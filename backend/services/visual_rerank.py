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
from services.paths import PROJECTS_ROOT
from services.stock_provider import StockClip
from services.visual_subject import subject_from_description

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
        path = PROJECTS_ROOT / project_name / "research.json"
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
    subject: str | None = None,
) -> Optional[StockClip]:
    """Pick the best clip from ``candidates`` using a vision LLM, anchored on the
    scene's ``subject`` (its head noun; derived from ``visual_description`` when
    not passed).

    Returns:
      * the chosen ``StockClip`` on success;
      * ``candidates[0]`` on ANY error / unparseable response — an error is a
        SOFT failure, never a reject, so the pipeline never breaks just because
        the reranker is unavailable;
      * ``None`` ONLY when the model EXPLICITLY rejects every candidate (it
        answered 0 = "none of these genuinely shows {subject}"), so the caller
        can route the scene to an on-topic AI-image fallback.

    Never raises except on an empty ``candidates`` list (a caller bug)."""
    if not candidates:
        raise ValueError("rerank_candidates called with empty list")
    if subject is None:
        subject = subject_from_description(visual_description)
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
            narration, visual_description, pool, project_name, topic, subject
        )
    except Exception as exc:
        print(f"  [rerank] WARNING: falling back to first candidate ({exc!r})")
        return candidates[0]

    if chosen_index is None:
        # Explicit reject: the model looked at the thumbnails and said none
        # genuinely shows the subject. Signal the caller for an AI-image fallback.
        print(
            f"  [rerank] no candidate genuinely shows {subject!r}; "
            f"rejecting all {len(pool)} for AI-image fallback"
        )
        return None

    if not (0 <= chosen_index < len(pool)):
        return candidates[0]
    return pool[chosen_index]


def _ask_claude(
    narration: str,
    visual_description: str,
    pool: list[StockClip],
    project_name: str | None,
    topic: str,
    subject: str,
) -> Optional[int]:
    """Return the 0-indexed position of the chosen candidate in ``pool``, or
    ``None`` when the model explicitly rejects them all (answered 0). Raises on
    an unparseable response so the caller treats it as a soft error (fall back to
    the first candidate) rather than a reject."""
    topic_line = (
        f"Overall video topic: \"{topic}\"\n" if topic else ""
    )
    subject_line = (
        f"The scene's SUBJECT is: \"{subject}\"\n" if subject else ""
    )
    subject_name = subject or "the subject described in the visual idea"
    text_block = (
        "You're picking the best stock-footage clip for one scene of a YouTube "
        "video.\n\n"
        f"{topic_line}"
        f"{subject_line}"
        f"Narration spoken over this clip: \"{narration}\"\n"
        f"Visual idea / search query: \"{visual_description}\"\n\n"
        f"Below are {len(pool)} candidate clips, each shown as a preview thumbnail "
        f"and numbered 1 to {len(pool)}. Pick the ONE that best fits as silent "
        f"B-roll behind the narration. It MUST genuinely show {subject_name} — "
        "prefer clips that literally show the subject and fit the overall topic, "
        "and reject off-topic or generic lifestyle imagery.\n\n"
        f"If NONE of the {len(pool)} clips genuinely shows {subject_name}, "
        "answer 0 instead.\n\n"
        f"Respond with ONLY a number from 0 to {len(pool)} "
        "(0 = none genuinely shows it)."
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
    n = int(m.group(0))
    if n == 0:
        return None  # explicit reject — none of the candidates is on-topic
    return n - 1
