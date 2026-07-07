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


class RemotionRenderRequest(BaseModel):
    comp: str
    props: dict[str, Any] = {}


class RemotionRenderResponse(BaseModel):
    task_id: str
    filename: str


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
