"""Per-scene Edit Decision List (EDL) for the render stage.

Stored at ``<projects_root>/<name>/edl.json`` with schema::

    {
      "version": 1,
      "scenes": [
        {
          "id": 0,
          "transition": "cut",        # cut | fade
          "ken_burns": false,
          "overlay_text": null,        # string or null
          "overlay_position": null     # "top" | "center" | "bottom" or null
        },
        ...
      ]
    }

V1 is intentionally minimal — just enough to express per-scene render
decisions and ship listicle text overlays as the first visible payoff. SFX,
music, custom transition timings, etc. are future-phase additions; the
``version`` field is here so readers can branch when the schema grows.

Generation is purely a function of upstream artifacts (scene_windows,
scene_plan, outline, script_config) — running ``generate_default_edl``
twice on unchanged inputs yields identical output. Assembly auto-creates
an EDL when one is absent, so existing projects rendered before this
stage existed don't need a migration.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from services.paths import PROJECTS_ROOT

EDL_SCHEMA_VERSION = 1


def _project_path(project_name: str) -> Path:
    return PROJECTS_ROOT / project_name


def _edl_path(project_name: str) -> Path:
    return _project_path(project_name) / "edl.json"


# ---------------------------------------------------------------------------
# Load / save
# ---------------------------------------------------------------------------

def load_edl(project_name: str) -> dict | None:
    """Return the saved EDL dict, or None if the file doesn't exist.

    Malformed JSON is propagated rather than silently treated as missing so a
    corrupted EDL fails loudly instead of silently rendering with defaults
    that don't reflect the user's intent (matches load_visual_config)."""
    p = _edl_path(project_name)
    if not p.exists():
        return None
    with p.open() as f:
        return json.load(f)


def save_edl(project_name: str, edl: dict) -> Path:
    """Atomic write of edl.json. Tempfile + os.replace prevents partial-read
    tearing if the renderer reads concurrently. Mirrors save_visual_config."""
    p = _edl_path(project_name)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".edl.", suffix=".tmp", dir=str(p.parent))
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(edl, f, indent=2)
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return p


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> Any | None:
    if not path.exists():
        return None
    try:
        with path.open() as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _listicle_segment_titles(segments: list) -> dict[int, str]:
    """Map body segment_id -> segment title from script_draft.json.

    Segment-id convention matches scene_plan: -1 hook, -2 conclusion,
    0..N-1 body segments in order. ``script_draft["segments"]`` lists only the
    body segments (hook + conclusion live at the top level), so index in
    that list equals segment_id."""
    return {i: (s.get("title") or "").strip() for i, s in enumerate(segments or [])}


def _is_listicle(script_config: dict | None) -> bool:
    if not script_config:
        return False
    return (script_config.get("video_type") or "").strip().lower() == "listicle"


def generate_default_edl(
    project_name: str,
    *,
    transition: str = "cut",
    ken_burns: bool = False,
) -> dict:
    """Build a per-scene EDL from the project's upstream artifacts.

    For every scene: transition + ken_burns are populated from the kwargs
    (so a render-triggered EDL respects the user's Render-tab choices).
    overlay_text starts as None for every scene; for listicle videos, the
    FIRST scene of each item segment is stamped with ``"{N}. {title}"`` at
    the top position.

    Robust to missing inputs:
      * scene_windows.json is the source of truth for scene ordering — if
        absent, raise (no point producing an empty EDL).
      * outline.json absent: log a warning and skip overlays (listicle
        videos still get a working EDL, just without text). Doesn't
        happen in practice if the pipeline ran in order.
      * script_config.json absent: assume non-listicle (no overlays).
    """
    if transition not in ("cut", "fade"):
        raise ValueError(f"transition must be 'cut' or 'fade', got {transition!r}")

    proj = _project_path(project_name)
    scene_windows = _load_json(proj / "scene_windows.json")
    if scene_windows is None:
        # Fall back to scene_plan.json's scene_intent — both have id + segment_id
        # and either is enough to build the EDL's scene list. scene_windows is
        # preferred because it's the post-timing artifact the renderer
        # actually consumes.
        plan = _load_json(proj / "scene_plan.json")
        if not plan:
            raise FileNotFoundError(
                f"Cannot generate EDL for {project_name!r}: neither "
                f"scene_windows.json nor scene_plan.json exists."
            )
        scene_windows = plan.get("scene_intent", [])

    script_draft = _load_json(proj / "script_draft.json")
    script_config = _load_json(proj / "script_config.json")

    overlay_for_segment: dict[int, str] = {}
    if _is_listicle(script_config):
        segments: list | None = None
        if script_draft is not None:
            segments = script_draft.get("segments", [])
        else:
            outline = _load_json(proj / "outline.json")
            if outline is not None:
                print(
                    f"WARNING: edl_service: script_draft.json missing for "
                    f"{project_name!r}; falling back to outline.json sections "
                    f"for overlay text."
                )
                segments = outline.get("sections", [])
            else:
                print(
                    f"WARNING: edl_service: neither script_draft.json nor "
                    f"outline.json found for {project_name!r}; generating EDL "
                    f"without overlay text."
                )

        if segments is not None:
            titles = _listicle_segment_titles(segments)
            # Item segments are body segment_ids 0..N-1 (hook=-1, conclusion=-2
            # don't get item-number overlays). 1-indexed display.
            for seg_id, title in titles.items():
                if seg_id < 0 or not title:
                    continue
                overlay_for_segment[seg_id] = f"{seg_id + 1}. {title}"

    # Track which segments we've already stamped the overlay on, so only the
    # FIRST scene of each item segment gets the text.
    stamped: set[int] = set()
    scenes: list[dict] = []
    for scene in scene_windows:
        sid = scene["id"]
        seg_id = scene.get("segment_id")

        overlay_text: str | None = None
        overlay_position: str | None = None
        if (
            seg_id is not None
            and seg_id in overlay_for_segment
            and seg_id not in stamped
        ):
            overlay_text = overlay_for_segment[seg_id]
            overlay_position = "top"
            stamped.add(seg_id)

        scenes.append({
            "id": sid,
            "transition": transition,
            "ken_burns": ken_burns,
            "overlay_text": overlay_text,
            "overlay_position": overlay_position,
        })

    return {
        "version": EDL_SCHEMA_VERSION,
        "scenes": scenes,
    }
