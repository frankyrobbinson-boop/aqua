"""Per-project visual configuration: which provider handles which segment.

Stored at ``<projects_root>/<name>/visual_config.json`` with schema:

    {
      "segments": [
        {"segment_id": -1, "scene_count": 5, "mode": "ai_image", "provider": "nano_banana"},
        {"segment_id": 0,  "scene_count": 9, "mode": "ai_image", "provider": "nano_banana"},
        {"segment_id": 1,  "scene_count": 7, "mode": "stock_video", "provider": "pexels"},
        ...
        {"segment_id": -2, "scene_count": 4, "mode": "stock_video", "provider": "pexels"}
      ]
    }

Optional top-level ``"default_mode"`` / ``"default_provider"`` keys (written by
the full-pipeline start flow) override the registry defaults for every segment
that has no per-segment saved entry; per-segment saved entries still win.

Segment IDs match ``scene_plan`` conventions: -1 = hook, 0..N = body segments,
-2 = conclusion. ``scene_count`` is informational in Phase 1 — the actual scene
count comes from scene_plan; a mismatch logs a warning. A future phase will
re-bucket scene_plan to honor an override.

If the file is absent, ``resolve_visual_config`` returns a default that pins
every segment to the system default mode/provider (``ai_image`` / ``seedream``).
Run graphs that never write this file therefore use the AI-image default.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections import OrderedDict
from pathlib import Path

from services.paths import PROJECTS_ROOT
from services.visual_provider_registry import (
    default_mode,
    default_provider_for_mode,
    default_provider_id,
    list_providers,
)


def _config_path(project_name: str) -> Path:
    return PROJECTS_ROOT / project_name / "visual_config.json"


def _scene_plan_path(project_name: str) -> Path:
    return PROJECTS_ROOT / project_name / "scene_plan.json"


def _script_draft_path(project_name: str) -> Path:
    return PROJECTS_ROOT / project_name / "script_draft.json"


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


def _load_script_draft(project_name: str) -> dict | None:
    p = _script_draft_path(project_name)
    if not p.exists():
        return None
    with p.open() as f:
        return json.load(f)


def _script_segment_skeleton(script: dict) -> list[dict]:
    """Build the ordered segment skeleton from a script draft, before any
    scene_plan exists. Uses the scene_plan id convention: -1 = hook (always
    present), 0..N-1 = body segments (one per script["segments"], in order),
    -2 = conclusion (always present). ``scene_count`` is None pre-plan; the
    actual per-segment scene count is only known once scenes are generated."""
    default_md = default_mode()
    try:
        default_pv = default_provider_for_mode(default_md)
    except ValueError:
        default_pv = default_provider_id()

    def _entry(seg_id: int) -> dict:
        return {
            "segment_id": seg_id,
            "scene_count": None,
            "mode": default_md,
            "provider": default_pv,
        }

    segments: list[dict] = [_entry(-1)]
    body = script.get("segments") or []
    for i in range(len(body)):
        segments.append(_entry(i))
    segments.append(_entry(-2))
    return segments


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
    """Build a default config from scene_plan. Defaults follow the system
    default mode/provider (``ai_image`` / ``seedream``); every segment uses it
    unless a saved config overrides.

    If scene_plan.json doesn't exist yet, fall back to the script draft so the
    UI can show and set per-segment modes before the visuals stage runs: the
    segment skeleton (hook, one row per body segment, conclusion) is derived
    from script_draft.json with ``scene_count`` None until scenes are planned.
    If neither scene_plan nor script_draft exists, returns an empty segments
    list rather than raising — the UI renders with no rows."""
    default_md = default_mode()
    try:
        default_pv = default_provider_for_mode(default_md)
    except ValueError:
        default_pv = default_provider_id()

    plan = _load_scene_plan(project_name)
    if not plan:
        script = _load_script_draft(project_name)
        if script:
            return {"segments": _script_segment_skeleton(script)}
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


def _saved_defaults(saved: dict | None) -> tuple[str, str] | None:
    """Validated (mode, provider) pair from the saved config's top-level
    ``default_mode`` / ``default_provider`` keys, or None to use the registry
    defaults. Defensive by design: an unknown provider id (registry edited
    since the config was written) falls back to None rather than raising, and
    a saved mode that disagrees with the provider's registry mode is corrected
    to the registry's — a stale saved default must never abort or misroute a
    run."""
    if not saved:
        return None
    provider_id = saved.get("default_provider")
    if not provider_id:
        return None
    entry = next((p for p in list_providers() if p["id"] == provider_id), None)
    if entry is None:
        return None
    return entry["mode"], entry["id"]


def resolve_visual_config(project_name: str) -> dict:
    """Return the effective config: saved if present, otherwise default.

    Merges saved-segment overrides ON TOP of the scene_plan-derived skeleton
    so a saved config that's missing a freshly-added segment (e.g. user added
    a body segment after editing visuals) still covers every segment in
    scene_plan. Saved segments win on mode/provider; scene_count always
    reflects the live scene_plan. Skeleton entries with no saved override use
    the saved top-level defaults (``default_mode``/``default_provider``) when
    present, else the registry defaults.
    """
    plan = _load_scene_plan(project_name)
    saved = load_visual_config(project_name)
    defaults = _saved_defaults(saved)
    # Per-scene overrides (for "mixed" segments) live at the top level and are
    # passed through untouched. Default {} so callers can index it safely.
    scene_overrides: dict = (saved.get("scene_overrides") if saved else None) or {}
    if not plan:
        # No plan yet: derive the segment skeleton from the script draft (empty
        # if there's no script either), then merge any saved mode/provider
        # choices on top so the user's pre-plan selections persist and carry
        # over to matching segment_ids once scenes are generated.
        skeleton = default_visual_config(project_name)
        if not saved:
            return {
                "segments": skeleton["segments"],
                "scene_overrides": scene_overrides,
            }
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
                    "scene_count": entry["scene_count"],  # None pre-plan
                    "mode": override.get("mode", entry["mode"]),
                    "provider": override.get("provider", entry["provider"]),
                })
            elif defaults:
                merged.append({**entry, "mode": defaults[0], "provider": defaults[1]})
            else:
                merged.append(entry)
        return {"segments": merged, "scene_overrides": scene_overrides}

    skeleton = default_visual_config(project_name)
    if not saved:
        return {"segments": skeleton["segments"], "scene_overrides": {}}

    saved_by_id: dict[int, dict] = {
        int(s["segment_id"]): s for s in saved.get("segments", [])
    }
    merged: list[dict] = []
    for entry in skeleton["segments"]:
        seg_id = entry["segment_id"]
        override = saved_by_id.get(seg_id)
        if override:
            # When the saved segment is "mixed" we keep mode "mixed" and pass
            # provider through as-is (it's dormant — routing is per-scene).
            merged.append({
                "segment_id": seg_id,
                "scene_count": entry["scene_count"],  # always from live plan
                "mode": override.get("mode", entry["mode"]),
                "provider": override.get("provider", entry["provider"]),
            })
        elif defaults:
            merged.append({**entry, "mode": defaults[0], "provider": defaults[1]})
        else:
            merged.append(entry)
    return {"segments": merged, "scene_overrides": scene_overrides}


def resolve_scene_provider_id(config: dict, scene: dict) -> str:
    """Return the provider id that should handle a single scene.

    For a segment whose mode is anything other than ``"mixed"``, every scene
    uses the segment's configured provider. For a ``"mixed"`` segment, the
    effective per-scene mode is resolved as:

        scene_overrides[str(scene_id)] -> scene["visual_mode"] -> "stock_video"

    and mapped to that mode's default provider. GUARD: ``default_provider_for_mode``
    is never called with ``"mixed"`` — any invalid/missing tag falls back to
    ``"stock_video"`` so a bad scene-plan tag can never error the run.
    """
    seg_id = int(scene["segment_id"])
    entry = next(
        (s for s in config.get("segments", []) if int(s["segment_id"]) == seg_id),
        None,
    )
    if entry is None:
        # Caller normally guards this; fall back to the global default rather
        # than raising so a single orphaned scene can't abort the batch.
        return default_provider_for_mode(default_mode())
    if entry.get("mode") != "mixed":
        return entry["provider"]

    overrides = config.get("scene_overrides") or {}
    effective = overrides.get(str(scene["id"])) or scene.get("visual_mode")
    if effective not in ("stock_video", "ai_image"):
        effective = "stock_video"
    return default_provider_for_mode(effective)
