"""Fetch stock-footage clips for each scene via a StockProvider.

Each scene's visual_description (from scene_plan) is used as the search query.
Downloaded raw clips land in ../projects/{project}/footage/scene_NNN.mp4.
Assembly trims + scales them to the final video format.
"""

import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from services.stock_provider import StockProvider, pick_best
from services.visual_rerank import rerank_candidates

# Bounded concurrency. Pexels free tier is 200 req/hr — at 8 workers we'll burn
# at most ~16 requests/sec, well within budget. Anthropic Haiku has no hard
# concurrency cap at our usage level.
_MAX_WORKERS = 8


def _footage_cache_path(output_path: str) -> str:
    return output_path + ".cache.json"


def _footage_cache_hit(scene: dict, output_path: str) -> bool:
    """True iff a previously-downloaded clip is still valid for this scene.

    Keyed by the scene's visual_description: editing the scene's query in the
    UI must invalidate the cache (otherwise a stale clip for the OLD query
    would silently re-use). File existence + size > 0 isn't enough on its own
    because scene IDs are stable across re-plans."""
    cache_path = _footage_cache_path(output_path)
    if not (os.path.exists(output_path) and os.path.exists(cache_path)):
        return False
    if os.path.getsize(output_path) == 0:
        return False
    try:
        with open(cache_path) as f:
            cache = json.load(f)
    except (OSError, json.JSONDecodeError):
        return False
    return cache.get("visual_description") == (scene.get("visual_description") or "").strip()


def fetch_scene_footage(
    project_name: str,
    scene_windows: list,
    provider: StockProvider,
) -> dict:
    """Search + download one stock clip per scene. Returns {scene_id: raw_clip_path}.

    Scenes are processed in parallel (each scene is independent — different
    Pexels search, different rerank call, different download). Cached clips
    are detected first so we never pay for them. Failures abort the run via
    the first exception that surfaces from as_completed."""
    footage_dir = f"../projects/{project_name}/footage"
    os.makedirs(footage_dir, exist_ok=True)

    # Track every stock clip ID we've committed to in this run. Both the cached-
    # scene pass and the parallel-fetch pass write into it, and the per-scene
    # worker consults it under a lock to avoid two scenes picking the same clip.
    used_clip_ids: set[str] = set()
    used_lock = threading.Lock()

    # First pass: identify what's cached vs what needs work. Done synchronously
    # so cache hits stream as a tight block of log lines before the parallel
    # downloads start interleaving.
    paths: dict[int, str] = {}
    todo: list[dict] = []
    for scene in scene_windows:
        sid = scene["id"]
        path = os.path.join(footage_dir, f"scene_{sid:03d}.mp4")
        if _footage_cache_hit(scene, path):
            print(f"  [scene {sid}] cached → {path}", flush=True)
            paths[sid] = path
            # Pre-populate the used set so fresh fetches in this run respect
            # what's already on disk. Legacy sidecars without stock_id are
            # silently skipped — the only cost is a possible duplicate against
            # them, which the next run will resolve once the new sidecar is
            # written with stock_id.
            try:
                with open(_footage_cache_path(path)) as cf:
                    cached = json.load(cf)
                cid = cached.get("stock_id")
                if cid is not None:
                    used_clip_ids.add(str(cid))
            except (OSError, json.JSONDecodeError):
                pass
            continue
        todo.append(scene)

    if not todo:
        return paths

    print(
        f"  Fetching {len(todo)} scenes in parallel (max {_MAX_WORKERS} workers)...",
        flush=True,
    )

    def _fetch_one(scene: dict) -> tuple[int, str]:
        sid = scene["id"]
        path = os.path.join(footage_dir, f"scene_{sid:03d}.mp4")
        query = (scene.get("visual_description") or "").strip()
        if not query:
            raise ValueError(f"Scene {sid} has no visual_description to search with")

        candidates = provider.search(query, min_duration=scene["duration"])
        if not candidates:
            raise RuntimeError(
                f"No {provider.name} footage found for scene {sid} (query={query!r})"
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

        # Avoid duplicate clip IDs across scenes. The critical section is
        # tiny (set ops over <=10 candidates); the slow I/O — search,
        # rerank, download — runs OUTSIDE the lock, so parallelism is
        # preserved. Fallback "accept duplicate if every candidate is
        # already used" prevents deadlock when the pool is exhausted.
        with used_lock:
            if str(best.id) in used_clip_ids:
                alt = next(
                    (c for c in rerank_pool if str(c.id) not in used_clip_ids),
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
            used_clip_ids.add(str(best.id))

        print(
            f"  [scene {sid}] {provider.name} {best.id}  "
            f"{best.width}x{best.height}  {best.duration:.1f}s  → {path}",
            flush=True,
        )
        provider.download(best, path)
        # Sidecar written AFTER the download finishes so a partial file never
        # gets mistaken for a cache hit. Keyed by visual_description so re-plans
        # that rewrite the query invalidate this clip.
        with open(_footage_cache_path(path), "w") as cf:
            json.dump({"visual_description": query, "stock_id": best.id}, cf)
        return sid, path

    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
        futures = {pool.submit(_fetch_one, scene): scene["id"] for scene in todo}
        first_exc: Optional[BaseException] = None
        for fut in as_completed(futures):
            try:
                sid, path = fut.result()
                paths[sid] = path
            except BaseException as exc:
                # Capture the first exception but let other in-flight downloads
                # finish writing what they've already paid for. We re-raise after.
                if first_exc is None:
                    first_exc = exc
                    print(
                        f"  ERROR scene {futures[fut]}: {exc!r} — waiting for "
                        f"in-flight downloads to settle before aborting...",
                        flush=True,
                    )
        if first_exc is not None:
            raise first_exc

    return paths
