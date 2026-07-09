"""Per-scene Edit Decision List (EDL) for the render stage.

Stored at ``<projects_root>/<name>/edl.json`` with schema::

    {
      "version": 3,
      "scenes": [
        {
          "id": 0,
          "impact": "section_start",  # hook | section_start | conclusion |
                                       #   key_point | ordinary
          "transition": "cut",        # cut | fade (intra-clip dip to black)
          "ken_burns": false,
          "lead_in": {                 # how this scene enters: a plain cut, or a
            "type": "crossfade",        #   crossfade INTO a section_start /
            "params": {"frames": 12}    #   conclusion (prior clip dissolves in)
          },
          "card": {                    # optional — a section-header title card
            "role": "section_header",
            "comp": "GardenFramed",    # Remotion comp (the default preset card_id)
            "content": {"index": "1", "title": "Bee balm"}
          },
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

V2 replaced V1's single flat ``overlay_text`` / ``overlay_position`` with an
``overlays`` list so a scene can carry several composited overlays at once —
a listicle item's first scene shows a ``header`` (item title) + a ``counter``
(``n / total``), and any scene with on_screen_text shows a ``callout``. Each
overlay's position + animation are baked in at generation time from the
channel's editing style (``resolve_channel_editing``); the per-kind *look*
(fontsize / box / animation timings) is resolved again at render time from the
same style. SFX, music, custom transition timings, etc. remain future-phase.

V3 adds three fields per scene: ``impact`` (narrative weight — the first scene
of the hook / each body section / the conclusion), ``lead_in`` (how the scene
enters — a ``crossfade`` INTO each section_start / conclusion, a ``cut``
everywhere else; derived per ``impact``), and an
optional ``card`` (a section-header title card, emitted at each section start
ONLY when the channel has a section-header DEFAULT design — opt-in per channel).
A ``card`` stores just its ``comp`` + per-video ``content{index,title}``; the
card's design ``props`` re-resolve from the channel default at render time
(assembly_service), and a card's presence DROPS that scene's numbered header +
counter overlays (the number lives on the card badge instead). ``transition``
stays the intra-clip dip-to-black string and is NOT overloaded by ``lead_in``.

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
from services.graphics_registry import resolve_section_header_default
from services.paths import PROJECTS_ROOT

EDL_SCHEMA_VERSION = 3

# Default crossfade width (in frames) for a section-boundary ``lead_in`` — the
# dissolve INTO each section_start / conclusion scene. A constant default for now;
# a channel ``edit_defaults`` block will make the width (and type) configurable
# per channel in a later step. Assembly (SECTION_XFADE_FRAMES) uses the same 12.
DEFAULT_LEAD_IN_FRAMES = 12


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
    """Build a per-scene EDL (v3) from the project's upstream artifacts.

    For every scene: transition + ken_burns are populated from the kwargs
    (so a render-triggered EDL respects the user's Render-tab choices);
    ``impact`` marks the scene's narrative weight (first scene of the hook /
    each body section / the conclusion); ``lead_in`` is derived per ``impact`` —
    a ``crossfade`` (default DEFAULT_LEAD_IN_FRAMES wide) INTO each section_start
    / conclusion, a ``cut`` everywhere else (the hook is scene 0 with no
    preceding clip). The first scene of each body
    section additionally gets a section-header ``card`` — but ONLY when the
    channel has a section-header DEFAULT design (opt-in per channel); a card
    DROPS that scene's numbered header + counter overlays. Each scene's
    ``overlays`` list is built from the channel's editing style
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

    # Section-header card design for this channel. A ``card`` is emitted at each
    # section start ONLY when the channel has a section-header DEFAULT preset
    # (opt-in per channel); otherwise no card is emitted and the listicle
    # header/counter overlays behave exactly as before. Resolved once — the card
    # stores only the comp + per-video content{index,title}; the design props
    # re-resolve from this same default at render time (assembly_service).
    section_header_default = resolve_section_header_default(channel_id)

    # Body segment titles (segment_id -> title). Feeds BOTH the listicle
    # "{N}. {title}" header text AND the section-header card content, so it's
    # resolved whenever either is needed. total_items feeds the listicle
    # counter's "{n} / {total}" text (len of the segment list).
    seg_titles: dict[int, str] = {}
    total_items = 0
    if listicle or section_header_default is not None:
        segments: list | None = None
        if script_draft is not None:
            segments = script_draft.get("segments", [])
        else:
            outline = _load_json(proj / "outline.json")
            if outline is not None:
                print(
                    f"WARNING: edl_service: script_draft.json missing for "
                    f"{project_name!r}; falling back to outline.json sections "
                    f"for header/card text."
                )
                segments = outline.get("sections", [])
            else:
                print(
                    f"WARNING: edl_service: neither script_draft.json nor "
                    f"outline.json found for {project_name!r}; generating EDL "
                    f"without header/counter/card text."
                )
        if segments is not None:
            total_items = len(segments)
            seg_titles = _listicle_segment_titles(segments)

    # Listicle "{N}. {title}" header text per body-item segment (listicle only,
    # header enabled). The card path (below) supersedes this on section-start
    # scenes when the channel has a section-header default.
    overlay_for_segment: dict[int, str] = {}
    if listicle and header_style.get("enabled", True):
        # Item segments are body segment_ids 0..N-1 (hook=-1, conclusion=-2
        # don't get item headers). 1-indexed display.
        for seg_id, title in seg_titles.items():
            if seg_id < 0 or not title:
                continue
            overlay_for_segment[seg_id] = f"{seg_id + 1}. {title}"

    # Build each scene's overlays list. Deterministic: same inputs → same EDL.
    # ``first_seen`` tracks the first scene of each segment_id (for ``impact``
    # and the section-start card); ``stamped`` tracks segments whose header/card
    # is already placed so only the FIRST scene of an item segment carries it.
    first_seen: set[int] = set()
    stamped: set[int] = set()
    scenes: list[dict] = []
    for scene in scene_windows:
        sid = scene["id"]
        seg_id = scene.get("segment_id")
        overlays: list[dict] = []

        # impact — narrative weight. The FIRST scene of the hook (segment_id -1),
        # of each body section (>= 0), and of the conclusion (-2). ``key_point``
        # is never auto-assigned (override-only, later); else ``ordinary``.
        is_first_of_segment = seg_id is not None and seg_id not in first_seen
        if seg_id is not None:
            first_seen.add(seg_id)
        if is_first_of_segment and seg_id == -1:
            impact = "hook"
        elif is_first_of_segment and seg_id == -2:
            impact = "conclusion"
        elif is_first_of_segment and seg_id >= 0:
            impact = "section_start"
        else:
            impact = "ordinary"

        # lead_in — how this scene ENTERS from the previous one. A section start
        # or the conclusion dissolves in via a crossfade (the previous section's
        # footage blends INTO this scene, which at a section start is its header
        # card); the hook (scene 0 — no preceding clip) and every ordinary scene
        # hard-cut. Width is the constant default for now (channel edit_defaults
        # makes it configurable later). ``transition`` (intra-clip dip) is separate
        # and NOT overloaded by this.
        if impact in ("section_start", "conclusion"):
            lead_in = {"type": "crossfade", "params": {"frames": DEFAULT_LEAD_IN_FRAMES}}
        else:
            lead_in = {"type": "cut"}

        # card — section-header title card at each section start, ONLY when the
        # channel has a section-header default. Stores the comp + per-video
        # content{index,title}; props re-resolve at render. A card OWNS the
        # item-intro scene: its badge carries the number+title, so the numbered
        # header + counter overlays are dropped for that scene (and the segment
        # is ``stamped`` so a later scene of it doesn't pick the header back up).
        card: dict | None = None
        if impact == "section_start" and section_header_default is not None:
            title = seg_titles.get(seg_id) or (scene.get("segment_title") or "").strip()
            if title:
                card = {
                    "role": "section_header",
                    "comp": section_header_default["comp"],
                    "content": {"index": str(seg_id + 1), "title": title},
                }
                stamped.add(seg_id)

        # header — first scene of each item segment (listicle only), unless a
        # card already labels this segment's intro scene.
        has_header = False
        if (
            card is None
            and seg_id is not None
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

        # counter — every body-item scene (listicle only), except a scene that
        # got a card (the card badge carries the number).
        if (
            card is None
            and listicle
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
        # carries a header OR a card (both own the item-intro scene; the
        # on_screen_text there restates the title, so a callout would double-
        # label). With no card this is byte-identical to before.
        on_screen = (scene.get("on_screen_text") or "").strip()
        if (
            on_screen
            and callout_style.get("enabled", True)
            and not has_header
            and card is None
        ):
            overlays.append({
                "kind": "callout",
                "text": on_screen,
                "position": callout_style["position"],
                "animation": callout_style["animation"],
                "start_offset": callout_style["start_offset"],
                "duration": callout_style["duration"],
            })

        entry: dict = {
            "id": sid,
            "impact": impact,
            "transition": transition,
            "ken_burns": ken_burns,
            "lead_in": lead_in,
            "overlays": overlays,
        }
        if card is not None:
            entry["card"] = card
        scenes.append(entry)

    return {
        "version": EDL_SCHEMA_VERSION,
        "scenes": scenes,
    }
