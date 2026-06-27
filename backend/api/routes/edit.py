"""EDL (Edit Decision List) endpoints.

Routes:
    POST /projects/{slug}/edit   -> kick off run_edit.py
    GET  /projects/{slug}/edl    -> read the current EDL JSON

The POST mirrors the /render route's request shape so the same Render-tab
options (transition + ken_burns) flow into a pre-render EDL generation
without a separate UI. The Edit-tab UI (per-scene editing of overlays,
transitions, etc.) is a future phase — V1 is read-only auto-generated EDL.
"""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.routes.projects import _project_dir
from api.routes.tasks import start_task
from services.edl_service import load_edl


router = APIRouter(tags=["edit"])

# Anchor relative to this file so uvicorn-from-anywhere works
# (routes/ -> api/ -> backend/).
_HERE = Path(__file__).resolve()
BACKEND_DIR = str(_HERE.parent.parent.parent)


class EditRequest(BaseModel):
    project_slug: str
    # Mirrors RenderRequest — these become the EDL's per-scene defaults so
    # the user's Render-tab choices feed through when EDL is generated
    # ahead of (or alongside) render.
    transition: str | None = Field(default="cut", pattern=r"^(cut|fade)$")
    ken_burns: bool | None = Field(default=False)


class EditResponse(BaseModel):
    task_id: str
    project_slug: str


@router.post("/projects/{slug}/edit", response_model=EditResponse)
async def start_edit(slug: str, req: EditRequest) -> EditResponse:
    """Trigger run_edit.py for this project. Task-shape matches /render so
    the frontend can reuse the existing RunPanel + tasks SSE plumbing."""
    _project_dir(slug)
    # Slug in the URL is authoritative; the payload's project_slug is
    # ignored if it disagrees. Mirrors the /render route's pattern of
    # trusting the URL over the body.
    env = {
        "RENDER_TRANSITION": req.transition or "cut",
        "RENDER_KEN_BURNS": "1" if req.ken_burns else "0",
    }
    cmd = [sys.executable, "run_edit.py", slug]
    task = start_task(
        cmd=cmd,
        cwd=BACKEND_DIR,
        metadata={"kind": "edit", "project_slug": slug},
        env_overrides=env,
    )
    return EditResponse(task_id=task.id, project_slug=slug)


@router.get("/projects/{slug}/edl")
def get_edl(slug: str) -> dict:
    """Return the current EDL or 404 if the edit stage hasn't run yet."""
    _project_dir(slug)
    edl = load_edl(slug)
    if edl is None:
        raise HTTPException(
            status_code=404,
            detail=f"No EDL for project {slug!r}. Run /projects/{slug}/edit first.",
        )
    return edl
