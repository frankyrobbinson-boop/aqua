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
from services.title_card_registry import (
    delete_preset as delete_title_card_preset,
    load_library as load_title_card_library,
    save_preset as save_title_card_preset,
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

# Saved-design extras: the GardenBloom-only Lottie fields that _sanitize_props
# drops but a persisted design must round-trip (see _sanitize_card_design).
_MAX_LOTTIE_ROWS = 4
_MAX_LOTTIE_NAME_LEN = 80
_DEFAULT_LOTTIE_RECOLOR_AMOUNT = 0.8

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


class SaveTitleCardRequest(BaseModel):
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
    # missing/invalid. (The MP4 render still drops the other lottie fields today,
    # so this only bites once Lotties bake into renders — kept correct now.)
    recolor_color = str(raw.get("lottieRecolorColor", ""))
    out["lottieRecolorColor"] = (
        recolor_color if _HEX_RE.match(recolor_color) else palette_out["accent"]
    )

    # foliageColor — GardenBloom's SVG foliage/leaf color, INDEPENDENT of the
    # text (which still colors the title/subtitle). Strict #rrggbb; falls back to
    # the sanitized text color when missing/invalid. This lives in _sanitize_props
    # (NOT only the card-design wrapper) because the SVG foliage DOES bake into the
    # MP4 render, so the render path must honor it.
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
    """Sanitize a SAVED title-card design: the strict/lenient render props from
    ``_sanitize_props`` PLUS the GardenBloom-only Lottie fields that
    ``_sanitize_props`` drops. The MP4 render path doesn't need those extras yet,
    but a persisted design must round-trip losslessly. The runtime-only
    ``lottieData`` is never persisted (``_sanitize_props`` already drops it and
    we never re-attach it). Each extra is attached only when present in ``raw``."""
    out = _sanitize_props(raw)

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


# ---------------------------------------------------------------------------
# Per-channel title-card design library (Phase 1 persistence). Named designs the
# /remotion designer can save, list, load, and delete. Stored under
# prompts/channels/<id>/title_cards.json via services.title_card_registry.
# ---------------------------------------------------------------------------


@router.get("/channels/{channel_id}/title-cards")
def get_title_cards(channel_id: str) -> dict[str, Any]:
    """The channel's saved title-card design library (default + presets)."""
    try:
        return load_title_card_library(channel_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/channels/{channel_id}/title-cards")
def save_title_card(channel_id: str, req: SaveTitleCardRequest) -> dict[str, Any]:
    """Upsert a named title-card design under this channel; returns the updated
    library. 422 on an unknown card_id, a bad name, or bad props; 404 on an
    unknown channel."""
    if req.card_id not in ALLOWED_COMPS:
        raise HTTPException(
            status_code=422, detail=f"unknown card_id: {req.card_id!r}"
        )
    name = _validate_preset_name(req.name)
    props = _sanitize_card_design(req.props)
    try:
        return save_title_card_preset(channel_id, name, req.card_id, props)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.delete("/channels/{channel_id}/title-cards/{name}")
def delete_title_card(channel_id: str, name: str) -> dict[str, Any]:
    """Delete a named title-card design; returns the updated library. 404 if the
    channel or the named preset is unknown."""
    # FastAPI hands us the URL-decoded segment; still guard its shape so a
    # decoded "/" or control char can't slip past.
    name = _validate_preset_name(name)
    try:
        return delete_title_card_preset(channel_id, name)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
