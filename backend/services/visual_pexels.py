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
import urllib.parse
from pathlib import Path
from typing import List

import requests
from dotenv import load_dotenv

from services.stock_provider import StockClip, StockProvider, pick_best
from services.visual_provider import (
    VisualProvider,
    cache_path_for,
    footage_dir_for,
    is_cache_valid,
    write_cache,
)
from services.visual_rerank import rerank_candidates

load_dotenv()

_SEARCH_URL = "https://api.pexels.com/videos/search"
_TARGET_W, _TARGET_H = 1920, 1080


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
    ) -> List[StockClip]:
        params = {
            "query": query,
            "per_page": max_results,
            "orientation": orientation,
            "size": "medium",  # >= HD; "large" forces 4K+ and starves results
        }
        url = f"{_SEARCH_URL}?{urllib.parse.urlencode(params)}"
        response = requests.get(url, headers=self._headers, timeout=20)
        response.raise_for_status()
        data = response.json()

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
        with requests.get(clip.download_url, stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(output_path, "wb") as f:
                shutil.copyfileobj(r.raw, f)
        return output_path


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

        candidates = self._client.search(query, min_duration=scene["duration"])
        if not candidates:
            raise RuntimeError(
                f"No {self._client.name} footage found for scene {sid} (query={query!r})"
            )

        # Filter to candidates that meet duration first, then LLM-rerank by
        # visual fit. Falls through to pick_best heuristics if rerank has nothing
        # to pick from (single candidate, missing previews, or API failure).
        qualifying = [c for c in candidates if c.duration >= scene["duration"]]
        rerank_pool = qualifying or candidates
        best = rerank_candidates(
            narration=scene.get("narration", ""),
            visual_description=query,
            candidates=rerank_pool,
        )
        if best is None:
            best = pick_best(candidates, scene["duration"])
        if best is None:
            raise RuntimeError(
                f"No usable candidate for scene {sid} (query={query!r})"
            )

        # Avoid duplicate clip IDs across scenes. Critical section is tiny
        # (set ops over <=10 candidates); slow I/O — search, rerank, download —
        # runs OUTSIDE the lock. Fallback "accept duplicate if every candidate
        # is already used" prevents deadlock when the pool is exhausted.
        with self._used_lock:
            if str(best.id) in self._used_clip_ids:
                alt = next(
                    (c for c in rerank_pool if str(c.id) not in self._used_clip_ids),
                    None,
                )
                if alt is not None:
                    print(
                        f"  [scene {sid}] avoiding duplicate of clip "
                        f"{best.id}, using {alt.id}",
                        flush=True,
                    )
                    best = alt
                else:
                    print(
                        f"  [scene {sid}] WARNING: all candidates already "
                        f"used, accepting duplicate {best.id}",
                        flush=True,
                    )
            self._used_clip_ids.add(str(best.id))

        print(
            f"  [scene {sid}] {self._client.name} {best.id}  "
            f"{best.width}x{best.height}  {best.duration:.1f}s  -> {output}",
            flush=True,
        )
        self._client.download(best, str(output))
        # Sidecar written AFTER the download finishes so a partial file never
        # gets mistaken for a cache hit.
        write_cache(output, {"visual_description": query, "stock_id": best.id})
        return output
