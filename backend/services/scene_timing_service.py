import json
import os
import re
from typing import Optional

from services.voice_prep_service import _expand_numbers


class SceneTimingError(Exception):
    """Raised when a scene's narration cannot be located in the audio timeline.

    A missing match almost always means the LLM hallucinated narration that was
    never spoken — letting it fall through to a proportional guess silently
    poisons downstream timing (subtitles, footage windows, render durations).
    The single tolerated case is a hallucinated final-scene CTA when essentially
    no audio remains; that is handled inline by dropping the scene with a
    warning, not by raising.
    """


def load_scene_plan(project_name: str) -> dict:
    with open(f"../projects/{project_name}/scene_plan.json") as f:
        return json.load(f)


def load_audio_timeline(project_name: str) -> list:
    with open(f"../projects/{project_name}/audio_timeline.json") as f:
        return json.load(f)


_NORMALIZE_RE = re.compile(r'[^a-z0-9]+')

# Split on whitespace, ASCII hyphen, and the Unicode dash family
# (em-dash, en-dash, minus sign, hyphen, non-breaking hyphen, figure dash).
# ElevenLabs returns concatenated audio tokens like 'zinnias—Zinnia' with no
# surrounding whitespace, so if we only split on \s and '-' the haystack token
# becomes 'zinniaszinnia' and the needle ['zinnias','zinnia'] can never line
# up. Both haystack and needle tokenizers must use this same splitter.
_TOKEN_SPLIT_RE = re.compile(r'[\s\-—–−‐‑‒]+')


def _normalize_word(s: str) -> str:
    """Lowercase and strip everything that isn't a letter or digit.

    Audio words from ElevenLabs come with trailing punctuation attached
    ('trellis,', 'thumb,'), and scene narration contains apostrophes,
    em-dashes, brackets, and quotes that don't appear in the spoken token.
    Stripping to [a-z0-9] makes both sides comparable.
    """
    return _NORMALIZE_RE.sub('', s.lower())


def _tokenize_narration(text: str) -> list[str]:
    """Convert scene narration into the same normalized token sequence the
    audio words use. Numerals are expanded first (so '5%' -> 'five percent'
    matches what was actually spoken), then we split on whitespace and on
    hyphens so 'salt-and-sugar' becomes ['salt','and','sugar'] like
    ElevenLabs returns it."""
    expanded = _expand_numbers(text)
    raw = _TOKEN_SPLIT_RE.split(expanded)
    return [n for n in (_normalize_word(t) for t in raw) if n]


def _find_subsequence(haystack: list[str], needle: list[str], start: int = 0) -> Optional[int]:
    """Return the index in `haystack` (>= start) where `needle` appears as a
    contiguous run of equal strings, or None. Both sides are already
    normalized by the caller. O(n*k) is fine — haystack is a few thousand
    words, k is 1-3."""
    if not needle:
        return None
    k = len(needle)
    last = len(haystack) - k
    for i in range(start, last + 1):
        if haystack[i:i + k] == needle:
            return i
    return None


