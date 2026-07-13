"""Pexels stock-video provider conforming to the VisualProvider interface.

Wraps the Pexels REST client + the deterministic on-topic filter from
``stock_provider`` / ``visual_relevance``. Behavior matches the pre-refactor
``visual_service.fetch_scene_footage`` per-scene loop one-for-one:

  - Search Pexels for the scene's visual_description
  - Filter to clips that meet the scene's required duration
  - Keep only candidates whose slug is on-topic for the scene's subject
  - Avoid duplicating clip IDs already chosen this run
  - Download the winner to ``footage/scene_<sid:03d>.mp4``
  - Write a ``.cache.json`` sidecar keyed by visual_description + stock_id

The per-run de-dup set lives on the instance, so callers must reuse one
``PexelsProvider`` instance for the duration of a fetch_all_scene_footage run
(the orchestrator does this). Crossing instances would re-allow duplicates,
which used to be enforced by the in-function ``used_clip_ids`` local set.
"""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Callable, List

import requests
from dotenv import load_dotenv

from services.stock_provider import StockClip, StockProvider, pick_best
from services.visual_provider import (
    NoOnTopicFootage,
    VisualProvider,
    cache_path_for,
    clean_other_mode_files,
    footage_dir_for,
    is_cache_valid,
    write_cache,
)
from services.visual_relevance import filter_on_topic
from services.visual_subject import (
    search_query_from_description,
    subject_from_description,
)

load_dotenv()

_SEARCH_URL = "https://api.pexels.com/videos/search"
_TARGET_W, _TARGET_H = 1920, 1080

# Retry policy for transient Pexels failures (rate limit / 5xx / network).
_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 2.0  # seconds; exponential backoff: 2, 4, 8


def _pexels_call_with_retry(fn: Callable, *, label: str):
    """Run ``fn`` with exponential backoff on transient HTTP errors. Catches
    requests.exceptions.RequestException (covers network/timeout/SSL) and
    HTTPError where status_code is 5xx OR 429. Other HTTPErrors (4xx like
    400/401/403) are permanent and propagate immediately."""
    last_exc: Exception | None = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            return fn()
        except requests.exceptions.HTTPError as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status is not None and status < 500 and status != 429:
                raise
            last_exc = exc
        except requests.exceptions.RequestException as exc:
            last_exc = exc
        if attempt == _MAX_RETRIES:
            break
        delay = _RETRY_BASE_DELAY * (2 ** (attempt - 1))
        print(
            f"  [pexels {label}] transient error "
            f"({type(last_exc).__name__}); retry {attempt}/{_MAX_RETRIES - 1} "
            f"in {delay:.1f}s",
            flush=True,
        )
        time.sleep(delay)

    raise RuntimeError(
        f"Pexels {label} failed after {_MAX_RETRIES} attempts: {last_exc!r}"
    ) from last_exc


# ---------------------------------------------------------------------------
# Low-level Pexels REST client (was ``stock_pexels.PexelsProvider``)
# ---------------------------------------------------------------------------

class _PexelsClient(StockProvider):
    """Internal REST client. Conforms to ``StockProvider`` so a future stock
    provider (e.g. Storyblocks) can drop into the same adapter shape."""

    name = "pexels"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.getenv("PEXELS_API_KEY")
        if not self.api_key:
            raise RuntimeError(
                "PEXELS_API_KEY not set. Get one at https://www.pexels.com/api/ "
                "and add it to backend/.env"
            )
        self._headers = {"Authorization": self.api_key}

    def search(
        self,
        query: str,
        min_duration: float,
        orientation: str = "landscape",
        max_results: int = 10,
        page: int = 1,
    ) -> List[StockClip]:
        params = {
            "query": query,
            "per_page": max_results,
            "orientation": orientation,
            "size": "medium",  # >= HD; "large" forces 4K+ and starves results
            "page": page,
        }
        url = f"{_SEARCH_URL}?{urllib.parse.urlencode(params)}"

        def _do_search():
            response = requests.get(url, headers=self._headers, timeout=20)
            response.raise_for_status()
            return response.json()

        data = _pexels_call_with_retry(_do_search, label=f"search p{page}")

        clips: List[StockClip] = []
        for video in data.get("videos", []):
            file = _pick_video_file(video.get("video_files", []))
            if not file:
                continue
            clips.append(StockClip(
                id=str(video["id"]),
                download_url=file["link"],
                duration=float(video.get("duration", 0)),
                width=int(file.get("width") or video.get("width") or 0),
                height=int(file.get("height") or video.get("height") or 0),
                provider=self.name,
                preview_url=video.get("image"),
                page_url=video.get("url"),
            ))
        return clips

    def download(self, clip: StockClip, output_path: str) -> str:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        def _do_download():
            with requests.get(clip.download_url, stream=True, timeout=60) as r:
                r.raise_for_status()
                with open(output_path, "wb") as f:
                    shutil.copyfileobj(r.raw, f)
            return output_path

        return _pexels_call_with_retry(_do_download, label=f"download {clip.id}")


