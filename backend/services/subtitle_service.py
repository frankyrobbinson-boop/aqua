"""Build an ASS subtitle file from audio_timeline.json word timestamps.

Long sentences are split into sequential subtitle cards (≤ MAX_WORDS_PER_CARD
each) so each card always fits on a single line at the chosen font size. The
word currently being spoken is highlighted in a bright accent color. Each card
is rendered as one Dialogue line per word; the card stays on screen for the
span of its words.
"""

import json
import os
from typing import List, Dict


# --- Layout / look knobs ----------------------------------------------------

# Each subtitle card is at most this many words. Set so cards always render
# on ONE line at FONT_SIZE inside a 1920×1080 frame (with side margins).
MAX_WORDS_PER_CARD = 7

FONT_NAME = "Arial Black"
FONT_SIZE = 64

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


def _render_card_with_highlight(words: List[Dict], highlight_idx: int) -> str:
    """Return ASS line text with the word at highlight_idx wrapped in highlight tags."""
    parts = []
    for i, w in enumerate(words):
        token = w["word"]
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


def build_subtitles(project_name: str, output_path: str) -> str:
    timeline_path = f"../projects/{project_name}/audio_timeline.json"
    with open(timeline_path) as f:
        timeline = json.load(f)

    words = _flatten_words(timeline)
    if not words:
        raise ValueError(f"No words in audio_timeline for {project_name}")

    sentences = _group_by_sentence(words)

    dialogue_lines: List[str] = []
    for sentence in sentences:
        for card_words in _split_into_cards(sentence, MAX_WORDS_PER_CARD):
            for i, w in enumerate(card_words):
                start = w["global_start"]
                # Hold the highlight until the next word actually starts so the
                # display doesn't flicker between words during micro-silences.
                if i + 1 < len(card_words):
                    end = card_words[i + 1]["global_start"]
                else:
                    end = w["global_end"]
                text = _render_card_with_highlight(card_words, i)
                dialogue_lines.append(
                    f"Dialogue: 0,{_format_time(start)},{_format_time(end)},"
                    f"Default,,0,0,0,,{text}\n"
                )

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        f.write(_ass_header())
        f.writelines(dialogue_lines)

    return output_path
