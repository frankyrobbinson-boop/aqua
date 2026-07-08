"""Remotion garden title-card render endpoint.

POST /remotion/render kicks off a Node render
(frontend/scripts/render-remotion.mjs) via the shared task runner and returns a
task_id (for SSE log streaming) plus the output filename. The MP4 lands in
backend/output/remotion/<uuid>.mp4, served by the /remotion-out StaticFiles
mount (see api/main.py). Standalone from the project video pipeline.

Props are validated with a HYBRID policy in ``_sanitize_props``: strict on the
things that matter for safety/correctness (comp allowlist, title, hex colors,
duration bounds, payload size) and lenient on the style enums (animation /
background / fontFamily / decoration pass through as strings — the frontend
cards fall back to defaults on unknown values). We always re-serialize the
sanitized props before handing them to the subprocess; the raw client string is
never passed through.
"""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.routes.tasks import start_task
from services.graphics_registry import (
    delete_preset as delete_graphics_preset,
    load_library as load_graphics_library,
    save_preset as save_graphics_preset,
)

router = APIRouter(tags=["remotion"])

# File-anchored paths so the API works regardless of uvicorn's launch cwd.
# This file is backend/api/routes/remotion.py, so parent x3 == backend/.
_HERE = Path(__file__).resolve()
BACKEND_DIR = _HERE.parent.parent.parent
FRONTEND_DIR = BACKEND_DIR.parent / "frontend"
REMOTION_OUT_DIR = BACKEND_DIR / "output" / "remotion"
_RENDER_SCRIPT = FRONTEND_DIR / "scripts" / "render-remotion.mjs"

# Mirror of CARD_IDS in frontend/src/remotion/cards/registry.ts. Keep in sync
# when adding or removing a card. Only these ids may be rendered.
ALLOWED_COMPS = frozenset(
    {
        "GardenCentered",
        "GardenFramed",
        "GardenBand",
        "GardenPremium",
        "GardenBloom",
    }
)

# Mirror of ROLES in frontend/src/remotion/cards/registry.ts and _ROLE_FILES in
# services/graphics_registry.py — the roles a saved graphic can be filed under.
# Keep the three in sync.
ALLOWED_ROLES = frozenset({"title", "section_header", "overlay", "transition"})

# Mirror of TRANSITION_IDS in frontend/src/remotion/transitions/registry.ts — the
# transition types a saved "transition"-role design may use (its card_id slot).
# Keep in sync (same convention as CARD_IDS ↔ ALLOWED_COMPS).
ALLOWED_TRANSITIONS = frozenset(
    {
        # Tier A — CSS/SVG presentations.
        "crossfade",
        "slide",
        "wipe",
        "clockWipe",
        "iris",
        "flip",
        "flowerSwipe",
        "flicker",
        # Tier B — @remotion/transitions WebGL shader presentations.
        "zoomBlur",
        "crossZoom",
        "crosswarp",
        "filmBurn",
        "dissolve",
        "linearBlur",
        "ripple",
        "dreamyZoom",
    }
)

# Garden defaults, mirroring frontend/src/remotion/cards/defaults.ts.
_DEFAULT_PALETTE = {
    "background": "#e9f1e4",
    "text": "#2f4a34",
    "accent": "#7bae5a",
}
_DEFAULT_DURATION = 5.0
_DURATION_MIN = 2.0
_DURATION_MAX = 20.0

_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
# Guard against oversized payloads before we do any per-field work.
_MAX_PROPS_BYTES = 4096
# Cap on any pass-through style enum string (lenient, but bounded).
_MAX_ENUM_LEN = 40
_MAX_SUBTITLE_LEN = 200
_MAX_EYEBROW_LEN = 40
_MAX_HIGHLIGHT_LEN = 60
_MAX_INDEX_LEN = 12

# GardenBloom-only Lottie config bounds. These fields flow through
# _sanitize_props so BOTH the MP4 render and a saved design keep them: the render
# script (render-remotion.mjs) loads each named file's JSON server-side into
# lottieData so the decorations bake into the MP4.
_MAX_LOTTIE_ROWS = 4
_MAX_LOTTIE_NAME_LEN = 80
_DEFAULT_LOTTIE_RECOLOR_AMOUNT = 0.8

# Transition-design bounds (saved from the /remotion "Transitions" tab). Mirror
# the knob ranges the designer exposes. Design + preview only — never a render
# input; the transition is not wired into the video pipeline.
_TRANSITION_FRAMES_MIN = 2
_TRANSITION_FRAMES_MAX = 120
_DEFAULT_TRANSITION_FRAMES = 30
_FLICKER_MIN = 1
_FLICKER_MAX = 20
_DEFAULT_FLICKER = 6
_DEFAULT_EDGE_COLOR = "#7bae5a"