def compute_scene_windows(project_name: str) -> list:
    """Assign [start_time, end_time] to each scene by locating each scene's
    first words as actual text inside the word-level audio timeline.

    For each scene in order we search forward from the cursor for the scene's
    first K=NEEDLE_K normalized tokens; the match's global_start becomes the
    scene's start_time. Each scene ends where the next scene begins; the final
    scene ends at the last audio word's global_end.

    A scene whose needle can't be located from the cursor triggers a SEMANTIC
    second-pass: search the WHOLE haystack from index 0 for the same needle.
    The outcome of that second search determines what we do:

      * Not found anywhere -> the LLM hallucinated narration that was never
        spoken. If it's the final scene, drop it with a warning (common CTA
        bug). Otherwise raise — a hallucinated mid-pipeline scene poisons
        every downstream timestamp consumer and needs investigation.
      * Found, but only at positions < cursor -> scene order is inverted vs
        the actual audio (an earlier scene already advanced past it). This
        is always a real bug; raise.
      * Found at position >= cursor -> unreachable in principle (the cursor
        search should have found it). Belt-and-braces; raise.

    The only tolerated silent drop is the final-scene hallucination case.
    Everything else is loud by design.
    """
    scenes = load_scene_plan(project_name)['scene_intent']
    timeline = load_audio_timeline(project_name)

    all_words = sorted(
        (w for chunk in timeline for w in chunk['words']),
        key=lambda w: w['global_start'],
    )

    # Build the haystack with the SAME tokenization rule the needle uses
    # (_TOKEN_SPLIT_RE: whitespace + the Unicode dash family, then strip
    # non-alphanumerics). The dash split is critical: ElevenLabs returns
    # 'one-size-fits-all' and 'zinnias—Zinnia' as single concatenated tokens,
    # so without splitting them the haystack becomes 'onesizefitsall' /
    # 'zinniaszinnia' and the corresponding needle can never line up.
    # Track which audio word each haystack token came from so the final word
    # index still maps back to a real global_start/global_end.
    norm_haystack: list[str] = []
    haystack_to_audio: list[int] = []
    for audio_idx, w in enumerate(all_words):
        for piece in _TOKEN_SPLIT_RE.split(w['word']):
            n = _normalize_word(piece)
            if n:
                norm_haystack.append(n)
                haystack_to_audio.append(audio_idx)

    NEEDLE_K = 6  # 6 tokens is long enough to be uniquely identifying across
                  # the whole video (3-token phrases like ['the','one','size']
                  # collide too often). When both sides tokenize identically
                  # (whitespace+hyphen split, strip non-alphanumerics, expand
                  # numerals), a 6-token prefix should always match cleanly.
                  # The only exception is a scene whose total normalized
                  # narration is shorter than 6 tokens — then we use all of it.

    # Walk scenes forward, recording (scene_dict, start_haystack_index) only
    # for scenes that resolved to real audio. `cursor` indexes the haystack
    # and is forward-only.
    n_haystack = len(norm_haystack)
    resolved: list[tuple[dict, int]] = []
    cursor = 0
    for i, scene in enumerate(scenes):
        tokens = _tokenize_narration(scene.get('narration', ''))
        sid = scene.get('id', i)
        excerpt = (scene.get('narration') or '').strip()[:80]

        if not tokens:
            raise SceneTimingError(
                f"Scene {sid} has empty/non-tokenizable narration; cannot "
                f"locate in audio timeline. Narration: {excerpt!r}"
            )

        # Use the full prefix up to NEEDLE_K. If the scene's total normalized
        # narration is shorter, use whatever it has (we already errored on zero).
        needle = tokens[:NEEDLE_K]
        match = _find_subsequence(norm_haystack, needle, start=cursor)

        if match is not None:
            resolved.append((scene, match))
            cursor = match + 1
            continue

        # Cursor-based search missed. Do a whole-haystack semantic check to
        # classify WHY it missed.
        is_final = (i == len(scenes) - 1)
        global_match = _find_subsequence(norm_haystack, needle, start=0)

        if global_match is None:
            # Not present anywhere in the audio — LLM hallucinated this scene.
            if is_final:
                print(
                    f"WARNING: dropping scene {sid} — hallucinated narration "
                    f"(not present in audio timeline) — dropped from output. "
                    f"Narration: {excerpt!r}"
                )
                continue
            raise SceneTimingError(
                f"Scene {sid} narration not present anywhere in the audio "
                f"timeline (needle={needle!r}). This is a mid-pipeline LLM "
                f"hallucination — the scene_plan.json contains narration that "
                f"was never spoken in the rendered audio. Inspect that scene "
                f"in scene_plan.json. Narration: {excerpt!r}"
            )

        if global_match < cursor:
            # Found earlier in the audio than where we are now — scene order
            # is inverted vs the actual narration. Real bug, always raise.
            raise SceneTimingError(
                f"Scene {sid} narration found in audio at haystack index "
                f"{global_match}, but cursor is already at {cursor} — scene "
                f"order in scene_plan.json is inverted vs the audio timeline. "
                f"Narration: {excerpt!r}"
            )

        # global_match >= cursor but cursor-search returned None. Shouldn't
        # be possible (same haystack, same needle, same start floor).
        raise SceneTimingError(
            f"Scene {sid}: unreachable branch — needle found globally at "
            f"{global_match} (>= cursor {cursor}) but cursor-based search "
            f"returned None. Likely a bug in _find_subsequence. "
            f"Narration: {excerpt!r}"
        )

    # Build windows. Each scene ends where the next begins; the last surviving
    # scene runs to the end of the audio. Translate haystack indices back to
    # audio-word indices via haystack_to_audio so timestamps come from the
    # real word the piece came from (hyphen-split pieces share a timestamp).
    result = []
    for idx, (scene, start_hay_idx) in enumerate(resolved):
        audio_idx = haystack_to_audio[min(start_hay_idx, n_haystack - 1)]
        start_time = all_words[audio_idx]['global_start']

        if idx + 1 < len(resolved):
            next_hay = min(resolved[idx + 1][1], n_haystack - 1)
            next_audio = haystack_to_audio[next_hay]
            end_time = all_words[next_audio]['global_start']
        else:
            end_time = all_words[-1]['global_end']

        result.append({
            **scene,
            'start_time': round(start_time, 3),
            'end_time': round(end_time, 3),
            'duration': round(end_time - start_time, 3),
        })

    return result


def save_scene_windows(project_name: str, windows: list):
    folder = f"../projects/{project_name}"
    os.makedirs(folder, exist_ok=True)
    with open(f"{folder}/scene_windows.json", "w") as f:
        json.dump(windows, f, indent=2)


def load_scene_windows(project_name: str) -> list:
    with open(f"../projects/{project_name}/scene_windows.json") as f:
        return json.load(f)
