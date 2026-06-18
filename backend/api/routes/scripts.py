"""Script generation: kick off run_script_only.py via the task runner."""

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from api.routes.tasks import start_task
from services.channel_registry import default_channel_id, list_channels
from services.research_service import slugify
from services.video_type_registry import (
    default_type_id,
    list_types,
)


router = APIRouter(tags=["scripts"])


class ScriptRequest(BaseModel):
    topic: str = Field(..., min_length=1, max_length=300)
    target_minutes: int = Field(default=10, ge=1, le=60)
    # If provided, the run will write artifacts to this project folder instead
    # of one derived from the topic. Used for the draft-project flow.
    project_slug: Optional[str] = None
    # Selects the outline/script structure module from video_types.json.
    # None falls back to the registry's default_type at run time.
    video_type: Optional[str] = None
    # ElevenLabs `speed` voice setting (0.8–1.2). 1.0 = native rate.
    voice_speed: Optional[float] = Field(default=None, ge=0.8, le=1.2)
    # If provided, included in the GPT-5 research prompt as a starting point.
    pre_research: Optional[str] = None
    # Wired into both outline + script prompts via {{ADDITIONAL_INSTRUCTIONS}}.
    additional_instructions: Optional[str] = None
    # Wired into the script prompt via {{SAMPLE_SCRIPT}} as a voice reference.
    sample_script: Optional[str] = None
    channel: Optional[str] = None


class ScriptResponse(BaseModel):
    task_id: str
    project_slug: str


def _write_pre_research(backend_dir: Path, project_slug: str, content: Optional[str]) -> None:
    if not content or not content.strip():
        return
    project_dir = backend_dir / ".." / "projects" / project_slug
    project_dir.mkdir(parents=True, exist_ok=True)
    with (project_dir / "pre_research.txt").open("w") as f:
        f.write(content)


def _write_script_config(backend_dir: Path, project_slug: str, req: "ScriptRequest") -> None:
    """Persist video_type + creator steering so run_script_only.py can read it.

    Always writes the file (even when fields are blank) so a re-run uses the
    latest settings and clears any stale ones."""
    project_dir = backend_dir / ".." / "projects" / project_slug
    project_dir.mkdir(parents=True, exist_ok=True)
    config = {
        "channel": req.channel or default_channel_id(),
        "video_type": req.video_type or default_type_id(),
        "additional_instructions": req.additional_instructions,
        "sample_script": req.sample_script,
        "voice_speed": req.voice_speed if req.voice_speed is not None else 1.0,
    }
    # Atomic write so a concurrent reader (the script subprocess) can't see a
    # half-written file. tempfile in same dir → os.replace is atomic on POSIX.
    target = project_dir / "script_config.json"
    fd, tmp = tempfile.mkstemp(prefix=".script_config.", suffix=".tmp", dir=str(project_dir))
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(config, f, indent=2)
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _resolve_slug(req: ScriptRequest) -> str:
    return req.project_slug or slugify(req.topic)


# ---------------------------------------------------------------------------
# Video type registry — exposed for the UI dropdown
# ---------------------------------------------------------------------------

@router.get("/video-types")
def get_video_types() -> dict:
    """Public registry: id, label, description + default_type for the UI."""
    return {"default_type": default_type_id(), "types": list_types()}


@router.get("/channels")
def get_channels() -> dict:
    """Public channel registry: id, name, description + default_channel for the UI.

    Surfaced for when the channel dropdown lands; today's UI doesn't call this
    yet but the data is ready."""
    return {"default_channel": default_channel_id(), "channels": list_channels()}


@router.post("/scripts", response_model=ScriptResponse)
async def create_script(req: ScriptRequest) -> ScriptResponse:
    """Start a script-only generation run."""
    project_slug = _resolve_slug(req)
    backend_dir = Path(__file__).resolve().parent.parent.parent
    _write_pre_research(backend_dir, project_slug, req.pre_research)
    _write_script_config(backend_dir, project_slug, req)

    cmd = [
        sys.executable,
        "run_script_only.py",
        req.topic,
        str(req.target_minutes),
        project_slug,
    ]

    task = start_task(
        cmd=cmd,
        cwd=str(backend_dir),
        metadata={
            "kind": "script",
            "topic": req.topic,
            "target_minutes": req.target_minutes,
            "project_slug": project_slug,
            "pre_research_provided": bool(req.pre_research),
        },
    )
    return ScriptResponse(task_id=task.id, project_slug=project_slug)


@router.post("/pipeline", response_model=ScriptResponse)
async def create_pipeline(req: ScriptRequest) -> ScriptResponse:
    """Start an end-to-end pipeline run: script → voiceover → visuals → render."""
    project_slug = _resolve_slug(req)
    backend_dir = Path(__file__).resolve().parent.parent.parent
    _write_pre_research(backend_dir, project_slug, req.pre_research)
    _write_script_config(backend_dir, project_slug, req)

    cmd = [
        sys.executable,
        "run_full_pipeline.py",
        req.topic,
        str(req.target_minutes),
        project_slug,
    ]

    task = start_task(
        cmd=cmd,
        cwd=str(backend_dir),
        metadata={
            "kind": "pipeline",
            "topic": req.topic,
            "target_minutes": req.target_minutes,
            "project_slug": project_slug,
            "pre_research_provided": bool(req.pre_research),
        },
    )
    return ScriptResponse(task_id=task.id, project_slug=project_slug)