def _pick_video_file(files: list) -> dict | None:
    """Pick the smallest MP4 that's at least 1920x1080. Prefer just-big-enough
    over 4K to keep download size and ffmpeg work down."""
    mp4s = [
        f for f in files
        if (f.get("file_type") == "video/mp4")
        and (f.get("width") or 0) >= _TARGET_W
        and (f.get("height") or 0) >= _TARGET_H
    ]
    if mp4s:
        return min(mp4s, key=lambda f: f.get("width", 0) * f.get("height", 0))
    # No HD+ available — fall back to the largest MP4 we can get.
    any_mp4 = [f for f in files if f.get("file_type") == "video/mp4"]
    if any_mp4:
        return max(any_mp4, key=lambda f: f.get("width", 0) * f.get("height", 0))
    return None


# ---------------------------------------------------------------------------
# VisualProvider adapter
# ---------------------------------------------------------------------------

class PexelsVisualProvider(VisualProvider):
    """Per-scene Pexels fetch + cache. Reuse one instance per orchestrator run
    so the dedup set spans all scenes (a fresh instance would let two scenes
    pick the same Pexels clip without realizing)."""

    provider_id = "pexels"
    mode = "stock_video"

    def __init__(self, client: _PexelsClient | None = None):
        self._client = client or _PexelsClient()
        self._used_clip_ids: set[str] = set()
        self._used_lock = threading.Lock()

    def fetch_for_scene(
        self, project_name: str, scene: dict, *, allow_ai_fallback: bool = True
    ) -> Path:
        """Fetch one on-topic stock clip for ``scene``.

        Raises ``NoOnTopicFootage`` when no candidate genuinely shows the scene's
        subject across the pages tried (empty results or the slug filter rejected
        every candidate); the orchestrator catches that to route the scene to the
        AI-image provider. When ``allow_ai_fallback`` is False the orchestrator
        has already spent its fallback budget, so we accept Pexels' best-effort
        clip instead of raising (a mediocre clip beats a missing scene)."""
        sid = scene["id"]
        footage_dir = footage_dir_for(project_name)
        output = footage_dir / f"scene_{sid:03d}.mp4"

        full_description = (scene.get("visual_description") or "").strip()
        # Subject-first query: lead with the scene's subject noun and drop
        # adjective / mood filler so Pexels returns the real subject more often
        # before the (paid) AI-image fallback fires. Falls back to the full
        # description when stripping leaves nothing. The query is ALSO the cache
        # key, so a scene whose derived query differs from its existing sidecar
        # re-fetches once on the next run — intentional and self-healing.
        query = search_query_from_description(full_description) or full_description
        subject = subject_from_description(full_description)

        if is_cache_valid(output, {"visual_description": query}):
            print(f"  [scene {sid}] cached -> {output}", flush=True)
            # Pre-populate the used set so fresh fetches in this run respect
            # what's already on disk. Legacy sidecars without stock_id are
            # silently skipped — the only cost is a possible duplicate against
            # them, which the next run will resolve once the sidecar rewrites.
            try:
                with open(cache_path_for(output)) as cf:
                    cached = json.load(cf)
                cid = cached.get("stock_id")
                if cid is not None:
                    with self._used_lock:
                        self._used_clip_ids.add(str(cid))
            except (OSError, json.JSONDecodeError):
                pass
            return output

        if not query:
            raise ValueError(f"Scene {sid} has no visual_description to search with")

        # Degrade path: the orchestrator exhausted its AI-image fallback budget,
        # so accept Pexels' best candidate WITHOUT the relevance reject rather
        # than error the scene.
        if not allow_ai_fallback:
            return self._fetch_best_effort(
                project_name, scene, query, subject, output
            )

        # Walk pages for the best UNUSED on-topic clip. Prefer the on-topic
        # winner; if it's already taken, walk the pool; if a whole page is
        # exhausted, try the next page. ``best is None`` for a page means the
        # search returned nothing OR the slug filter rejected every candidate —
        # try the next page, then fall back to AI. ``first_on_topic`` is kept for
        # the duplicate-accept fallback (a dup beats a gap when every on-topic
        # clip is used).
        chosen: StockClip | None = None
        first_on_topic: StockClip | None = None
        for page in (1, 2):
            try:
                best, on_topic_pool = self._search_and_filter(
                    scene, query, subject, page=page
                )
            except Exception as exc:
                print(
                    f"  [scene {sid}] page {page} search failed ({exc!r})",
                    flush=True,
                )
                continue
            if best is None:
                # No on-topic clip on this page. Deliberately do NOT fall back to
                # the off-topic pool — try the next page, then the AI fallback.
                continue
            if first_on_topic is None:
                first_on_topic = best
            # Pick AND claim under one lock hold so no other worker can grab the
            # same clip in the window between choosing and registering it.
            with self._used_lock:
                cand = self._pick_unused_from_pool(best, on_topic_pool)
                if cand is not None:
                    chosen = cand
                    self._used_clip_ids.add(str(chosen.id))
                    break
            print(
                f"  [scene {sid}] all page-{page} on-topic candidates already "
                f"used; trying next page",
                flush=True,
            )

        if chosen is None:
            if first_on_topic is not None:
                # On-topic clips exist but every one is already used by another
                # scene. A duplicate beats a missing scene — accept WITH WARN.
                with self._used_lock:
                    chosen = first_on_topic
                    print(
                        f"  [scene {sid}] WARNING: all on-topic candidates "
                        f"already used across pages, accepting duplicate "
                        f"{chosen.id}",
                        flush=True,
                    )
                    self._used_clip_ids.add(str(chosen.id))
            else:
                # No page yielded an on-topic clip — hand off to the AI-image
                # fallback (this is NOT a scene failure).
                raise NoOnTopicFootage(scene_id=sid, subject=subject)

        if first_on_topic is not None and chosen.id != first_on_topic.id:
            print(
                f"  [scene {sid}] avoiding duplicate of clip "
                f"{first_on_topic.id}, using {chosen.id}",
                flush=True,
            )

        # Only now that we're committed to writing an .mp4 do we sweep a stale
        # AI-image .png for this scene id (mode-flip cleanup). Doing it here — not
        # before the search — means a scene that ends up REJECTED keeps any prior
        # fallback .png (+ its cache) for the AI provider to reuse rather than
        # regenerate.
        clean_other_mode_files(footage_dir, sid, keep_ext=".mp4")

        print(
            f"  [scene {sid}] {self._client.name} {chosen.id}  "
            f"{chosen.width}x{chosen.height}  {chosen.duration:.1f}s  -> {output}",
            flush=True,
        )
        self._client.download(chosen, str(output))
        # Sidecar written AFTER the download finishes so a partial file never
        # gets mistaken for a cache hit.
        write_cache(output, {"visual_description": query, "stock_id": chosen.id})
        return output

    def _fetch_best_effort(
        self,
        project_name: str,
        scene: dict,
        query: str,
        subject: str,
        output: Path,
    ) -> Path:
        """Degrade path used ONLY when the orchestrator has spent its AI-image
        fallback budget: take Pexels' best qualifying candidate for ``query``
        WITHOUT the on-topic slug filter, so the scene still gets footage even
        when nothing is verifiably on-topic. Prefers an unused clip; accepts a duplicate
        over a gap. Raises ``NoOnTopicFootage`` only if Pexels returns nothing at
        all (the scene then has no visual — a genuine failure)."""
        sid = scene["id"]
        footage_dir = footage_dir_for(project_name)
        candidates = self._client.search(
            query, min_duration=scene["duration"], page=1
        )
        qualifying = [
            c for c in candidates if c.duration >= scene["duration"]
        ] or candidates
        with self._used_lock:
            chosen = next(
                (c for c in qualifying if str(c.id) not in self._used_clip_ids),
                None,
            ) or pick_best(candidates, scene["duration"])
            if chosen is None:
                raise NoOnTopicFootage(scene_id=sid, subject=subject)
            self._used_clip_ids.add(str(chosen.id))
        print(
            f"  [scene {sid}] WARNING: AI-image fallback budget exhausted; "
            f"accepting best-effort stock clip {chosen.id} (relevance not "
            f"verified)",
            flush=True,
        )
        clean_other_mode_files(footage_dir, sid, keep_ext=".mp4")
        self._client.download(chosen, str(output))
        write_cache(output, {"visual_description": query, "stock_id": chosen.id})
        return output

    def _search_and_filter(
        self, scene: dict, query: str, subject: str, page: int
    ) -> tuple[StockClip | None, list[StockClip]]:
        """Search Pexels for ``query`` at ``page``, filter by duration, and keep
        only clips whose page-URL slug is on-topic for the scene's SUBJECT.

        Returns ``(best, on_topic_pool)`` where ``best`` is the first on-topic
        clip (Pexels relevance order preserved), or ``None`` when this page has
        NO on-topic clip — either the search returned nothing OR the slug filter
        rejected every candidate. The caller distinguishes those from a usable
        page by ``best is None`` and only consumes ``on_topic_pool`` (the dedup
        walk pool) when ``best`` is set."""
        candidates = self._client.search(
            query, min_duration=scene["duration"], page=page
        )
        if not candidates:
            return None, []
        qualifying = [c for c in candidates if c.duration >= scene["duration"]]
        pool = qualifying or candidates
        on_topic = filter_on_topic(pool, subject)
        # filter_on_topic returns [] when nothing on this page names the subject;
        # pick_best([]) is None, a real "nothing on-topic" signal that fires the
        # caller's NoOnTopicFootage -> AI-image fallback path.
        best = pick_best(on_topic, scene["duration"])
        return best, on_topic

    def _pick_unused_from_pool(
        self, best: StockClip, pool: list[StockClip]
    ) -> StockClip | None:
        """Caller must hold ``self._used_lock``. Returns ``best`` if unused;
        otherwise the next unused clip in pool order; otherwise None."""
        if str(best.id) not in self._used_clip_ids:
            return best
        for c in pool:
            if str(c.id) not in self._used_clip_ids:
                return c
        return None
