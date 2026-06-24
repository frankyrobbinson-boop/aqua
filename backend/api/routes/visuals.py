"""Visual provider config endpoints + dispatch trigger.

Routes:
    GET /projects/{slug}/visual-config        -> effective config
    PUT /projects/{slug}/visual-config        -> persist user edits
    GET /visual-providers                     -> registry dump for dropdowns
    POST /projects/{slug}/visuals/generate    -> kick off run_visuals.py

The GET/PUT pair operates on ``../projects/<slug>/visual_config.json`` via
``visual_config_service``. The POST mirrors ``api.routes.pipeline.start_visuals``
shape so the frontend can reuse RunPanel + the existing tasks SSE plumbing.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, ConfigDict

from api.routes.projects import _project_dir
from api.routes.tasks import start_task
from services.visual_config_service import (
    load_visual_config,
    resolve_visual_config,
    save_visual_config,
)
from services.visual_provider_registry import (
    default_mode,
    default_provider_id,
    list_modes,
    list_providers,
)

router = APIRouter(tags=["visuals"])

# Anchored to this file's location so it works regardless of where uvicorn was
# launched from. routes/ -> api/ -> backend/.
_HERE = Path(__file__).resolve()
BACKEND_DIR = str(_HERE.parent.parent.parent)


# ---------------------------------------------------------------------------
# Pydantic payloads
# ---------------------------------------------------------------------------

class VisualSegmentEntry(BaseModel):
    """One segment-level provider assignment. ``scene_count`` is informational
    in Phase 1 (the live scene_plan still drives actual counts) so it's optional
    on PUT — clients can omit it and the server keeps whatever value the
    skeleton produced from scene_plan."""

    model_config = ConfigDict(extra="forbid")
    segment_id: int
    scene_count: Optional[int] = Field(default=None, ge=0)
    mode: str
    provider: str


class VisualConfigPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    segments: list[VisualSegmentEntry]


class GenerateVisualsResponse(BaseModel):
    task_id: str
    project_slug: str


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

@router.get("/visual-providers")
def get_visual_providers() -> dict:
    """Full registry for the frontend: providers + modes + defaults. One call
    so the UI doesn't have to assemble three endpoints to render a dropdown."""
    return {
        "providers": list_providers(),
        "modes": list_modes(),
        "default_mode": default_mode(),
        "default_provider": default_provider_id(),
    }


# ---------------------------------------------------------------------------
# Per-project config
# ---------------------------------------------------------------------------

@router.get("/projects/{slug}/visual-config")
def get_visual_config(slug: str) -> dict:
    """Return the effective config: saved overrides merged on top of the
    scene_plan-derived skeleton. ``saved`` flag tells the UI whether the user
    has ever explicitly written to this project (vs. running on pure defaults).
    """
    _project_dir(slug)
    saved = load_visual_config(slug)
    effective = resolve_visual_config(slug)
    return {"saved": saved is not None, "config": effective}


@router.put("/projects/{slug}/visual-config")
def update_visual_config(slug: str, payload: VisualConfigPayload) -> dict:
    """Persist a user-edited config. Validates provider/mode strings against
    the registry; an unknown id is a 422. We do NOT cascade-invalidate footage
    here — the per-scene cache sidecars (visual_description hash, prompt hash)
    catch staleness on the next run_visuals call, which preserves cached
    Pexels downloads and Nano Banana images when only some segments changed."""
    _project_dir(slug)

    known_provider_ids = {p["id"] for p in list_providers()}
    known_mode_ids = {m["id"] for m in list_modes()}
    for seg in payload.segments:
        if seg.provider not in known_provider_ids:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown provider: {seg.provider!r}",
            )
        if seg.mode not in known_mode_ids:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown mode: {seg.mode!r}",
            )

    save_visual_config(slug, payload.model_dump(exclude_none=True))
    return {"ok": True, "config": resolve_visual_config(slug)}


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

@router.post("/projects/{slug}/visuals/generate", response_model=GenerateVisualsResponse)
def start_visuals_generate(slug: str) -> GenerateVisualsResponse:
    """Trigger run_visuals.py for this project. Mirrors api.routes.pipeline's
    /visuals route shape (same task_id contract) so the frontend's RunPanel /
    tasks-SSE plumbing works unchanged."""
    _project_dir(slug)
    cmd = [sys.executable, "run_visuals.py", slug]
    task = start_task(
        cmd=cmd,
        cwd=BACKEND_DIR,
        metadata={"kind": "visuals", "project_slug": slug},
    )
    return GenerateVisualsResponse(task_id=task.id, project_slug=slug)


# ---------------------------------------------------------------------------
# Visual-prompt enhancement (status + standalone regenerate + model registry)
# ---------------------------------------------------------------------------

@router.get("/projects/{slug}/visual-prompts")
def get_visual_prompts_status(slug: str) -> dict:
    """File-metadata snapshot. Intentionally does NOT return the prompts —
    the UI only needs to know whether they exist, when they were generated,
    which model, and which source (enhanced vs passthrough). The prompts
    themselves are auto-applied and not user-editable in Phase 1."""
    p = _project_dir(slug)
    prompts_path = p / "visual_prompts.json"
    if not prompts_path.exists():
        return {
            "exists": False,
            "scene_count": 0,
            "generated_at": None,
            "model": None,
            "source": None,
        }
    try:
        with prompts_path.open() as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {
            "exists": False,
            "scene_count": 0,
            "generated_at": None,
            "model": None,
            "source": None,
        }
    mtime = prompts_path.stat().st_mtime
    generated_at = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
    return {
        "exists": True,
        "scene_count": len(payload.get("scenes", [])),
        "generated_at": generated_at,
        "model": payload.get("model"),
        "source": payload.get("source"),
    }


@router.post(
    "/projects/{slug}/visual-prompts/generate",
    response_model=GenerateVisualsResponse,
)
def start_visual_prompts_generate(slug: str) -> GenerateVisualsResponse:
    """Kick off run_visual_prompts.py standalone. Same task-shape contract as
    the visuals route so the frontend can stream logs with the existing
    streamTaskLogs helper."""
    _project_dir(slug)
    cmd = [sys.executable, "run_visual_prompts.py", slug]
    task = start_task(
        cmd=cmd,
        cwd=BACKEND_DIR,
        metadata={"kind": "visual_prompts", "project_slug": slug},
    )
    return GenerateVisualsResponse(task_id=task.id, project_slug=slug)


@router.get("/visual-prompt-models")
def get_visual_prompt_models() -> dict:
    """Model registry passthrough for a future model selector dropdown."""
    registry_path = Path(BACKEND_DIR) / "prompts" / "visual_prompt_models.json"
    if not registry_path.exists():
        raise HTTPException(
            status_code=500,
            detail="visual_prompt_models.json missing from prompts/",
        )
    with registry_path.open() as f:
        return json.load(f)
