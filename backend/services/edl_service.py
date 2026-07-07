"""Per-scene Edit Decision List (EDL) for the render stage.

Stored at ``<projects_root>/<name>/edl.json`` with schema::

    {
      "version": 2,
      "scenes": [
        {
          "id": 0,
          "transition": "cut",        # cut | fade
          "ken_burns": false,
          "overlays": [                # zero or more on-screen text overlays
            {
              "kind": "header",       # header | callout | counter
              "text": "1. Hot nights",
              "position": "top",      # top | top_right | upper_third | center | bottom
              "animation": "slide_up",# slide_up | pop | fade | none
              "start_offset": 0.0,    # seconds into the scene the overlay begins
              "duration": null         # seconds visible, or null = whole scene
            },
            ...
          ]
        },
        ...
      ]
    }

V2 replaces V1's single flat ``overlay_text`` / ``overlay_position`` with an
``overlays`` list so a scene can carry several composited overlays at once —
a listicle item's first scene shows a ``header`` (item title) + a ``counter``
(``n / total``), and any scene with on_screen_text shows a ``callout``. Each
overlay's position + animation are baked in at generation time from the
channel's editing style (``resolve_channel_editing``); the per-kind *look*
(fontsize / box / animation timings) is resolved again at render time from the
same style. SFX, music, custom transition timings, etc. remain future-phase.

Generation is purely a function of upstream artifacts (scene_windows,
scene_plan, outline, script_config, channel editing style) — running
``generate_default_edl`` twice on unchanged inputs yields identical output.
Assembly regenerates an EDL when one is absent OR at a stale schema version
(there is no manual EDL editor, so a deterministic regen reproduces all prior
data while upgrading the shape), so pre-V2 projects migrate transparently.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from services.channel_registry import resolve_channel_editing
from services.paths import PROJECTS_ROOT

EDL_SCHEMA_VERSION = 2


def is_current_version(edl: dict | None) -> bool:
    """True iff ``edl`` is a dict at the current schema version. Readers
    (assembly_service, run_render) use this to decide whether to regenerate:
    there is no manual EDL editor, so a version mismatch is always safe to
    regenerate deterministically from upstream artifacts."""
    return bool(edl) and edl.get("version") == EDL_SCHEMA_VERSION


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


# Video types whose sections are a numbered item list — each item's first scene
# gets a "{N}. {title}" overlay stamped on it. This set is render-time overlay
# classification only; it does NOT affect prompt generation / video_type_registry,
# which no longer accepts "listicle" for generation. "listicle" is retained here for
# backward-compat so pre-migration projects still render numbered-item headers +
# counters when re-rendered.
_NUMBERED_LIST_TYPES = {"mistakes", "discovery_list", "listicle"}


def _is_listicle(script_config: dict | None) -> bool:
    if not script_config:
        return False
    return (script_config.get("video_type") or "").strip().lower() in _NUMBERED_LIST_TYPES


def generate_default_edl(
    project_name: str,
    *,
    transition: str = "cut",
    ken_burns: bool = False,
) -> dict:
    """Build a per-scene EDL (v2 overlays list) from the project's upstream
    artifacts.

    For every scene: transition + ken_burns are populated from the kwargs
    (so a render-triggered EDL respects the user's Render-tab choices). Each
    scene's ``overlays`` list is built from the channel's editing style
    (``resolve_channel_editing``, keyed off script_config's channel):

      * header  — the FIRST scene of each listicle item segment, ``"{N}. {title}"``
                  (listicle videos only, when ``header.enabled``).
      * counter — every body-item scene, ``"{n} / {total}"`` (listicle videos
                  only, when ``counter.enabled``).
      * callout — any scene whose ``on_screen_text`` is non-empty (all video
                  types, when ``callout.enabled``), UNLESS that scene already
                  carries a header (the header labels the item on its intro
                  scene and the on_screen_text there typically restates it, so
                  a callout would double-label — later item scenes keep theirs).

    Robust to missing inputs:
      * scene_windows.json is the source of truth for scene ordering — if
        absent, raise (no point producing an empty EDL).
      * outline.json absent: log a warning and skip header/counter overlays
        (listicle videos still get a working EDL, just without item text).
        Doesn't happen in practice if the pipeline ran in order.
      * script_config.json absent: assume non-listicle (callouts only) and
        resolve the default channel's editing style.
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

    # Per-channel on-screen editing style (header/callout/counter look +
    # policy). channel_id comes from script_config; None → default channel.
    # This is the seam where per-channel styles will source once presets carry
    # an ``editing`` block — none do yet, so every channel gets the defaults.
    channel_id = (script_config or {}).get("channel")
    style = resolve_channel_editing(channel_id)
    header_style = style["header"]
    callout_style = style["callout"]
    counter_style = style["counter"]

    listicle = _is_listicle(script_config)

    # Header text per body-item segment; the FIRST scene of each item segment
    # gets a "{N}. {title}" header. Listicle-only, and only when headers are
    # enabled. total_items feeds the counter's "{n} / {total}" text and is the
    # same source used for the titles (len of the segment list).
    overlay_for_segment: dict[int, str] = {}
    total_items = 0
    if listicle:
        segments: list | None = None
        if script_draft is not None:
            segments = script_draft.get("segments", [])
        else:
            outline = _load_json(proj / "outline.json")
            if outline is not None:
                print(
                    f"WARNING: edl_service: script_draft.json missing for "
                    f"{project_name!r}; falling back to outline.json sections "
                    f"for header/counter text."
                )
                segments = outline.get("sections", [])
            else:
                print(
                    f"WARNING: edl_service: neither script_draft.json nor "
                    f"outline.json found for {project_name!r}; generating EDL "
                    f"without header/counter overlays."
                )

        if segments is not None:
            total_items = len(segments)
            if header_style.get("enabled", True):
                titles = _listicle_segment_titles(segments)
                # Item segments are body segment_ids 0..N-1 (hook=-1,
                # conclusion=-2 don't get item headers). 1-indexed display.
                for seg_id, title in titles.items():
                    if seg_id < 0 or not title:
                        continue
                    overlay_for_segment[seg_id] = f"{seg_id + 1}. {title}"

    # Build each scene's overlays list. Deterministic: same inputs → same EDL.
    # ``stamped`` tracks segments already given a header so only the FIRST scene
    # of each item segment carries it.
    stamped: set[int] = set()
    scenes: list[dict] = []
    for scene in scene_windows:
        sid = scene["id"]
        seg_id = scene.get("segment_id")
        overlays: list[dict] = []

        # header — first scene of each item segment (listicle only).
        has_header = False
        if (
            seg_id is not None
            and seg_id in overlay_for_segment
            and seg_id not in stamped
        ):
            overlays.append({
                "kind": "header",
                "text": overlay_for_segment[seg_id],
                "position": header_style["position"],
                "animation": header_style["animation"],
                "start_offset": 0.0,
                "duration": None,
            })
            stamped.add(seg_id)
            has_header = True

        # counter — every body-item scene (listicle only).
        if (
            listicle
            and counter_style.get("enabled", True)
            and seg_id is not None
            and seg_id >= 0
        ):
            overlays.append({
                "kind": "counter",
                "text": f"{seg_id + 1} / {total_items}",
                "position": counter_style["position"],
                "animation": "none",
                "start_offset": 0.0,
                "duration": None,
            })

        # callout — on_screen_text on any scene, unless this scene already
        # carries a header (see docstring: the header owns the item-intro
        # scene; the on_screen_text there restates the title).
        on_screen = (scene.get("on_screen_text") or "").strip()
        if on_screen and callout_style.get("enabled", True) and not has_header:
            overlays.append({
                "kind": "callout",
                "text": on_screen,
                "position": callout_style["position"],
                "animation": callout_style["animation"],
                "start_offset": callout_style["start_offset"],
                "duration": callout_style["duration"],
            })

        scenes.append({
            "id": sid,
            "transition": transition,
            "ken_burns": ken_burns,
            "overlays": overlays,
        })

    return {
        "version": EDL_SCHEMA_VERSION,
        "scenes": scenes,
    }
