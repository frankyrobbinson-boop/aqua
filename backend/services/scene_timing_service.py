import json
import os
import re
from typing import Optional

from services.voice_prep_service import _expand_numbers


def load_scene_plan(project_name: str) -> dict:
    with open(f"../projects/{project_name}/scene_plan.json") as f:
        return json.load(f)


def load_audio_timeline(project_name: str) -> list:
    with open(f"../projects/{project_name}/audio_timeline.json") as f:
        return json.load(f)


_NORMALIZE_RE = re.compile(r'[^a-z0-9]+')


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
    raw = re.split(r'[\s\-]+', expanded)
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
    first K normalized tokens; the match's global_start becomes the scene's
    start_time. Each scene ends where the next scene begins; the final scene
    ends at the last audio word's global_end. If a scene's needle can't be
    located (shorter needles tried first), that one scene falls back to a
    proportional estimate but the cursor and subsequent scenes are unaffected.
    """
    scenes = load_scene_plan(project_name)['scene_intent']
    timeline = load_audio_timeline(project_name)

    all_words = sorted(
        (w for chunk in timeline for w in chunk['words']),
        key=lambda w: w['global_start'],
    )
    n_words = len(all_words)
    norm_haystack = [_normalize_word(w['word']) for w in all_words]

    # Pre-compute proportional fallback indices (same math as before — used
    # only when exact match fails for a single scene).
    narration_counts = [len(_expand_numbers(s['narration']).split()) for s in scenes]
    total_narration = sum(narration_counts) or 1
    cumulative = 0
    proportional_idx = []
    for count in narration_counts:
        proportional_idx.append(min(int(cumulative / total_narration * n_words), n_words - 1))
        cumulative += count

    NEEDLE_K = 3  # 3 tokens is unique enough within a forward search window
                  # without being so long that minor tokenization differences
                  # at token 4+ (e.g. an inline [pause]) break the match.

    start_indices: list[int] = []
    cursor = 0
    for i, scene in enumerate(scenes):
        tokens = _tokenize_narration(scene.get('narration', ''))
        match = None
        # Try K=3 then K=2 then K=1 before giving up.
        for k in (NEEDLE_K, 2, 1):
            needle = tokens[:k]
            if not needle or not all(needle):
                continue
            match = _find_subsequence(norm_haystack, needle, start=cursor)
            if match is not None:
                break
        if match is None:
            sid = scene.get('id', i)
            excerpt = (scene.get('narration') or '').strip()[:60]
            needle_for_log = tokens[:NEEDLE_K]
            print(
                f"WARNING: scene {sid} fell back to proportional timing "
                f"(needle={needle_for_log!r} not found from word index {cursor}); "
                f"narration: {excerpt!r}"
            )
            match = proportional_idx[i]
            # IMPORTANT: don't advance cursor past a fallback match — that
            # would push a guessed position onto downstream exact searches.
            start_indices.append(match)
        else:
            start_indices.append(match)
            cursor = match + 1

    # Build windows. Each scene ends where the next begins; the last scene
    # runs to the end of the audio. If two scenes happened to resolve to the
    # same index (only possible via fallback or empty needle), nudge end to
    # the matched word's global_end so duration is never zero.
    result = []
    for i, scene in enumerate(scenes):
        start_idx = min(start_indices[i], n_words - 1)
        start_time = all_words[start_idx]['global_start']

        if i + 1 < len(scenes):
            next_idx = min(start_indices[i + 1], n_words - 1)
            end_time = all_words[next_idx]['global_start']
            if end_time <= start_time:
                end_time = all_words[start_idx]['global_end']
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
