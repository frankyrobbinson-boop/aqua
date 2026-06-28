"""Pexels stock-video provider conforming to the VisualProvider interface.

Wraps the existing Pexels REST client + rerank logic from ``stock_pexels`` /
``stock_provider`` / ``visual_rerank``. Behavior matches the pre-refactor
``visual_service.fetch_scene_footage`` per-scene loop one-for-one:

  - Search Pexels for the scene's visual_description
  - Filter to clips that meet the scene's required duration
  - Vision-rerank candidates via Claude Haiku
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
    VisualProvider,
    cache_path_for,
    clean_other_mode_files,
    footage_dir_for,
    is_cache_valid,
    write_cache,
)
from services.visual_rerank import rerank_candidates

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
    """Internal REST client. Kept conforming to ``StockProvider`` so the legacy
    ``stock_pexels.PexelsProvider`` alias (re-exported below) and any external
    callers still work during the transition."""

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


# Legacy alias — pipeline.py and run_video_only.py still import this. Removing
# the symbol would break those entrypoints; the orchestrator in visual_service
# now wraps it through PexelsVisualProvider.
PexelsProvider = _PexelsClient


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

    def fetch_for_scene(self, project_name: str, scene: dict) -> Path:
        sid = scene["id"]
        footage_dir = footage_dir_for(project_name)
        output = footage_dir / f"scene_{sid:03d}.mp4"
        query = (scene.get("visual_description") or "").strip()

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

        # Clean up any stale AI-image .png for this scene id so a mode-flip
        # (ai_image -> stock_video) doesn't leave both a .png and .mp4.
        clean_other_mode_files(footage_dir, sid, keep_ext=".mp4")

        best, rerank_pool = self._search_and_rank(scene, query, project_name, page=1)

        # De-dup walk: prefer the rerank winner; if it's taken, try the next
        # unused clip in rank order across the full pool. If everything in
        # page-1 is taken, fetch page 2 and rerank again. Only then accept a
        # duplicate WITH WARN — a duplicated clip beats a missing scene.
        with self._used_lock:
            chosen = self._pick_unused_from_pool(best, rerank_pool)
            if chosen is None:
                print(
                    f"  [scene {sid}] all page-1 candidates already used; "
                    f"fetching page 2",
                    flush=True,
                )
                # Release lock for the network call.
                pass
        if chosen is None:
            try:
                best2, rerank_pool2 = self._search_and_rank(
                    scene, query, project_name, page=2
                )
            except Exception as exc:
                print(
                    f"  [scene {sid}] page 2 search failed ({exc!r}); "
                    f"accepting duplicate from page 1",
                    flush=True,
                )
                best2, rerank_pool2 = best, []
            with self._used_lock:
                chosen = self._pick_unused_from_pool(best2, rerank_pool2)
                if chosen is None:
                    print(
                        f"  [scene {sid}] WARNING: all candidates across two "
                        f"pages already used, accepting duplicate {best.id}",
                        flush=True,
                    )
                    chosen = best
                self._used_clip_ids.add(str(chosen.id))
        else:
            with self._used_lock:
                # Re-check under lock — another worker may have grabbed it
                # while we held no lock. If so, walk again.
                if str(chosen.id) in self._used_clip_ids:
                    walked = self._pick_unused_from_pool(best, rerank_pool)
                    if walked is not None:
                        chosen = walked
                    else:
                        print(
                            f"  [scene {sid}] WARNING: pool exhausted "
                            f"under contention, accepting duplicate {chosen.id}",
                            flush=True,
                        )
                self._used_clip_ids.add(str(chosen.id))

        if chosen.id != best.id:
            print(
                f"  [scene {sid}] avoiding duplicate of clip {best.id}, "
                f"using {chosen.id}",
                flush=True,
            )

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

    def _search_and_rank(
        self, scene: dict, query: str, project_name: str, page: int
    ) -> tuple[StockClip, list[StockClip]]:
        """Search Pexels for ``query`` at ``page``, filter by duration, and
        rerank. Returns (best, rerank_pool). Raises if the page yields no
        usable candidates (caller decides whether to fall back to a duplicate).
        """
        sid = scene["id"]
        candidates = self._client.search(
            query, min_duration=scene["duration"], page=page
        )
        if not candidates:
            raise RuntimeError(
                f"No {self._client.name} footage found for scene {sid} "
                f"(query={query!r}, page={page})"
            )
        qualifying = [c for c in candidates if c.duration >= scene["duration"]]
        rerank_pool = qualifying or candidates
        best = rerank_candidates(
            narration=scene.get("narration", ""),
            visual_description=query,
            candidates=rerank_pool,
            project_name=project_name,
        )
        if best is None:
            best = pick_best(candidates, scene["duration"])
        if best is None:
            raise RuntimeError(
                f"No usable candidate for scene {sid} "
                f"(query={query!r}, page={page})"
            )
        return best, rerank_pool

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
