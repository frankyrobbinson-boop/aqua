"""Voiceover, visuals, and render: each kicks off the matching pipeline script
via the task runner and returns a task_id for SSE log streaming."""

import asyncio
import json
import os
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.routes.tasks import start_task
from services.paths import PROJECTS_ROOT
from services.visual_config_service import resolve_visual_config


router = APIRouter(tags=["pipeline"])

# Per-slug locks for read-modify-write on script_config.json. Two concurrent
# /voiceover calls for the same slug would otherwise race the file.
_config_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

# File-anchored paths so the API works no matter where uvicorn was launched.
_HERE = Path(__file__).resolve()
BACKEND_DIR = str(_HERE.parent.parent.parent)


class ProjectStageRequest(BaseModel):
    project_slug: str
    # Optional override for the voiceover stage. When present, patches
    # script_config.json before kicking off run_audio.
    voice_speed: Optional[float] = None


class RenderRequest(ProjectStageRequest):
    # Per-render options consumed by run_render.py via env vars. Not
    # persisted to project state — user picks at render time.
    ken_burns: Optional[bool] = Field(default=False)
    # Section cards + EDL-driven section transitions default ON. run_render.py
    # reads each as a kill-switch: "0" = off, anything else / unset = EDL-driven.
    render_section_cards: bool = True
    render_section_transitions: bool = True


class StageResponse(BaseModel):
    task_id: str
    project_slug: str


def _check_project(slug: str) -> Path:
    if "/" in slug or ".." in slug or slug.startswith("."):
        raise HTTPException(status_code=400, detail=f"Invalid project slug: {slug!r}")
    p = PROJECTS_ROOT / slug
    if not p.is_dir():
        raise HTTPException(status_code=404, detail=f"Project not found: {slug}")
    return p


def _start_stage(
    script: str,
    slug: str,
    stage: str,
    env: dict[str, str] | None = None,
) -> StageResponse:
    cmd = [sys.executable, script, slug]
    task = start_task(
        cmd=cmd,
        cwd=BACKEND_DIR,
        metadata={"kind": stage, "project_slug": slug},
        env_overrides=env,
        kind=stage,
        project_slug=slug,
    )
    return StageResponse(task_id=task.id, project_slug=slug)


def _patch_script_config(slug: str, updates: dict) -> None:
    """Read script_config.json, apply updates, write back atomically. Skips
    silently if the file doesn't exist (a voiceover called before script
    generation would fail anyway in _check_inputs)."""
    p = PROJECTS_ROOT / slug / "script_config.json"
    if not p.exists():
        return
    try:
        with p.open() as f:
            cfg = json.load(f)
    except (OSError, json.JSONDecodeError):
        cfg = {}
    cfg.update({k: v for k, v in updates.items() if v is not None})
    # Atomic write: tempfile in same dir, then os.replace. Prevents partial-
    # read tearing if another process (the script subprocess) reads concurrently.
    fd, tmp = tempfile.mkstemp(prefix=".script_config.", suffix=".tmp", dir=str(p.parent))
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(cfg, f, indent=2)
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


@router.post("/voiceover", response_model=StageResponse)
async def start_voiceover(req: ProjectStageRequest) -> StageResponse:
    _check_project(req.project_slug)
    if req.voice_speed is not None:
        async with _config_locks[req.project_slug]:
            _patch_script_config(req.project_slug, {"voice_speed": req.voice_speed})
    return _start_stage("run_audio.py", req.project_slug, "voiceover")


@router.post("/visuals", response_model=StageResponse)
async def start_visuals(req: ProjectStageRequest) -> StageResponse:
    _check_project(req.project_slug)
    return _start_stage("run_visuals.py", req.project_slug, "visuals")


@router.post("/render", response_model=StageResponse)
async def start_render(req: RenderRequest) -> StageResponse:
    _check_project(req.project_slug)
    env = {
        "RENDER_KEN_BURNS": "1" if req.ken_burns else "0",
        "RENDER_SECTION_CARDS": "1" if req.render_section_cards else "0",
        "RENDER_SECTION_TRANSITIONS": "1" if req.render_section_transitions else "0",
    }
    return _start_stage("run_render.py", req.project_slug, "render", env=env)


class SceneInfo(BaseModel):
    id: int
    segment_id: int
    narration: str
    visual_description: str
    # Effective per-scene visual mode: a per-scene override (mixed segments)
    # wins, then the scene-plan tag, then falls back to the segment's mode.
    visual_mode: Optional[str] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    duration: Optional[float] = None
    has_footage: bool
    footage_url: Optional[str] = None


@router.get("/projects/{slug}/scenes", response_model=list[SceneInfo])
def get_scenes(slug: str) -> list[SceneInfo]:
    """Per-scene info for the visuals UI: narration, query used, footage status."""
    p = _check_project(slug)

    # Prefer scene_windows.json (has timing info). Fall back to scene_plan.json.
    scenes_data: list[dict] = []
    sw_path = p / "scene_windows.json"
    if sw_path.exists():
        with sw_path.open() as f:
            scenes_data = json.load(f)
    else:
        sp_path = p / "scene_plan.json"
        if not sp_path.exists():
            return []
        with sp_path.open() as f:
            scenes_data = json.load(f).get("scene_intent", [])

    # Resolve config once to compute each scene's EFFECTIVE visual mode. For a
    # "mixed" segment that's override -> scene tag -> "stock_video"; for any
    # other segment it's just the segment mode. Best-effort: if config can't be
    # resolved (no scene_plan yet) fall back to the raw scene tag.
    try:
        config = resolve_visual_config(slug)
    except Exception:
        config = {"segments": [], "scene_overrides": {}}
    config_by_seg = {
        int(s["segment_id"]): s for s in config.get("segments", [])
    }
    scene_overrides = config.get("scene_overrides") or {}

    def _effective_mode(scene: dict) -> Optional[str]:
        seg = scene.get("segment_id")
        entry = config_by_seg.get(int(seg)) if seg is not None else None
        if entry is None:
            return scene.get("visual_mode")
        if entry.get("mode") != "mixed":
            return entry.get("mode")
        eff = scene_overrides.get(str(scene.get("id"))) or scene.get("visual_mode")
        return eff if eff in ("stock_video", "ai_image") else "stock_video"

    footage_dir = p / "footage"
    result: list[SceneInfo] = []
    for scene in scenes_data:
        sid = scene["id"]
        # Footage can be MP4 (Pexels stock) or PNG (Nano Banana / AI image
        # providers). Check both extensions; .png wins if both exist (newer
        # AI providers running on top of an old Pexels-generated project).
        ext = None
        for candidate_ext in (".png", ".mp4"):
            candidate = footage_dir / f"scene_{sid:03d}{candidate_ext}"
            if candidate.exists() and candidate.stat().st_size > 0:
                ext = candidate_ext
                break
        has_footage = ext is not None
        result.append(
            SceneInfo(
                id=sid,
                segment_id=int(scene.get("segment_id", 0)),
                narration=scene.get("narration", ""),
                visual_description=scene.get("visual_description", ""),
                visual_mode=_effective_mode(scene),
                start_time=scene.get("start_time"),
                end_time=scene.get("end_time"),
                duration=scene.get("duration"),
                has_footage=has_footage,
                footage_url=(
                    f"/files/{slug}/footage/scene_{sid:03d}{ext}"
                    if has_footage
                    else None
                ),
            )
        )
    return result
