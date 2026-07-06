"""Remotion motion-graphics render endpoint.

POST /remotion/render kicks off a Node render
(frontend/scripts/render-remotion.mjs) via the shared task runner and returns a
task_id (for SSE log streaming) plus the output filename. The MP4 lands in
backend/output/remotion/<uuid>.mp4, served by the /remotion-out StaticFiles
mount (see api/main.py). Standalone from the project video pipeline.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.routes.tasks import start_task

router = APIRouter(tags=["remotion"])

# File-anchored paths so the API works regardless of uvicorn's launch cwd.
# This file is backend/api/routes/remotion.py, so parent x3 == backend/.
_HERE = Path(__file__).resolve()
BACKEND_DIR = _HERE.parent.parent.parent
FRONTEND_DIR = BACKEND_DIR.parent / "frontend"
REMOTION_OUT_DIR = BACKEND_DIR / "output" / "remotion"
_RENDER_SCRIPT = FRONTEND_DIR / "scripts" / "render-remotion.mjs"


class RemotionRenderRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=120)


class RemotionRenderResponse(BaseModel):
    task_id: str
    filename: str


@router.post("/remotion/render", response_model=RemotionRenderResponse)
async def start_remotion_render(req: RemotionRenderRequest) -> RemotionRenderResponse:
    """Render the TitleCard composition to MP4 with the given title.

    No per-slug lock (single-user tool); the frontend disables the button while
    a render is in flight. Each call writes a fresh uuid-named file so repeat
    renders don't clobber one another."""
    title = req.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="title must not be empty")

    REMOTION_OUT_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}.mp4"
    abs_out = REMOTION_OUT_DIR / filename

    cmd = [
        "node",
        str(_RENDER_SCRIPT),
        "--comp=TitleCard",
        f"--props={json.dumps({'title': title})}",
        f"--out={abs_out}",
    ]
    task = start_task(
        cmd=cmd,
        cwd=str(FRONTEND_DIR),
        kind="remotion",
    )
    return RemotionRenderResponse(task_id=task.id, filename=filename)
