"""Build an ASS subtitle file from audio_timeline.json word timestamps.

Long sentences are split into sequential subtitle cards (≤ MAX_WORDS_PER_CARD
each) so each card always fits on a single line at the chosen font size. The
word currently being spoken is highlighted in a bright accent color. Each card
is rendered as one Dialogue line per word; the card stays on screen for the
span of its words.
"""

import json
import os
import re
from typing import List, Dict

from services.paths import PROJECTS_ROOT


# --- Layout / look knobs ----------------------------------------------------

# Each subtitle card is at most this many words. Set so cards always render
# on ONE line at FONT_SIZE inside a 1920×1080 frame (with side margins).
MAX_WORDS_PER_CARD = 7

FONT_NAME = "Arial Black"
# Temporary "a little bigger" bump (was 64) pending the full subtitle-style
# customization feature; MAX_WORDS_PER_CARD still keeps each card to one line.
FONT_SIZE = 76

# ASS style colors are &HAABBGGRR& (alpha + BGR). Inline \c overrides are
# &HBBGGRR& (BGR only). Store both shapes so the style block and inline tags
# stay correct.
PRIMARY_COLOUR_STYLE = "&H00FFFFFF&"     # white
OUTLINE_COLOUR_STYLE = "&H00000000&"     # black
SHADOW_COLOUR_STYLE = "&H80000000&"      # semi-transparent black

PRIMARY_INLINE = "&HFFFFFF&"             # white, for inline \c
HIGHLIGHT_INLINE = "&H00D4FF&"           # gold #FFD400 in BGR

OUTLINE_WIDTH = 5
SHADOW_DEPTH = 4
ALIGNMENT = 2          # 2 = bottom-center
MARGIN_L = 120
MARGIN_R = 120
MARGIN_V = 110

# Wrap style 2 = no automatic line wrap.
WRAP_STYLE = 2

# Highlight: color only (no bold) so glyph widths don't change as the highlight
# moves across the card.
_HL_ON = f"{{\\c{HIGHLIGHT_INLINE}}}"
_HL_OFF = f"{{\\c{PRIMARY_INLINE}}}"

_SENTENCE_END_CHARS = (".", "?", "!")

# Em-dash (—) and en-dash (–) are stripped from subtitle display — they're
# phrase-separator typography that reads as visual noise on screen. Regular
# hyphens (-) are kept so compound words like "year-old" stay intact.
_EM_DASHES = ("—", "–")

# Card-to-card transition behavior. By default the next card appears the
# frame the current one disappears (no flash of empty screen). Only when the
# silent gap between cards is genuinely long do we let the current card
# disappear naturally and leave a beat of silence — the kind of pause that's
# meaningful for the viewer (em-dash beats, sentence breaths). Tune below.
GAP_BRIDGE_THRESHOLD = 0.5   # s. Gap < this → cards transition back-to-back.
# When we DON'T bridge (a genuinely long pause), hold the finished card on
# screen toward the next card's start, capped at this many seconds. The old
# fixed 0.1s tail made cards vanish almost the instant the last word was
# spoken — subtitles "disappearing early" during every meaningful pause.
# 0.8s keeps the line readable through the breath while still leaving a beat
# of clean screen before the next card when the pause runs longer than that.
MAX_TAIL_HOLD = 0.8          # s. Cap on the post-word hold when not bridging.

# Highlight lead-in: a uniform shift (seconds) added to every highlight's
# start/end relative to the word's global_start. 0 = each word lights up ON its
# spoken onset — the tightest match the ElevenLabs word timestamps allow.
#
# A prior non-zero value (0.06) shifted the WHOLE track a uniform ~60ms LATE to
# counter highlights reading "early." But a uniform shift only re-centers the
# track; it cannot fix the per-word scatter inherent in the ASR timestamps (some
# onsets land a hair early, some late), and the added late bias made alignment
# read worse, not better. Kept as a re-tunable knob: nudge up a hair only if
# highlights consistently feel early, down if they feel late.
HIGHLIGHT_LEAD_IN = 0.0   # seconds (0 = highlight on the word's global_start)

# ASS Dialogue times are centisecond-precision; a trimmed cue narrower than
# one centisecond would be written with equal start/end (a zero-duration
# line), so _clip_to_blank_windows drops slivers below this instead.
_MIN_CUE_SPAN = 0.01   # s


