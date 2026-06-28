"""LLM rerank for stock-footage candidates.

Pexels returns ~10 candidates per search, ordered by their internal relevance —
which is broad and frequently surfaces lifestyle stock for niche queries (a
person eating fruit when the topic is gardening, etc). This module asks Claude
Haiku 4.5 to look at each candidate's preview thumbnail and pick the one that
best matches the scene's narration, with the project's overall TOPIC threaded
in so the model can reject off-topic candidates regardless of niche.

Cost: ~$0.005–0.01 per scene at 8 candidates × low-res thumbnails. ~$0.30–0.60
per 60-scene video. Falls back to the first candidate on any error so the
pipeline never breaks because the reranker is unavailable.
"""

import json
import os
import re
import threading
from pathlib import Path
from typing import Optional

import anthropic
from dotenv import load_dotenv

from services import cost_ledger
from services.stock_provider import StockClip

load_dotenv()

_MODEL = "claude-haiku-4-5-20251001"
_MAX_CANDIDATES = 8

_client: Optional[anthropic.Anthropic] = None

# Module-level project_name -> topic cache. Reranker is called per-scene and
# the topic doesn't change within a run; re-reading research.json N times is
# wasted I/O. ``""`` is a sentinel for "tried and found nothing" so we don't
# re-check disk on every miss.
_TOPIC_CACHE: dict[str, str] = {}
_TOPIC_LOCK = threading.Lock()


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    return _client


def _load_project_topic(project_name: str) -> str:
    """Return the project's research topic, cached. Empty string if missing."""
    with _TOPIC_LOCK:
        if project_name in _TOPIC_CACHE:
            return _TOPIC_CACHE[project_name]
        topic = ""
        path = Path(f"../projects/{project_name}/research.json")
        if path.exists():
            try:
                with path.open() as f:
                    data = json.load(f)
                topic = (data.get("topic") or "").strip()
            except (OSError, json.JSONDecodeError):
                topic = ""
        _TOPIC_CACHE[project_name] = topic
        return topic


def rerank_candidates(
    narration: str,
    visual_description: str,
    candidates: list[StockClip],
    project_name: str | None = None,
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

    topic = _load_project_topic(project_name) if project_name else ""

    try:
        chosen_index = _ask_claude(
            narration, visual_description, pool, project_name, topic
        )
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
    project_name: str | None,
    topic: str,
) -> int:
    """Returns the 0-indexed position of the chosen candidate in pool."""
    topic_line = (
        f"Overall video topic: \"{topic}\"\n" if topic else ""
    )
    text_block = (
        "You're picking the best stock-footage clip for one scene of a YouTube "
        "video.\n\n"
        f"{topic_line}"
        f"Narration spoken over this clip: \"{narration}\"\n"
        f"Visual idea / search query: \"{visual_description}\"\n\n"
        f"Below are {len(pool)} candidate clips, each shown as a preview thumbnail "
        f"and numbered 1 to {len(pool)}. Pick the ONE that best fits as silent "
        "B-roll behind the narration. Prefer clips that literally show the "
        "subject described in the visual idea and that fit the overall topic. "
        "Reject clips that are off-topic or generic lifestyle imagery when a "
        "more literal match is available.\n\n"
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

    if project_name:
        usage = getattr(response, "usage", None)
        in_tok = getattr(usage, "input_tokens", 0) if usage else 0
        out_tok = getattr(usage, "output_tokens", 0) if usage else 0
        cost_ledger.record(
            project_name,
            stage="visuals",
            provider="anthropic",
            model=_MODEL,
            input_tokens=in_tok,
            output_tokens=out_tok,
            extra={"step": "rerank"},
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
