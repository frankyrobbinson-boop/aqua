"""Deterministic, no-LLM relevance filter for stock-footage candidates.

Replaces the Claude-Haiku vision rerank (``visual_rerank``) with a free,
deterministic slug match. Pexels returns ~10 candidates per search ordered by
its own broad relevance, which frequently surfaces off-topic lifestyle stock for
a niche subject. Rather than pay a vision model to reject those, we keep a clip
ONLY when the scene's subject noun shows up in the clip's page-URL slug (Pexels
slugs are human-authored and descriptive, e.g.
``/video/a-bee-on-a-purple-flower-12345/``).

Bias is deliberately toward REJECT: when the slug doesn't clearly name the
subject, we drop the clip so the orchestrator routes the scene to an on-topic
AI image instead of gambling on a generic stock clip.

Public:
    filter_on_topic(candidates, subject) -> list[StockClip]
        On-topic clips in input (Pexels relevance) order; [] when none match.
    clip_matches_subject(clip, subject) -> bool
"""

from __future__ import annotations

import re
import urllib.parse

from services.stock_provider import StockClip


def _slug_tokens(page_url: str | None) -> list[str]:
    """Lowercased word tokens from a stock page URL's slug — the last non-empty
    path segment, split on ``-`` / ``_`` / whitespace, with pure-digit tokens
    (the trailing numeric id) dropped. Empty list when there's no usable slug."""
    if not page_url:
        return []
    path = urllib.parse.urlparse(page_url).path
    segments = [s for s in path.split("/") if s]
    if not segments:
        return []
    tokens = re.split(r"[-_\s]+", segments[-1].lower())
    return [t for t in tokens if t and not t.isdigit()]


def _variants(word: str) -> set[str]:
    """A word plus light singular/plural variants (±s / ±es). Deterministic — no
    real stemming, just enough to fold 'plant'/'plants' and 'bush'/'bushes' so a
    match isn't missed on a trivial number difference."""
    w = (word or "").lower()
    out = {w}
    if len(w) > 3 and w.endswith("es"):
        out.add(w[:-2])   # bushes -> bush
    if len(w) > 2 and w.endswith("s"):
        out.add(w[:-1])   # plants -> plant
    out.add(w + "s")      # plant -> plants
    out.add(w + "es")     # bush -> bushes
    return out


def clip_matches_subject(clip: StockClip, subject: str) -> bool:
    """True iff the clip's page-URL slug names the scene's ``subject`` (its head
    noun), folding light singular/plural variants. Bias toward REJECT: an empty
    subject, or a slug that doesn't clearly contain the subject, returns False so
    the caller falls back to an on-topic AI image."""
    subj = (subject or "").strip().lower()
    if not subj:
        return False
    slug = set(_slug_tokens(clip.page_url))
    if not slug:
        return False
    return bool(_variants(subj) & slug)


def filter_on_topic(candidates: list[StockClip], subject: str) -> list[StockClip]:
    """Keep only candidates whose page-URL slug is on-topic for ``subject``,
    preserving the input (Pexels relevance) order. Returns ``[]`` when none match
    — the caller treats that as 'no on-topic stock' and routes the scene to the
    AI-image fallback. Deterministic and free; biased toward REJECT so off-topic
    lifestyle stock is dropped in favor of an on-topic AI image."""
    subj = (subject or "").strip().lower()
    if not subj:
        return []
    return [c for c in candidates if clip_matches_subject(c, subj)]