# Per-type numeric knobs a transition may carry (flowerSwipe's angle + the Tier-B
# shader knobs), mirroring the `numericParams` slider ranges in
# frontend/src/remotion/transitions/registry.ts. Each is CLAMPED to its bounds
# and KEPT only when present, so a saved design (and the render-preview) honors
# the user's tweak. Split by storage type: the step-1/step-5 knobs
# (angle/amplitude/speed) store as ints — matching the designer's whole-number
# readout — while the sub-integer knobs stay float. Bounds span the widest range
# any transition exposes for a shared key (e.g. intensity: dissolve 0..2).
_TRANSITION_INT_KNOBS: dict[str, tuple[int, int]] = {
    "angle": (-45, 45),
    "amplitude": (0, 300),
    "speed": (0, 150),
}
_TRANSITION_FLOAT_KNOBS: dict[str, tuple[float, float]] = {
    "rotation": (0.0, 1.2),
    "strength": (0.0, 1.0),
    "seed": (0.0, 10.0),
    "intensity": (0.0, 2.0),
    "scale": (1.0, 2.0),
}

# Render-preview hold (frames) per clip, passed to TransitionPreview so the
# rendered stage stays short (~1.5–2s at 30fps): total = durationInFrames +
# 2*hold. Small on purpose — the browser can't preview Tier-B shaders, so this
# quick render stands in.
_TRANSITION_PREVIEW_HOLD = 12

# Title-card preset name — must be a safe single URL path segment: 1..60 chars
# after trim, no "/" and no C0/DEL control characters.
_PRESET_NAME_MIN = 1
_PRESET_NAME_MAX = 60
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]")


class RemotionRenderRequest(BaseModel):
    comp: str
    props: dict[str, Any] = {}


class RemotionRenderResponse(BaseModel):
    task_id: str
    filename: str


class TransitionPreviewRequest(BaseModel):
    """Body for POST /transitions/preview: the transition TYPE (validated against
    ALLOWED_TRANSITIONS) and its param set (sanitized via
    _sanitize_transition_design)."""

    type: str
    params: dict[str, Any] = {}


class SaveGraphicRequest(BaseModel):
    name: str
    card_id: str
    props: dict[str, Any] = {}


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _enum_str(value: Any, default: str) -> str:
    """Lenient pass-through for a style enum: keep any non-empty string within a
    length bound, else fall back to the default. Unknown values are fine — the
    frontend cards fall back to their own defaults on unrecognized ids."""
    if isinstance(value, str):
        v = value.strip()
        if 0 < len(v) <= _MAX_ENUM_LEN:
            return v
    return default