def _format_time(seconds: float) -> str:
    """ASS time format: H:MM:SS.cc (centisecond precision)."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds - h * 3600 - m * 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _flatten_words(timeline: list) -> List[Dict]:
    words = [w for chunk in timeline for w in chunk["words"]]
    words.sort(key=lambda w: w["global_start"])
    return words


def _group_by_sentence(words: List[Dict]) -> List[List[Dict]]:
    """Split flat word list into sentence groups by trailing . ? !"""
    groups: List[List[Dict]] = []
    current: List[Dict] = []
    for w in words:
        current.append(w)
        if w["word"].rstrip().endswith(_SENTENCE_END_CHARS):
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    return groups


def _split_into_cards(sentence: List[Dict], max_words: int) -> List[List[Dict]]:
    """Split a sentence into balanced subtitle cards of at most max_words each.

    A 12-word sentence becomes 6+6, not 7+5. A 15-word sentence becomes 5+5+5."""
    n = len(sentence)
    if n <= max_words:
        return [sentence]

    # Number of cards = ceil(n / max_words). Balance words across them.
    n_cards = (n + max_words - 1) // max_words
    base = n // n_cards
    extra = n % n_cards  # first `extra` cards get one more word

    cards: List[List[Dict]] = []
    i = 0
    for c in range(n_cards):
        take = base + (1 if c < extra else 0)
        cards.append(sentence[i:i + take])
        i += take
    return cards


def _is_dash_token(token: str) -> bool:
    """True if token is purely em/en dashes (and whitespace). Used as a
    phrase-separator in the script; should not render in subtitles."""
    stripped = token.strip()
    return stripped != "" and all(ch in _EM_DASHES for ch in stripped)


_DASH_SPLIT_RE = re.compile(r'[—–]+')


def _split_dash_token(word: Dict) -> List[Dict]:
    """Expand a dash-joined ElevenLabs token into separate pseudo-words.

    ElevenLabs returns dash-joined phrases like 'before—you' or 'tag—Wave,'
    as a single audio token with one timestamp. The prior fix
    (`_clean_display` replacing the dash with a space) made them display
    as two visual words but they still shared one highlight slot — so the
    user saw two words light up simultaneously when the highlight reached
    that token.

    Splitting here at card-construction time gives each piece its own
    timestamp slice (equal divisions of the original duration) and its
    own highlight slot, so the karaoke effect advances word-by-word the
    way the viewer expects.
    """
    raw = word["word"]
    parts = [p for p in _DASH_SPLIT_RE.split(raw) if p.strip()]
    if len(parts) <= 1:
        return [word]
    start = word["global_start"]
    end = word["global_end"]
    duration = end - start
    if duration <= 0:
        # Defensive: zero-duration token. Same timestamp on every piece.
        return [
            {"word": p, "global_start": start, "global_end": end}
            for p in parts
        ]
    slice_dur = duration / len(parts)
    return [
        {
            "word": parts[i],
            "global_start": start + i * slice_dur,
            "global_end": start + (i + 1) * slice_dur,
        }
        for i in range(len(parts))
    ]


def _clean_display(token: str) -> str:
    """Replace em-dashes (—) and en-dashes (–) with a space for subtitle
    display. ElevenLabs returns dash-joined phrases like 'tag—Wave,' or
    'days—perfect.' as a single audio token; stripping the dash to empty
    glues the halves into 'tagWave' / 'daysperfect'. Replacing with a space
    keeps the words visually separated. Regular hyphens (-) are kept so
    compound words like 'year-old' stay intact."""
    for d in _EM_DASHES:
        token = token.replace(d, " ")
    return token


def _render_card_with_highlight(words: List[Dict], highlight_idx: int) -> str:
    """Return ASS line text with the word at highlight_idx wrapped in highlight tags."""
    parts = []
    for i, w in enumerate(words):
        token = _clean_display(w["word"])
        if i == highlight_idx:
            parts.append(f"{_HL_ON}{token}{_HL_OFF}")
        else:
            parts.append(token)
    return " ".join(parts)


def _ass_header() -> str:
    return (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "PlayResX: 1920\n"
        "PlayResY: 1080\n"
        f"WrapStyle: {WRAP_STYLE}\n"
        "ScaledBorderAndShadow: yes\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{FONT_NAME},{FONT_SIZE},{PRIMARY_COLOUR_STYLE},&H000000FF,"
        f"{OUTLINE_COLOUR_STYLE},{SHADOW_COLOUR_STYLE},"
        f"-1,0,0,0,100,100,0,0,1,{OUTLINE_WIDTH},{SHADOW_DEPTH},"
        f"{ALIGNMENT},{MARGIN_L},{MARGIN_R},{MARGIN_V},1\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, "
        "MarginV, Effect, Text\n"
    )


def _clip_to_blank_windows(
    start: float, end: float, blank_windows
) -> tuple[float, float] | None:
    """Trim the cue span [start, end] against the (bs, be) blank windows so no
    karaoke word is visible while a section card is on screen, WITHOUT dropping
    the visible part of a cue that merely straddles a card edge (the old
    suppress-on-any-overlap behavior made the last cue before every section
    card vanish entirely).

    Per window:
      - cue fully inside the window        → dropped (returns None)
      - cue straddles the entry edge (bs)  → trimmed to end at bs
      - cue straddles the exit edge (be)   → trimmed to start at be
    A cue that merely abuts an edge (end == bs or start == be) is untouched.
    Returns the (possibly trimmed) (start, end), or None when nothing visible
    remains — including slivers below the .ass centisecond precision, which
    would be emitted with equal start/end times (a zero-duration cue)."""
    for bs, be in blank_windows:
        if start >= bs and end <= be:
            return None  # fully under the card
        if start < bs < end:
            end = bs     # straddles the card's entry edge (or spans the window)
        elif bs <= start < be:
            start = be   # straddles the card→footage seam
        if end - start < _MIN_CUE_SPAN:
            return None
    return start, end


def build_subtitles(
    project_name: str,
    output_path: str,
    blank_windows: List[tuple] | None = None,
) -> str:
    """Build the burned-in karaoke subtitles from the word-level audio timeline.

    ``blank_windows`` (optional): a list of ``(start, end)`` time windows in
    seconds covered by a section card (see assembly_service — a card fronts a
    section-intro scene, eating into that scene's own frames). Any subtitle cue
    that plays entirely inside one of these windows is dropped, and a cue that
    straddles a window edge is TRIMMED at that edge (see
    ``_clip_to_blank_windows``), so no karaoke word is ever visible while a
    card is on screen — but the visible part of an edge-straddling cue is kept
    instead of the whole cue vanishing. ``None`` (the default) drops nothing —
    the output is identical to the pre-card behavior, so the normal render
    path is unaffected."""
    blank = blank_windows or []
    timeline_path = PROJECTS_ROOT / project_name / "audio_timeline.json"
    with timeline_path.open() as f:
        timeline = json.load(f)

    words = _flatten_words(timeline)
    if not words:
        raise ValueError(f"No words in audio_timeline for {project_name}")

    sentences = _group_by_sentence(words)

    # Flatten sentences → cards, filtering pure-dash tokens (em-dashes used as
    # phrase separators). The dash's time slot is absorbed via the bridging
    # logic below — the previous word's display extends across it.
    all_cards: List[List[Dict]] = []
    for sentence in sentences:
        for card_words in _split_into_cards(sentence, MAX_WORDS_PER_CARD):
            # Expand dash-joined tokens FIRST so each piece gets its own
            # highlight slot, then filter out any pure-dash tokens (which
            # are phrase separators that shouldn't render at all).
            expanded: List[Dict] = []
            for w in card_words:
                expanded.extend(_split_dash_token(w))
            cleaned = [w for w in expanded if not _is_dash_token(w["word"])]
            if cleaned:
                all_cards.append(cleaned)

    dialogue_lines: List[str] = []
    for ci, card_words in enumerate(all_cards):
        # Where does the next card start? Used to bridge consecutive cards
        # back-to-back when the gap is small (the common case) and let the
        # current card disappear naturally when the gap is genuinely long.
        next_card_start = (
            all_cards[ci + 1][0]["global_start"]
            if ci + 1 < len(all_cards)
            else None
        )
        for wi, w in enumerate(card_words):
            # Shift the whole highlight track later by HIGHLIGHT_LEAD_IN so each
            # word lights up ON the word rather than a hair early. The shift is
            # applied uniformly to BOTH start and end so card durations and
            # back-to-back bridging between cards are preserved.
            start = w["global_start"] + HIGHLIGHT_LEAD_IN
            if wi + 1 < len(card_words):
                # Mid-card: hold the highlight until the next word starts so
                # the display doesn't flicker between words during micro-silences.
                end = card_words[wi + 1]["global_start"] + HIGHLIGHT_LEAD_IN
            else:
                # Last word of card. Decide whether to bridge into the next card.
                natural_end = w["global_end"]
                if next_card_start is None:
                    # Final card of the video: hold the readability tail.
                    end = natural_end + MAX_TAIL_HOLD + HIGHLIGHT_LEAD_IN
                elif next_card_start - natural_end < GAP_BRIDGE_THRESHOLD:
                    end = next_card_start + HIGHLIGHT_LEAD_IN  # bridge: next card appears the frame this one ends
                else:
                    # Real silent gap: hold toward the next card, capped at
                    # MAX_TAIL_HOLD, so the line stays readable through the
                    # pause instead of vanishing right after the last word.
                    end = min(next_card_start, natural_end + MAX_TAIL_HOLD) + HIGHLIGHT_LEAD_IN
            # Clamp the shifted start (only the very first line can be affected)
            # and guard end > start defensively (holds since both shift equally).
            start = max(0.0, start)
            if end <= start:
                end = start
            if blank:
                clipped = _clip_to_blank_windows(start, end, blank)
                if clipped is None:
                    continue  # cue plays entirely under a section card — drop
                start, end = clipped
            text = _render_card_with_highlight(card_words, wi)
            dialogue_lines.append(
                f"Dialogue: 0,{_format_time(start)},{_format_time(end)},"
                f"Default,,0,0,0,,{text}\n"
            )

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        f.write(_ass_header())
        f.writelines(dialogue_lines)

    return output_path
