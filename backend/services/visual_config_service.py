"""Per-project visual configuration: which provider handles which segment.

Stored at ``../projects/<name>/visual_config.json`` with schema:

    {
      "segments": [
        {"segment_id": -1, "scene_count": 5, "mode": "ai_image", "provider": "nano_banana"},
        {"segment_id": 0,  "scene_count": 9, "mode": "ai_image", "provider": "nano_banana"},
        {"segment_id": 1,  "scene_count": 7, "mode": "stock_video", "provider": "pexels"},
        ...
        {"segment_id": -2, "scene_count": 4, "mode": "stock_video", "provider": "pexels"}
      ]
    }

Segment IDs match ``scene_plan`` conventions: -1 = hook, 0..N = body segments,
-2 = conclusion. ``scene_count`` is informational in Phase 1 — the actual scene
count comes from scene_plan; a mismatch logs a warning. A future phase will
re-bucket scene_plan to honor an override.

If the file is absent, ``resolve_visual_config`` returns a default that pins
every segment to ``stock_video`` / ``pexels``, which is today's behavior. Run
graphs that never write this file therefore continue to work unchanged.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections import OrderedDict
from pathlib import Path

from services.visual_provider_registry import (
    default_mode,
    default_provider_for_mode,
    default_provider_id,
)

_PROJECTS_ROOT = Path("../projects")


def _config_path(project_name: str) -> Path:
    return _PROJECTS_ROOT / project_name / "visual_config.json"


def _scene_plan_path(project_name: str) -> Path:
    return _PROJECTS_ROOT / project_name / "scene_plan.json"


# ---------------------------------------------------------------------------
# Load / save
# ---------------------------------------------------------------------------

def load_visual_config(project_name: str) -> dict | None:
    """Return the saved config dict, or None if the file doesn't exist.

    Malformed JSON is propagated rather than silently treated as missing —
    a corrupted config should fail loudly so the user fixes it instead of
    quietly running with defaults that may bill the wrong provider.
    """
    p = _config_path(project_name)
    if not p.exists():
        return None
    with p.open() as f:
        return json.load(f)


def save_visual_config(project_name: str, config: dict) -> None:
    """Atomic write of visual_config.json. Tempfile + os.replace prevents a
    partial-read race if the UI's PUT lands concurrently with a pipeline run
    that reads it. Mirrors api/routes/pipeline._patch_script_config."""
    p = _config_path(project_name)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        prefix=".visual_config.", suffix=".tmp", dir=str(p.parent)
    )
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(config, f, indent=2)
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Defaults derived from scene_plan
# ---------------------------------------------------------------------------

def _load_scene_plan(project_name: str) -> dict | None:
    p = _scene_plan_path(project_name)
    if not p.exists():
        return None
    with p.open() as f:
        return json.load(f)


def _segment_scene_counts(scene_plan: dict) -> "OrderedDict[int, int]":
    """{segment_id: count} preserving first-seen order from scene_plan. Order
    matters because the UI renders segments top-to-bottom matching narrative
    order (hook=-1, body 0..N, conclusion=-2)."""
    counts: OrderedDict[int, int] = OrderedDict()
    for scene in scene_plan.get("scene_intent", []):
        seg = int(scene["segment_id"])
        counts[seg] = counts.get(seg, 0) + 1
    return counts


def default_visual_config(project_name: str) -> dict:
    """Build a default config from scene_plan. Defaults preserve today's
    behavior: every segment uses ``stock_video`` / ``pexels``.

    If scene_plan.json doesn't exist yet (e.g. user is editing config before
    the visuals stage has produced one), returns an empty segments list rather
    than raising — the UI can render with no rows and the user re-opens after
    the script stage."""
    default_md = default_mode()
    try:
        default_pv = default_provider_for_mode(default_md)
    except ValueError:
        default_pv = default_provider_id()

    plan = _load_scene_plan(project_name)
    if not plan:
        return {"segments": []}

    counts = _segment_scene_counts(plan)
    return {
        "segments": [
            {
                "segment_id": seg_id,
                "scene_count": count,
                "mode": default_md,
                "provider": default_pv,
            }
            for seg_id, count in counts.items()
        ]
    }


def resolve_visual_config(project_name: str) -> dict:
    """Return the effective config: saved if present, otherwise default.

    Merges saved-segment overrides ON TOP of the scene_plan-derived skeleton
    so a saved config that's missing a freshly-added segment (e.g. user added
    a body segment after editing visuals) still covers every segment in
    scene_plan. Saved segments win on mode/provider; scene_count always
    reflects the live scene_plan.
    """
    plan = _load_scene_plan(project_name)
    saved = load_visual_config(project_name)
    if not plan:
        # No plan yet: trust the saved file if it exists, otherwise empty.
        return saved or {"segments": []}

    skeleton = default_visual_config(project_name)
    if not saved:
        return skeleton

    saved_by_id: dict[int, dict] = {
        int(s["segment_id"]): s for s in saved.get("segments", [])
    }
    merged: list[dict] = []
    for entry in skeleton["segments"]:
        seg_id = entry["segment_id"]
        override = saved_by_id.get(seg_id)
        if override:
            merged.append({
                "segment_id": seg_id,
                "scene_count": entry["scene_count"],  # always from live plan
                "mode": override.get("mode", entry["mode"]),
                "provider": override.get("provider", entry["provider"]),
            })
        else:
            merged.append(entry)
    return {"segments": merged}
