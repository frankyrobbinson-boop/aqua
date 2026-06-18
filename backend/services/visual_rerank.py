"""LLM rerank for stock-footage candidates.

Pexels returns ~10 candidates per search, ordered by their internal relevance —
which is broad and frequently surfaces lifestyle stock for niche queries (a
person eating fruit for a gardening clip, etc). This module asks Claude Haiku
4.5 to look at each candidate's preview thumbnail and pick the one that best
matches the scene's narration.

Cost: ~$0.005–0.01 per scene at 8 candidates × low-res thumbnails. ~$0.30–0.60
per 60-scene video. Falls back to the first candidate on any error so the
pipeline never breaks because the reranker is unavailable.
"""

import os
import re
from typing import Optional

import anthropic
from dotenv import load_dotenv

from services.stock_provider import StockClip

load_dotenv()

_MODEL = "claude-haiku-4-5-20251001"
_MAX_CANDIDATES = 8

_client: Optional[anthropic.Anthropic] = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    return _client


def rerank_candidates(
    narration: str,
    visual_description: str,
    candidates: list[StockClip],
) -> StockClip:
    """Pick the best clip from candidates using a vision LLM. Returns the first
    candidate if anything goes wrong — never raises."""
    if not candidates:
        raise ValueError("rerank_candidates called with empty list")
    if len(candidates) == 1:
        return candidates[0]

    # Only candidates with a preview URL can be reranked visually. Keep order.
    rankable = [c for c in candidates if c.preview_url]
    if len(rankable) < 2:
        return candidates[0]

    pool = rankable[:_MAX_CANDIDATES]

    try:
        chosen_index = _ask_claude(narration, visual_description, pool)
    except Exception as exc:
        print(f"  [rerank] WARNING: falling back to first candidate ({exc!r})")
        return candidates[0]

    if not (0 <= chosen_index < len(pool)):
        return candidates[0]
    return pool[chosen_index]


def _ask_claude(
    narration: str,
    visual_description: str,
    pool: list[StockClip],
) -> int:
    """Returns the 0-indexed position of the chosen candidate in pool."""
    text_block = (
        "You're picking the best stock-footage clip for one scene of a YouTube "
        "gardening video.\n\n"
        f"Narration spoken over this clip: \"{narration}\"\n"
        f"Visual idea / search query: \"{visual_description}\"\n\n"
        f"Below are {len(pool)} candidate clips, each shown as a preview thumbnail "
        f"and numbered 1 to {len(pool)}. Pick the ONE that best fits as silent "
        "B-roll behind the narration. Prefer clips that match the literal subject "
        "(plants, soil, tools, hands working, gardens) over generic lifestyle "
        "imagery (people eating, kids, unrelated activities) when the topic is "
        "specifically about plants or gardening.\n\n"
        f"Respond with ONLY a number from 1 to {len(pool)}."
    )

    content: list[dict] = [{"type": "text", "text": text_block}]
    for i, clip in enumerate(pool, start=1):
        content.append({"type": "text", "text": f"\nCandidate {i}:"})
        content.append({
            "type": "image",
            "source": {"type": "url", "url": clip.preview_url},
        })

    client = _get_client()
    response = client.messages.create(
        model=_MODEL,
        max_tokens=20,
        messages=[{"role": "user", "content": content}],
    )

    text = ""
    for block in response.content:
        if block.type == "text":
            text += block.text

    m = re.search(r"\d+", text)
    if not m:
        raise ValueError(f"Could not parse a number from response: {text!r}")
    one_indexed = int(m.group(0))
    return one_indexed - 1