def _sanitize_props(raw: dict[str, Any]) -> dict[str, Any]:
    """Validate/normalize client props into the CardProps shape. Strict on the
    safety-relevant fields; lenient on style enums. Raises HTTP 422 on the
    strict failures."""
    if not isinstance(raw, dict):
        raise HTTPException(status_code=422, detail="props must be an object")

    # Payload-size guard on the incoming props.
    try:
        raw_size = len(json.dumps(raw, ensure_ascii=False).encode("utf-8"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="props is not serializable")
    if raw_size > _MAX_PROPS_BYTES:
        raise HTTPException(status_code=422, detail="props payload too large")

    # title — required, 1..120 after trim.
    title = str(raw.get("title", "")).strip()
    if not (1 <= len(title) <= 120):
        raise HTTPException(
            status_code=422, detail="title must be 1–120 characters"
        )

    out: dict[str, Any] = {"title": title}

    # subtitle — optional, trimmed, length-capped.
    subtitle = raw.get("subtitle")
    if subtitle is not None:
        sub = str(subtitle).strip()[:_MAX_SUBTITLE_LEN]
        if sub:
            out["subtitle"] = sub

    # eyebrow — optional kicker (GardenPremium), trimmed, length-capped.
    eyebrow = raw.get("eyebrow")
    if eyebrow is not None:
        eb = str(eyebrow).strip()[:_MAX_EYEBROW_LEN]
        if eb:
            out["eyebrow"] = eb

    # highlight — optional title word/phrase to accent, trimmed, length-capped.
    highlight = raw.get("highlight")
    if highlight is not None:
        hl = str(highlight).strip()[:_MAX_HIGHLIGHT_LEN]
        if hl:
            out["highlight"] = hl

    # index — optional section-header badge (GardenFramed/GardenBand bake it into
    # the MP4), trimmed, length-capped. Kept AS TYPED (the user controls the '#').
    index = raw.get("index")
    if index is not None:
        ix = str(index).strip()[:_MAX_INDEX_LEN]
        if ix:
            out["index"] = ix

    # durationInSeconds — clamp to [2, 20].
    try:
        duration = float(raw.get("durationInSeconds", _DEFAULT_DURATION))
    except (TypeError, ValueError):
        duration = _DEFAULT_DURATION
    out["durationInSeconds"] = _clamp(duration, _DURATION_MIN, _DURATION_MAX)

    # palette — strict #rrggbb per channel, else the garden default.
    palette_in = raw.get("palette")
    if not isinstance(palette_in, dict):
        palette_in = {}
    palette_out: dict[str, str] = {}
    for key, default in _DEFAULT_PALETTE.items():
        val = str(palette_in.get(key, default))
        palette_out[key] = val if _HEX_RE.match(val) else default
    out["palette"] = palette_out

    # lottieRecolorColor — GardenBloom's Lottie recolor target, INDEPENDENT of
    # the accent. Strict #rrggbb; falls back to the sanitized accent when
    # missing/invalid.
    recolor_color = str(raw.get("lottieRecolorColor", ""))
    out["lottieRecolorColor"] = (
        recolor_color if _HEX_RE.match(recolor_color) else palette_out["accent"]
    )

    # lottieAnimations / lottieDensity / lottieRecolorAmount — GardenBloom's
    # Lottie config (which files, how many instances, how strongly recolored).
    # Kept on BOTH the render and the save path: render-remotion.mjs loads each
    # named file's JSON server-side into `lottieData` so the decorations bake into
    # the MP4. This is small, already-validated config — the big JSON is never
    # sent here, and the runtime-only `lottieData` is never accepted. Each field
    # is attached only when present in `raw`.

    # lottieAnimations — up to _MAX_LOTTIE_ROWS rows; skip malformed entries.
    anims = raw.get("lottieAnimations")
    if isinstance(anims, list):
        rows: list[dict[str, Any]] = []
        for item in anims:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()[:_MAX_LOTTIE_NAME_LEN]
            if not name:
                continue
            rows.append(
                {
                    "name": name,
                    "loop": bool(item.get("loop", True)),
                    "recolor": bool(item.get("recolor", True)),
                }
            )
            if len(rows) >= _MAX_LOTTIE_ROWS:
                break
        if rows:
            out["lottieAnimations"] = rows

    # lottieDensity — lenient enum, default "low".
    if "lottieDensity" in raw:
        out["lottieDensity"] = _enum_str(raw.get("lottieDensity"), "low")

    # lottieRecolorAmount — clamp to [0, 1]; default 0.8 when present-but-invalid.
    if "lottieRecolorAmount" in raw:
        try:
            amount = float(raw["lottieRecolorAmount"])
        except (TypeError, ValueError):
            amount = _DEFAULT_LOTTIE_RECOLOR_AMOUNT
        out["lottieRecolorAmount"] = _clamp(amount, 0.0, 1.0)

    # foliageColor — GardenBloom's SVG foliage/leaf color, INDEPENDENT of the
    # text (which still colors the title/subtitle). Strict #rrggbb; falls back to
    # the sanitized text color when missing/invalid. Bakes into the MP4 render,
    # so the render path honors it too.
    foliage_color = str(raw.get("foliageColor", ""))
    out["foliageColor"] = (
        foliage_color if _HEX_RE.match(foliage_color) else palette_out["text"]
    )

    # style enums — lenient pass-through with defaults.
    out["animation"] = _enum_str(raw.get("animation"), "rise")
    out["background"] = _enum_str(raw.get("background"), "gradient")
    out["fontFamily"] = _enum_str(raw.get("fontFamily"), "nunito")

    decoration_in = raw.get("decoration")
    if not isinstance(decoration_in, dict):
        decoration_in = {}
    out["decoration"] = {
        "set": _enum_str(decoration_in.get("set"), "leaves"),
        "density": _enum_str(decoration_in.get("density"), "low"),
    }

    return out


def _sanitize_card_design(raw: dict[str, Any]) -> dict[str, Any]:
    """Sanitize a SAVED title-card design. Identical to ``_sanitize_props`` now
    that the GardenBloom Lottie config (lottieAnimations / lottieDensity /
    lottieRecolorAmount) flows through the render path too — a saved design and a
    render sanitize the same way. Kept as a named delegate so the save call site
    reads intentionally (and leaves a seam for save-only extras later). The
    runtime-only ``lottieData`` is never persisted (never accepted by
    ``_sanitize_props``)."""
    return _sanitize_props(raw)


def _sanitize_transition_design(raw: dict[str, Any]) -> dict[str, Any]:
    """Sanitize a SAVED transition design (the /remotion "Transitions" tab).
    Strict on the safety-relevant bits (payload size, integer clamps, hex color);
    lenient on the direction/timing enums (the frontend registry falls back to
    its own defaults on unknown ids). Design + preview only — never a render
    input. Raises HTTP 422 on the strict failures."""
    if not isinstance(raw, dict):
        raise HTTPException(status_code=422, detail="props must be an object")

    # Payload-size guard on the incoming props.
    try:
        raw_size = len(json.dumps(raw, ensure_ascii=False).encode("utf-8"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="props is not serializable")
    if raw_size > _MAX_PROPS_BYTES:
        raise HTTPException(status_code=422, detail="props payload too large")

    out: dict[str, Any] = {}

    # durationInFrames — integer clamp to [2, 120].
    try:
        frames = int(float(raw.get("durationInFrames", _DEFAULT_TRANSITION_FRAMES)))
    except (TypeError, ValueError):
        frames = _DEFAULT_TRANSITION_FRAMES
    out["durationInFrames"] = int(
        _clamp(frames, _TRANSITION_FRAMES_MIN, _TRANSITION_FRAMES_MAX)
    )

    # direction / timing — lenient enums with defaults.
    out["direction"] = _enum_str(raw.get("direction"), "from-left")
    out["timing"] = _enum_str(raw.get("timing"), "linear")

    # flickerCount — integer clamp to [1, 20].
    try:
        flicker = int(float(raw.get("flickerCount", _DEFAULT_FLICKER)))
    except (TypeError, ValueError):
        flicker = _DEFAULT_FLICKER
    out["flickerCount"] = int(_clamp(flicker, _FLICKER_MIN, _FLICKER_MAX))

    # edgeColor — strict #rrggbb, else the garden accent default.
    edge_color = str(raw.get("edgeColor", ""))
    out["edgeColor"] = (
        edge_color if _HEX_RE.match(edge_color) else _DEFAULT_EDGE_COLOR
    )

    # Per-type numeric knobs — CLAMP + KEEP each one that's present so the tweak
    # survives a save and reaches the render-preview. A present-but-unparseable
    # value is dropped (the frontend reseeds it from defaultParams on load).
    for key, (lo_i, hi_i) in _TRANSITION_INT_KNOBS.items():
        if key in raw:
            try:
                out[key] = int(_clamp(int(float(raw[key])), lo_i, hi_i))
            except (TypeError, ValueError):
                pass
    for key, (lo_f, hi_f) in _TRANSITION_FLOAT_KNOBS.items():
        if key in raw:
            try:
                out[key] = _clamp(float(raw[key]), lo_f, hi_f)
            except (TypeError, ValueError):
                pass

    return out


def _validate_preset_name(name: str) -> str:
    """Trim + validate a preset name so it's safe as a single URL path segment:
    1..60 chars, no "/", no control characters. Raises HTTP 422 on violation."""
    trimmed = name.strip()
    if not (_PRESET_NAME_MIN <= len(trimmed) <= _PRESET_NAME_MAX):
        raise HTTPException(
            status_code=422,
            detail=(
                f"preset name must be {_PRESET_NAME_MIN}–{_PRESET_NAME_MAX} "
                f"characters"
            ),
        )
    if "/" in trimmed or _CONTROL_CHAR_RE.search(trimmed):
        raise HTTPException(
            status_code=422,
            detail="preset name may not contain '/' or control characters",
        )
    return trimmed


@router.post("/remotion/render", response_model=RemotionRenderResponse)
async def start_remotion_render(
    req: RemotionRenderRequest,
) -> RemotionRenderResponse:
    """Render one garden title card to MP4 with the given props.

    No per-slug lock (single-user tool); the frontend disables the button while
    a render is in flight. Each call writes a fresh uuid-named file so repeat
    renders don't clobber one another."""
    if req.comp not in ALLOWED_COMPS:
        raise HTTPException(
            status_code=422, detail=f"unknown comp: {req.comp!r}"
        )

    props = _sanitize_props(req.props)

    REMOTION_OUT_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}.mp4"
    abs_out = REMOTION_OUT_DIR / filename

    cmd = [
        "node",
        str(_RENDER_SCRIPT),
        f"--comp={req.comp}",
        f"--props={json.dumps(props)}",
        f"--out={abs_out}",
    ]
    task = start_task(
        cmd=cmd,
        cwd=str(FRONTEND_DIR),
        kind="remotion",
    )
    return RemotionRenderResponse(task_id=task.id, filename=filename)


@router.post("/transitions/preview", response_model=RemotionRenderResponse)
async def start_transition_preview(
    req: TransitionPreviewRequest,
) -> RemotionRenderResponse:
    """Render the two-clip TransitionPreview stage to a SHORT MP4 for the
    /remotion "Transitions" tab.

    The live browser <Player> can't run the Tier-B WebGL shader transitions, so
    the designer previews those through this quick render instead. Mirrors
    /remotion/render (task runner + SSE + uuid file under output/remotion/,
    served by the /remotion-out mount). The comp is always TransitionPreview —
    validated HERE by the transition TYPE against ALLOWED_TRANSITIONS; it is
    intentionally NOT in ALLOWED_COMPS (never a card render, never a pipeline
    input). A small hold keeps the clip short (~1.5–2s)."""
    if req.type not in ALLOWED_TRANSITIONS:
        raise HTTPException(
            status_code=422, detail=f"unknown transition: {req.type!r}"
        )

    params = _sanitize_transition_design(req.params)

    REMOTION_OUT_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}.mp4"
    abs_out = REMOTION_OUT_DIR / filename

    # Props match TransitionPreview's shape ({type, params, holdFrames}); the
    # short hold is the only render-specific tweak. Root.tsx's calculateMetadata
    # derives the composition length from these.
    props = {
        "type": req.type,
        "params": params,
        "holdFrames": _TRANSITION_PREVIEW_HOLD,
    }
    cmd = [
        "node",
        str(_RENDER_SCRIPT),
        "--comp=TransitionPreview",
        f"--props={json.dumps(props)}",
        f"--out={abs_out}",
    ]
    task = start_task(
        cmd=cmd,
        cwd=str(FRONTEND_DIR),
        kind="remotion",
    )
    return RemotionRenderResponse(task_id=task.id, filename=filename)


