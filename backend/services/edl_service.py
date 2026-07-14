"""Per-scene Edit Decision List (EDL) for the render stage.

Stored at ``<projects_root>/<name>/edl.json`` with schema::

    {
      "version": 6,
      "scenes": [
        {
          "id": 0,
          "impact": "section_start",  # hook | section_start | conclusion |
                                       #   key_point | ordinary
          "transition": "cut",        # cut | fade (intra-clip dip to black)
          "ken_burns": false,
          "lead_in": {                 # how this scene enters: a plain "cut", a
            "type": "fade_black",       #   "fade_black" THROUGH black INTO a
            "params": {"frames": 28}    #   section_start / conclusion / title scene,
          },                            #   or a "blur_dissolve" at a within-segment
                                        #   visual-subject shift (mid-tier dissolve)
          "card": {                    # optional — a section-header OR mid-hook
            "role": "section_header",   #   title card ("section_header" | "title")
            "comp": "GardenFramed",    # Remotion comp (the default preset card_id)
            "content": {"index": "1", "item_noun": "Flower", "title": "Bee balm"}
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

V4 adds a second ``card`` role — an opt-in mid-hook ``title`` card
(``role:"title"``). It is emitted at the ONE hook scene (``segment_id == -1``)
whose narration OPENS WITH the script's ``title_spoken`` (a reworded on-screen
mirror of the spoken title): the scene's leading normalized tokens must equal
``title_spoken``'s first K=min(len,12) tokens (``_find_title_scene_id``). This
front-alignment GATE means the card ships only when the spoken title actually
starts a hook scene, so card and voiceover begin together; if ``title_spoken``
lands only mid-scene the card is DROPPED and a warning logged (never a
misaligned card). Like the section-header card it is opt-in per channel (emitted
only when the channel has a ``title`` DEFAULT design) and stores just its
``comp`` + ``content{title}`` (no index; props re-resolve at render). A title
card OWNS its hook scene the same way a section card owns a section intro — its
duplicate callout is dropped.

V5 adds ``item_noun`` to a section-header card's ``content`` (alongside
``index`` + ``title``) — the singular noun of the listed subject the script
model fills at the top level (``Mistake`` / ``Dish`` / ``Move`` / …). It
lets the card render a ``"{item_noun} #{index}."`` label (the floral two-tier
header + the Garden badge prefix) instead of a bare number. Resolved from
``script_draft["item_noun"]`` (empty when the script predates the field or the
type doesn't set it — the card then falls back to the bare index, unchanged).
The mid-hook ``title`` card is untouched (it carries only a title).

V6 renames the section-boundary ``lead_in`` from a ``crossfade`` (an
``xfade=transition=fade`` dissolve of the prior footage) to a ``fade_black`` — an
``xfade=transition=fadeblack`` that fades the outgoing footage THROUGH black at
the original cut (which sits in the ~0.6s section-boundary silence) and rises the
incoming section-header (or title) card up FROM black. It is derived at every
``section_start`` + the ``conclusion`` (exactly where the crossfade was) PLUS the
mid-hook ``title`` scene WHEN a title card is emitted, so that card also rises
from black. ``lead_in.type`` is ``cut | blur_dissolve | fade_black``. The mid-tier
``blur_dissolve`` is emitted at ORDINARY WITHIN-SEGMENT seams where the two scenes'
visual SUBJECT shifts (a deterministic head-noun comparison of their
``visual_description``s, ``_classify_blur_dissolve_seams``), capped so it stays a
tier above — intermixed with, not a replacement for — hard cuts (a min gap between
dissolves + a per-segment cap) and never adjacent to another non-cut seam (so it
never lands on a section boundary, the hook, or the conclusion). Assembly renders
it as a short Remotion defocus-dissolve window spliced in place of the seam. Both
the fade and the blur-dissolve are duration-neutral by construction (the fade's
centre lands on the original cut with each flanking clip extended by half its
width; the blur window is capped to EXACTLY 2N frames and replaces the last N of
clip A + the first N of clip B), so the audio + subtitle timelines are unchanged.

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
import re
import tempfile
from pathlib import Path
from typing import Any

from services.channel_registry import resolve_channel_editing
from services.graphics_registry import (
    resolve_section_header_default,
    resolve_title_card_default,
)
from services.paths import PROJECTS_ROOT
from services.visual_subject import subject_from_description

EDL_SCHEMA_VERSION = 6

# Default fade-to-black width (in frames) recorded on a section-boundary
# ``lead_in``'s ``params`` — the ``fade_black`` INTO each section_start /
# conclusion (and the mid-hook title scene). A constant default for now; a channel
# ``edit_defaults`` block will make the width (and type) configurable per channel
# in a later step. Assembly owns the ACTUAL fade width (SECTION_FADEBLACK_FRAMES);
# this mirrors it (68 at 60fps) so the EDL records the true width, not a stale hint.
# EDL metadata only — assembly is authoritative for the rendered seam width.
DEFAULT_LEAD_IN_FRAMES = 68

# Mid-tier ``blur_dissolve`` defaults recorded on a ``blur_dissolve`` lead_in's
# ``params``. Like DEFAULT_LEAD_IN_FRAMES mirrors the fade width, these MIRROR the
# actual window params assembly owns (assembly_service BLUR_DISSOLVE_FRAMES /
# BLUR_DISSOLVE_MAX_BLUR) so the EDL records the true values, not stale hints;
# assembly stays authoritative for the render. ``frames`` is N (the window spans
# 2N frames — the last N of clip A + the first N of clip B); ``max_blur`` is the
# peak defocus (px @1080p). EDL metadata only — assembly owns the rendered window.
DEFAULT_BLUR_DISSOLVE_FRAMES = 24
DEFAULT_BLUR_DISSOLVE_MAX_BLUR = 36

# Mid-tier blur-dissolve classifier knobs — TUNE THESE to change how OFTEN a
# blur-dissolve appears at ordinary within-segment cuts. A dissolve is emitted at a
# within-segment seam only when the two scenes' visual subject shifts, and then
# only subject to these caps so it stays "a tier above" — intermixed with, not a
# replacement for — hard cuts:
#   BLUR_DISSOLVE_MIN_GAP_SEAMS   — at least this many seams between consecutive
#                                   blur-dissolves (also keeps them non-adjacent).
#   BLUR_DISSOLVE_MAX_PER_SEGMENT — at most this many within any one body segment.
# Raise the gap / lower the cap for rarer dissolves; do the reverse for more.
BLUR_DISSOLVE_MIN_GAP_SEAMS = 3
BLUR_DISSOLVE_MAX_PER_SEGMENT = 2


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


def _norm_tokens(text: str) -> list[str]:
    """Lowercase ``[a-z0-9]+`` tokens of ``text`` — the normalized token
    sequence used to align ``title_spoken`` against a hook scene's leading
    narration (case / punctuation / whitespace insensitive)."""
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def _find_title_scene_id(scene_windows: list, title_spoken: str) -> int | None:
    """Return the id of the HOOK scene (``segment_id == -1``) whose narration
    OPENS WITH ``title_spoken`` — its LEADING normalized tokens equal
    ``title_spoken``'s first K=min(len,12) tokens — else ``None``.

    This is the front-alignment gate for the mid-hook title card: the card is
    emitted ONLY at a hook scene that STARTS with the spoken title, so the
    on-screen card and the voiceover begin together. A ``title_spoken`` that
    lands only mid-scene (nowhere at the front of a hook scene) returns None, so
    the caller drops the card rather than ship a misaligned one. K is capped at
    12 tokens so a long spoken title still matches on its opening without needing
    the whole sentence to sit inside one scene."""
    key = _norm_tokens(title_spoken)
    if not key:
        return None
    k = min(len(key), 12)
    prefix = key[:k]
    for scene in scene_windows:
        if scene.get("segment_id") != -1:
            continue
        if _norm_tokens(scene.get("narration", ""))[:k] == prefix:
            return scene["id"]
    return None


def _visual_subject(visual_description: str) -> str:
    """The head-noun SUBJECT token of a scene's ``visual_description`` — its first
    normalized token that isn't a leading modifier. Empty string when the
    description is empty or all modifiers.

    Delegates to ``visual_subject.subject_from_description`` (the single source of
    truth, shared with the footage-fetch layer's relevance filter + query derivation) so
    the subject used to place blur-dissolve seams can never drift from the one
    used to fetch footage."""
    return subject_from_description(visual_description)


def _visual_subject_shifts(a: str, b: str) -> bool:
    """True when two scenes' ``visual_description``s have DIFFERENT subjects (their
    head nouns differ) — the deterministic mid-tier signal that the shot's subject
    genuinely changed (e.g. a hummingbird shot -> a flower shot). A missing subject
    on either side is treated as NO shift (conservative — no blur-dissolve)."""
    sa, sb = _visual_subject(a), _visual_subject(b)
    return bool(sa) and bool(sb) and sa != sb


def _classify_blur_dissolve_seams(
    scene_windows: list, fade_incoming_ids: set[int]
) -> set[int]:
    """Return the set of scene ids that should ENTER via a mid-tier
    ``blur_dissolve`` lead_in.

    A blur-dissolve is placed at an ORDINARY WITHIN-SEGMENT seam (both flanking
    scenes share a body ``segment_id`` >= 0 — never a section boundary, the hook,
    or the conclusion) when the two scenes' visual SUBJECT shifts
    (``_visual_subject_shifts``), subject to three caps that keep it a tier above —
    not a replacement for — hard cuts, and that preserve the assembly invariant
    that no two non-cut seams are adjacent (``_lead_in_seams``):

      * NO ADJACENCY — a candidate seam adjacent to an already-occupied seam (a
        section-boundary ``fade_black`` OR an already-placed blur-dissolve) is
        dropped (kept a hard cut), so no clip ever flanks two transitions.
      * MIN GAP — at least ``BLUR_DISSOLVE_MIN_GAP_SEAMS`` seams between
        consecutive blur-dissolves.
      * PER-SEGMENT CAP — at most ``BLUR_DISSOLVE_MAX_PER_SEGMENT`` per body
        segment.

    Seams are considered left-to-right, so on a collision the EARLIER seam wins and
    the later stays a hard cut. Deterministic: purely a function of scene order,
    ``segment_id``, ``visual_description``, and the fade-incoming set."""
    n = len(scene_windows)
    # Seam left-index i sits between scenes at positions i and i+1. A ``fade_black``
    # INTO the scene at position p occupies seam p-1 (matches _lead_in_seams).
    occupied: set[int] = set()
    for p, scene in enumerate(scene_windows):
        if p >= 1 and scene["id"] in fade_incoming_ids:
            occupied.add(p - 1)

    blur_ids: set[int] = set()
    per_segment: dict[int, int] = {}
    last_emitted: int | None = None
    for i in range(n - 1):
        a = scene_windows[i]
        b = scene_windows[i + 1]
        seg = a.get("segment_id")
        # Ordinary within-segment BODY seam only (same seg, seg >= 0). This
        # excludes section boundaries (seg changes), the hook (-1), the conclusion
        # (-2), AND a section_start's own scene (whose lead_in is fade_black).
        if seg is None or seg < 0 or b.get("segment_id") != seg:
            continue
        if not _visual_subject_shifts(
            a.get("visual_description", ""), b.get("visual_description", "")
        ):
            continue
        # No adjacency to any occupied seam (a fade OR a prior blur-dissolve).
        if i in occupied or (i - 1) in occupied or (i + 1) in occupied:
            continue
        if (
            last_emitted is not None
            and i - last_emitted < BLUR_DISSOLVE_MIN_GAP_SEAMS
        ):
            continue
        if per_segment.get(seg, 0) >= BLUR_DISSOLVE_MAX_PER_SEGMENT:
            continue
        blur_ids.add(b["id"])
        occupied.add(i)
        last_emitted = i
        per_segment[seg] = per_segment.get(seg, 0) + 1
    return blur_ids


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
    a ``fade_black`` (default DEFAULT_LEAD_IN_FRAMES wide) THROUGH black INTO each
    section_start / conclusion (and the mid-hook title scene when a title card is
    emitted), a ``cut`` everywhere else (the hook's first scene is scene 0 with no
    preceding clip). The first scene of each body
    section additionally gets a section-header ``card`` — but ONLY when the
    channel has a section-header DEFAULT design (opt-in per channel); a card
    DROPS that scene's numbered header + counter overlays. Separately, the ONE
    hook scene whose narration OPENS WITH the script's ``title_spoken`` gets a
    mid-hook ``title`` card — but ONLY when the channel has a ``title`` DEFAULT
    design AND a hook scene actually STARTS with the spoken title (the
    front-alignment gate, ``_find_title_scene_id``); if ``title_spoken`` lands
    only mid-scene no card is emitted and a warning is logged. Each scene's
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

    # Section-header card design(s) for this channel — a ROTATION SET (an ordered
    # list of {comp, props}) or None. A ``card`` is emitted at each section start
    # ONLY when the channel has a section-header design (opt-in per channel);
    # otherwise no card is emitted and the listicle header/counter overlays behave
    # exactly as before. The k-th section start (its 0-based seg_id) takes rotation
    # entry ``seg_id % len``, so consecutive sections show DIFFERENT designs
    # (wrapping when there are more sections than presets); a single-default
    # channel is a 1-element set (every section the same, as before). Each card
    # stores only its rotated comp + per-video content{index,item_noun,title}; the
    # design props (and the rotation) re-resolve at render time (assembly_service).
    section_header_rotation = resolve_section_header_default(channel_id)

    # Mid-hook title card design for this channel — same opt-in switch model as
    # the section header. A ``title`` card is emitted at the ONE hook scene whose
    # narration OPENS WITH the script's ``title_spoken`` (the reworded on-screen
    # mirror of the spoken title) and ONLY when the channel has a ``title``
    # DEFAULT preset. Resolve the default + the target hook scene id up front. If
    # a title default + title_spoken are both present but NO hook scene STARTS
    # with the spoken title (it lands only mid-scene), emit NO card and warn — a
    # card firing mid-narration would desync from the voiceover.
    title_card_default = resolve_title_card_default(channel_id)
    title_spoken = ((script_draft or {}).get("title_spoken") or "").strip()
    title_scene_id: int | None = None
    if title_card_default is not None and title_spoken:
        title_scene_id = _find_title_scene_id(scene_windows, title_spoken)
        if title_scene_id is None:
            print(
                f"WARNING: edl_service: title_spoken for {project_name!r} does "
                f"not OPEN any hook scene (segment_id -1) — no title card emitted "
                f"(a mid-scene card would misalign with the narration)."
            )

    # Mid-tier ``blur_dissolve`` seams — the ordinary within-segment cuts where the
    # visual subject shifts (capped + never adjacent to a non-cut seam). Computed up
    # front so the classifier can steer clear of section-boundary fades: first
    # resolve which scenes ENTER via ``fade_black`` (each section start + the
    # conclusion + the mid-hook title scene — the SAME set the per-scene loop below
    # derives), then classify the blur seams against it. The hook's first scene
    # (segment_id -1) hard-cuts, so it is NOT a fade-incoming scene.
    fade_incoming_ids: set[int] = set()
    _seen_seg: set[int] = set()
    for scene in scene_windows:
        seg_id = scene.get("segment_id")
        first = seg_id is not None and seg_id not in _seen_seg
        if seg_id is not None:
            _seen_seg.add(seg_id)
        if first and seg_id is not None and (seg_id >= 0 or seg_id == -2):
            fade_incoming_ids.add(scene["id"])
    if title_scene_id is not None:
        fade_incoming_ids.add(title_scene_id)
    blur_incoming_ids = _classify_blur_dissolve_seams(scene_windows, fade_incoming_ids)

    # item_noun — the singular noun of the listed subject (Mistake / Dish /
    # Move / …), a top-level field the script model fills. Stamped into each
    # section-header card's content so the card can render a
    # "{item_noun} #{index}." label; empty when the script predates the field or
    # the type doesn't set it (the card then shows the bare index, unchanged).
    item_noun = ((script_draft or {}).get("item_noun") or "").strip()

    # Body segment titles (segment_id -> title). Feeds BOTH the listicle
    # "{N}. {title}" header text AND the section-header card content, so it's
    # resolved whenever either is needed. total_items feeds the listicle
    # counter's "{n} / {total}" text (len of the segment list).
    seg_titles: dict[int, str] = {}
    total_items = 0
    if listicle or section_header_rotation:
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
        # or the conclusion fades up THROUGH black (the previous section's footage
        # fades to black at the cut, which sits in the section-boundary silence,
        # then this scene — its header card at a section start — rises FROM black);
        # the mid-hook ``title`` scene fades up the same way WHEN a title card is
        # emitted (so the title card also rises from black). The hook's first scene
        # (scene 0 — no preceding clip; a fade_black there would be inert under the
        # seam mechanic) and every ordinary scene hard-cut. Width is the constant
        # default for now (channel edit_defaults makes it configurable later).
        # A mid-tier ``blur_dissolve`` instead enters an ordinary within-segment
        # scene whose visual subject shifts (blur_incoming_ids — capped + never
        # adjacent to a non-cut seam, so it never collides with a fade). Fade takes
        # precedence, but the two sets are disjoint by construction (a blur seam is
        # only ever an ordinary within-segment cut). ``transition`` (intra-clip dip)
        # is separate and NOT overloaded by this.
        if impact in ("section_start", "conclusion") or (
            title_scene_id is not None and sid == title_scene_id
        ):
            lead_in = {"type": "fade_black", "params": {"frames": DEFAULT_LEAD_IN_FRAMES}}
        elif sid in blur_incoming_ids:
            lead_in = {
                "type": "blur_dissolve",
                "params": {
                    "frames": DEFAULT_BLUR_DISSOLVE_FRAMES,
                    "max_blur": DEFAULT_BLUR_DISSOLVE_MAX_BLUR,
                },
            }
        else:
            lead_in = {"type": "cut"}

        # card — at most one per scene, resolved in priority order. FIRST the
        # mid-hook ``title`` card: the single hook scene the gate aligned to
        # (title_scene_id) carries it, storing just comp + content{title} (no
        # index; props re-resolve at render). THEN the section-header card at
        # each section start (only when a section-header default exists), storing
        # comp + content{index,title}. A card OWNS its scene: its badge carries
        # the label, so the numbered header + counter + callout overlays are
        # dropped for that scene (the section case also ``stamps`` the segment so
        # a later scene of it doesn't pick the header back up).
        card: dict | None = None
        if title_scene_id is not None and sid == title_scene_id:
            card = {
                "role": "title",
                "comp": title_card_default["comp"],
                "content": {"title": title_spoken},
            }
        if card is None and impact == "section_start" and section_header_rotation:
            title = seg_titles.get(seg_id) or (scene.get("segment_title") or "").strip()
            if title:
                # Rotate through the section-header set by segment position so
                # each section start gets a different design (wraps past the end).
                # seg_id is the 0-based body-segment id, == this card's index-1.
                design = section_header_rotation[seg_id % len(section_header_rotation)]
                card = {
                    "role": "section_header",
                    "comp": design["comp"],
                    "content": {
                        "index": str(seg_id + 1),
                        "item_noun": item_noun,
                        "title": title,
                    },
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
