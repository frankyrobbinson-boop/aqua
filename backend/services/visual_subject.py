"""Deterministic per-scene visual SUBJECT + stock-search-query derivation.

A scene's ``visual_description`` (e.g. "hosta white flowers opening dusk") leads
with a concrete subject noun. Two places need that subject WITHOUT calling any
model:

  * ``visual_rerank`` anchors its keep/reject decision on it ("does this clip
    genuinely show {subject}?").
  * ``visual_pexels`` leads the Pexels query with it and drops adjective / mood
    filler, so the stock search returns the real subject more often before the
    (paid) AI-image fallback fires.

This head-noun heuristic is the single source of truth: ``edl_service`` (which
uses the same subject to place blur-dissolve seams) imports
``subject_from_description`` from here rather than keeping its own copy. Tune
``_LEADING_MODIFIERS`` to change subject detection everywhere at once.
"""

from __future__ import annotations

import re

# Leading modifiers skipped when reading a visual_description's SUBJECT (its head
# noun): articles / prepositions + common colour / framing / size / season
# words, so e.g. "red bee balm ..." reads subject "bee" and "scarlet penstemon
# ..." reads "penstemon". Deterministic — tune this set to change subject
# detection. (Moved verbatim from edl_service._VISUAL_SUBJECT_SKIP so the two
# call sites can never drift.)
_LEADING_MODIFIERS = frozenset({
    "a", "an", "the", "of", "in", "on", "at", "to", "with", "and", "near", "by",
    "red", "blue", "orange", "white", "green", "violet", "crimson", "scarlet",
    "coral", "pink", "yellow", "purple", "deep", "pale", "dark", "light",
    "tall", "single", "small", "big", "large", "long", "short", "full",
    "dry", "empty", "fresh", "wilting", "spent", "faded",
    "spring", "summer", "autumn", "fall", "winter", "late", "early",
    "morning", "evening", "day",
    "close", "closeup", "macro", "wide", "slow", "quick", "fast", "soft",
})


def _norm_tokens(text: str) -> list[str]:
    """Lowercase ``[a-z0-9]+`` tokens of ``text`` (case / punctuation /
    whitespace insensitive)."""
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def subject_from_description(description: str) -> str:
    """The head-noun SUBJECT token of a ``visual_description`` — its first
    normalized token that isn't a leading modifier (``_LEADING_MODIFIERS``).
    Empty string when the description is empty or all modifiers.

    Examples:
        "hosta white flowers opening dusk"     -> "hosta"
        "deer eating garden plants at night"   -> "deer"
        "mulched hosta garden bed dark soil"   -> "mulched"
    """
    for tok in _norm_tokens(description):
        if tok not in _LEADING_MODIFIERS:
            return tok
    return ""


def scene_subject(scene: dict) -> str:
    """Convenience: ``subject_from_description`` of a scene's
    ``visual_description`` (empty string when the scene or field is missing)."""
    return subject_from_description((scene or {}).get("visual_description") or "")


def search_query_from_description(description: str) -> str:
    """A subject-first stock-search query: the description's tokens with the
    recognized leading-modifier filler (colours, sizes, seasons, framing / mood
    words) dropped, preserving order. Because the SUBJECT is by definition the
    first surviving token, the query always leads with it.

    Conservative — only known modifier words are removed; every noun / verb is
    kept. Returns an empty string when every token is filler, so the caller can
    fall back to the full ``visual_description``.

    Examples:
        "hosta white flowers opening dusk"    -> "hosta flowers opening dusk"
        "deer eating garden plants at night"  -> "deer eating garden plants night"
        "organic mulch spread around hosta crown"
                                              -> "organic mulch spread around hosta crown"
    """
    return " ".join(
        t for t in _norm_tokens(description) if t not in _LEADING_MODIFIERS
    )