# ---------------------------------------------------------------------------
# Per-channel graphics design library (Phase 1 persistence). Named designs the
# /remotion designer can save, list, load, and delete, keyed by role. Stored
# under prompts/channels/<id>/<role-file>.json via services.graphics_registry
# (title_cards.json, section_headers.json, overlays.json, transitions.json).
# ---------------------------------------------------------------------------


@router.get("/channels/{channel_id}/graphics/{role}")
def get_graphics(channel_id: str, role: str) -> dict[str, Any]:
    """The channel's saved graphics library for one role (default + presets).
    422 on an unknown role; 404 on an unknown channel."""
    if role not in ALLOWED_ROLES:
        raise HTTPException(status_code=422, detail=f"unknown role: {role!r}")
    try:
        return load_graphics_library(channel_id, role)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/channels/{channel_id}/graphics/{role}")
def save_graphic(
    channel_id: str, role: str, req: SaveGraphicRequest
) -> dict[str, Any]:
    """Upsert a named graphics design under this channel + role; returns the
    updated library. 422 on an unknown role, an unknown card_id / transition
    type, a bad name, or bad props; 404 on an unknown channel."""
    if role not in ALLOWED_ROLES:
        raise HTTPException(status_code=422, detail=f"unknown role: {role!r}")
    name = _validate_preset_name(req.name)
    if role == "transition":
        # Transition designs reuse the {name, card_id, props} record: card_id is
        # the transition TYPE (ALLOWED_TRANSITIONS), props is its param set.
        if req.card_id not in ALLOWED_TRANSITIONS:
            raise HTTPException(
                status_code=422,
                detail=f"unknown transition: {req.card_id!r}",
            )
        props = _sanitize_transition_design(req.props)
    else:
        if req.card_id not in ALLOWED_COMPS:
            raise HTTPException(
                status_code=422, detail=f"unknown card_id: {req.card_id!r}"
            )
        props = _sanitize_card_design(req.props)
    try:
        return save_graphics_preset(channel_id, role, name, req.card_id, props)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.delete("/channels/{channel_id}/graphics/{role}/{name}")
def delete_graphic(channel_id: str, role: str, name: str) -> dict[str, Any]:
    """Delete a named graphics design; returns the updated library. 422 on an
    unknown role or bad name; 404 if the channel or the named preset is
    unknown."""
    if role not in ALLOWED_ROLES:
        raise HTTPException(status_code=422, detail=f"unknown role: {role!r}")
    # FastAPI hands us the URL-decoded segment; still guard its shape so a
    # decoded "/" or control char can't slip past.
    name = _validate_preset_name(name)
    try:
        return delete_graphics_preset(channel_id, role, name)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
