"""Visuals orchestrator: dispatch each scene to its configured provider.

Reads ``scene_plan.json`` + ``visual_config.json`` (or the default), looks up
each scene's segment, resolves the provider via ``visual_provider_registry``,
and calls ``fetch_for_scene``. Caching, dedup, and provider-specific error
handling live in the providers themselves; this module just routes.

Behavioral preservation: if ``visual_config.json`` is absent, every segment
falls back to ``stock_video`` / ``pexels`` (see ``visual_config_service``), so
projects predating this refactor run exactly as before.

Public surface:
    fetch_all_scene_footage(project_name) -> ({scene_id: Path}, {scene_id: str})
        Sole orchestrator entrypoint. Returns a (paths, errors) tuple so
        callers can decide whether the error rate is tolerable before
        aborting the run; an individual scene failure no longer cancels
        the whole batch.
"""

from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from services.paths import PROJECTS_ROOT
from services.visual_config_service import (
    resolve_scene_provider_id,
    resolve_visual_config,
)
from services.visual_provider import VisualProvider
from services.visual_provider_registry import get_provider

# Bounded concurrency for the orchestrator's worker pool. Same value as the
# old per-Pexels-call pool; AI image providers self-rate-cap with their own
# semaphores so this cap is mostly about Pexels HTTP politeness + log
# readability.
_MAX_WORKERS = 8


# ---------------------------------------------------------------------------
# Public orchestrator
# ---------------------------------------------------------------------------

def fetch_all_scene_footage(
    project_name: str,
) -> tuple[dict[int, Path], dict[int, str]]:
    """Fetch footage for every scene, dispatching per-segment to the right
    provider. Returns ``(paths, errors)`` where:

      - ``paths`` is ``{scene_id: Path}`` for every scene that produced output
      - ``errors`` is ``{scene_id: "<exception repr>"}`` for every scene that
        failed

    Does NOT raise on per-scene failures; the caller decides whether the error
    rate is tolerable (see ``run_visuals.py`` which aborts above a threshold).
    Still raises on whole-batch failures: missing scene_windows.json,
    misconfigured visual_config, etc.
    """
    # Read scene_windows.json (not scene_plan.json) because:
    #   1. Pexels provider needs `duration` per scene — only scene_windows has it
    #      (it's computed from start_time/end_time during the scene-timing stage).
    #   2. scene_windows is the canonical post-drop-phantom list: scene_plan can
    #      contain trailing hallucinated CTA scenes that scene_timing already
    #      dropped; fetching footage for those is wasted spend + wasted disk.
    # scene_windows entries carry every original scene_plan field PLUS the
    # timing block, so this is strictly a superset read.
    scene_windows_path = PROJECTS_ROOT / project_name / "scene_windows.json"
    if not scene_windows_path.exists():
        raise FileNotFoundError(
            f"scene_windows.json not found for {project_name!r} — "
            f"run the scene-timing stage first (it runs automatically as "
            f"step [2/4] inside run_visuals.py)"
        )
    import json
    with scene_windows_path.open() as f:
        scenes: list[dict] = json.load(f)
    if not scenes:
        raise RuntimeError(f"scene_windows for {project_name!r} has no scenes")

    config = resolve_visual_config(project_name)
    config_by_segment: dict[int, dict] = {
        int(s["segment_id"]): s for s in config.get("segments", [])
    }

    # Warn (don't fail) on scene_count mismatches between visual_config and
    # the live scene_plan. Phase 1 always defers to scene_plan; a future
    # re-bucketing stage will honor the override.
    live_counts: dict[int, int] = defaultdict(int)
    for s in scenes:
        live_counts[int(s["segment_id"])] += 1
    for seg_id, entry in config_by_segment.items():
        configured = entry.get("scene_count")
        actual = live_counts.get(seg_id, 0)
        if configured is not None and configured != actual:
            print(
                f"  WARNING: segment {seg_id} configured for {configured} "
                f"scene(s) but scene_plan has {actual}. Honoring scene_plan "
                f"(Phase 1 does not re-bucket).",
                flush=True,
            )

    # Pair each scene with the provider instance it'll use. Doing the lookup
    # up-front means a misconfigured segment fails before any work starts.
    scene_provider: list[tuple[dict, VisualProvider, str]] = []
    for scene in scenes:
        seg_id = int(scene["segment_id"])
        entry = config_by_segment.get(seg_id)
        if entry is None:
            raise RuntimeError(
                f"Scene {scene['id']} in segment {seg_id} has no entry in "
                f"visual_config. Resolve config first or delete the project's "
                f"visual_config.json to fall back to defaults."
            )
        # Route per scene: non-mixed segments resolve to the segment provider
        # (byte-for-byte unchanged); mixed segments resolve each scene to the
        # right default provider for its effective per-scene mode.
        provider_id = resolve_scene_provider_id(config, scene)
        provider = get_provider(provider_id)
        scene_provider.append((scene, provider, provider_id))

    print(
        f"  Dispatching {len(scene_provider)} scene(s) across providers "
        f"(max {_MAX_WORKERS} workers)...",
        flush=True,
    )

    paths: dict[int, Path] = {}
    errors: dict[int, str] = {}

    def _one(scene: dict, provider: VisualProvider, pid: str) -> tuple[int, Path]:
        sid = scene["id"]
        out = provider.fetch_for_scene(project_name, scene)
        return sid, Path(out)

    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
        futures = {
            pool.submit(_one, scene, provider, pid): scene["id"]
            for scene, provider, pid in scene_provider
        }
        # Collect per-scene errors into the dict instead of aborting on first.
        # The caller (run_visuals) decides whether the error rate is tolerable.
        for fut in as_completed(futures):
            sid = futures[fut]
            try:
                got_sid, path = fut.result()
                paths[got_sid] = path
            except BaseException as exc:
                errors[sid] = repr(exc)
                print(f"  ERROR scene {sid}: {exc!r}", flush=True)

    return paths, errors
