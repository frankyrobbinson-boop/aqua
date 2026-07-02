"""Script generation: kick off run_script_only.py via the task runner."""

import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from api.routes.tasks import start_task
from services.paths import PROJECTS_ROOT
from services.channel_preset_registry import (
    create_channel as create_channel_preset,
    load_preset as load_channel_preset,
    save_preset as save_channel_preset,
    get_voice_module as get_channel_voice_module,
    save_voice_module as save_channel_voice_module,
)
from services.channel_registry import (
    default_channel_id,
    list_channel_sections,
    list_channels,
    _resolve as _resolve_channel,
)
from services.hook_archetype_registry import (
    default_archetype_id,
    list_archetypes,
    _resolve as _resolve_archetype,
)
from services.research_service import slugify
from services.video_type_registry import (
    default_type_id,
    list_types,
)


router = APIRouter(tags=["scripts"])

# Matches the draft slug shape created by POST /projects: draft-{epoch}-{4 hex}.
# Anchored so it never matches a legitimate topic-derived slug.
_DRAFT_SLUG_RE = re.compile(r"^draft-\d+-[a-f0-9]+$")


class ScriptRequest(BaseModel):
    topic: str = Field(..., min_length=1, max_length=300)
    target_minutes: int = Field(default=10, ge=1, le=60)
    # If provided, the run writes artifacts into this existing project folder
    # (used to resume a legacy draft-XXXX folder, or to re-run script generation
    # for an existing topic-slug project). When omitted — the canonical path
    # for new creations — the backend derives a unique slug from the topic.
    # Pattern is a superset of the draft-slug shape (draft-{epoch}-{hex}) and
    # the topic-slug shape produced by slugify(), so both kinds round-trip.
    project_slug: Optional[str] = Field(
        default=None,
        pattern=r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$",
        max_length=80,
    )
    # Selects the outline/script type files from video_types.json.
    # Required at generation time — an unset/unknown type fails loudly (no
    # silent default). The UI always sends the dropdown's selected type.
    video_type: Optional[str] = None
    # Number of items per section-list; applies to both video types.
    # None falls back to 5 in the composers.
    item_count: Optional[int] = Field(default=None, ge=3, le=12)
    hook_archetype: Optional[str] = None
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


def _write_pre_research(project_slug: str, content: Optional[str]) -> None:
    if not content or not content.strip():
        return
    project_dir = PROJECTS_ROOT / project_slug
    project_dir.mkdir(parents=True, exist_ok=True)
    with (project_dir / "pre_research.txt").open("w") as f:
        f.write(content)


def _write_script_config(project_slug: str, req: "ScriptRequest") -> None:
    """Persist video_type + creator steering so run_script_only.py can read it.

    Always writes the file (even when fields are blank) so a re-run uses the
    latest settings and clears any stale ones."""
    project_dir = PROJECTS_ROOT / project_slug
    project_dir.mkdir(parents=True, exist_ok=True)
    config = {
        "channel": req.channel or default_channel_id(),
        # No silent default: an unset type flows through as-is and fails loudly
        # at generation time (resolve_modules raises) rather than defaulting.
        "video_type": req.video_type,
        "item_count": req.item_count,
        "additional_instructions": req.additional_instructions,
        "sample_script": req.sample_script,
        "voice_speed": req.voice_speed if req.voice_speed is not None else 1.0,
        "hook_archetype": req.hook_archetype,
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


def _derive_unique_slug(topic: str, projects_root: Path) -> str:
    """Slugify ``topic`` and append -2, -3, ... until the candidate doesn't
    collide with an existing project directory. Used by the unified creation
    flow (no draft folder pre-allocated) so the first write to disk happens
    under the final slug."""
    base = slugify(topic)
    candidate = base
    n = 2
    while (projects_root / candidate).exists():
        candidate = f"{base}-{n}"
        n += 1
    return candidate


def _resolve_slug(req: ScriptRequest) -> str:
    return req.project_slug or slugify(req.topic)


def _migrate_draft_slug(req: ScriptRequest) -> str:
    """If `req.project_slug` is a draft slug from POST /projects, rename its
    folder to the topic-derived slug and return the new slug. Otherwise return
    `_resolve_slug(req)` unchanged.

    Collisions with an existing non-draft project are resolved by suffixing
    -2, -3, ... — the renamed folder never overwrites another project."""
    slug = _resolve_slug(req)
    if req.project_slug is None or not _DRAFT_SLUG_RE.match(req.project_slug):
        return slug

    desired = slugify(req.topic)  # raises ValueError on empty topic
    if desired == req.project_slug:
        return desired  # defensive: a topic happened to look like the draft

    src = PROJECTS_ROOT / req.project_slug
    if not src.is_dir():
        # Draft folder vanished (e.g. user deleted it elsewhere). Bail to the
        # topic slug so subsequent writes still land somewhere sensible.
        return desired

    # Pick a unique target. Collisions only happen if the same topic was used
    # before; suffix until free.
    target = PROJECTS_ROOT / desired
    if target.exists():
        n = 2
        while (PROJECTS_ROOT / f"{desired}-{n}").exists():
            n += 1
        desired = f"{desired}-{n}"
        target = PROJECTS_ROOT / desired

    shutil.move(str(src), str(target))
    return desired


def _validate_hook_archetype(archetype_id: Optional[str]) -> None:
    """Fail loud with 400 if a per-video override doesn't exist in the registry."""
    if archetype_id is None:
        return
    try:
        _resolve_archetype(archetype_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


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


@router.get("/channels/{channel_id}")
def get_channel_detail(channel_id: str) -> dict:
    """Read-only detail view of a channel for the /channels/[id] UI page.

    Returns id/name/description (from channels.json), the preferred hook
    archetype + its human label, and ALL `## ` sections of the channel module
    body as {heading: body_text}. Future channel fields and new sections
    surface here automatically."""
    try:
        c = _resolve_channel(channel_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    pref_id = c.get("preferred_hook_archetype")
    pref_label: Optional[str] = None
    if pref_id:
        try:
            pref_label = _resolve_archetype(pref_id)["label"]
        except ValueError:
            pref_label = None  # boot guards normally prevent this; stay defensive

    return {
        "id": c["id"],
        "name": c["name"],
        "description": c["description"],
        "preferred_hook_archetype": pref_id,
        "preferred_hook_archetype_label": pref_label,
        "sections": list_channel_sections(channel_id),
    }


@router.get("/hook-archetypes")
def get_hook_archetypes() -> dict:
    """Public hook-archetype registry: id, label, description + default_archetype."""
    return {"default_archetype": default_archetype_id(), "archetypes": list_archetypes()}


# ---------------------------------------------------------------------------
# Channel preset editor — Phase 3b
# ---------------------------------------------------------------------------
#
# Read/write surface for the structured preset.json + voice.md content. The
# legacy ``GET /channels/{id}`` above (markdown sections) stays as-is for
# dropdown consumers; this block adds the editor's read/write endpoints.


class CharacterPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: Optional[bool] = None
    image_path: Optional[str] = None
    strength: Optional[float] = Field(default=None, ge=0.0, le=1.0)


class VisualsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    style_description: Optional[str] = None
    reference_image_paths: Optional[list[str]] = None
    character: Optional[CharacterPatch] = None
    creative_direction: Optional[str] = None
    image_prompt_model: Optional[str] = None


class ChannelPresetPatch(BaseModel):
    """Partial-update payload. Every field optional so the editor can PUT a
    single changed knob; the registry's ``save_preset`` deep-merges into the
    existing JSON. Unknown top-level keys are rejected here (extra=forbid) —
    forward-compat sections (script/voiceover/render) will land via explicit
    model fields when 3c+ wires them up."""

    model_config = ConfigDict(extra="forbid")
    label: Optional[str] = None
    description: Optional[str] = None
    color: Optional[str] = None
    preferred_hook_archetype: Optional[str] = None
    visuals: Optional[VisualsPatch] = None


class ChannelVoicePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str


def _load_visual_prompt_model_ids() -> set[str]:
    """Read ``prompts/visual_prompt_models.json`` and return the set of valid
    model ids. Path is resolved relative to backend/ so it works regardless
    of where uvicorn was launched."""
    backend_dir = Path(__file__).resolve().parent.parent.parent
    path = backend_dir / "prompts" / "visual_prompt_models.json"
    if not path.exists():
        return set()
    with path.open() as f:
        data = json.load(f)
    return {m["id"] for m in data.get("models", [])}


@router.get("/channels/{channel_id}/preset")
def get_channel_preset(channel_id: str) -> dict:
    """Full preset.json for the editor. Single source of truth for the
    /channels/[id] page (identity + visuals + future sections)."""
    try:
        return load_channel_preset(channel_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/channels/{channel_id}/preset")
def update_channel_preset(channel_id: str, payload: ChannelPresetPatch) -> dict:
    """Deep-merge ``payload`` into the channel's preset.json and atomically
    write. Returns the merged preset.

    Cross-field validation (registry membership):
      - ``preferred_hook_archetype`` must resolve in hook_archetype_registry.
      - ``visuals.image_prompt_model`` must be a known model id.
    Scalar-range checks (strength 0-1) are handled by the Pydantic model."""
    try:
        load_channel_preset(channel_id)  # validates channel id exists
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    if payload.preferred_hook_archetype is not None:
        try:
            _resolve_archetype(payload.preferred_hook_archetype)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))

    if payload.visuals is not None and payload.visuals.image_prompt_model is not None:
        known = _load_visual_prompt_model_ids()
        if known and payload.visuals.image_prompt_model not in known:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Unknown image_prompt_model: "
                    f"{payload.visuals.image_prompt_model!r}"
                ),
            )

    partial = payload.model_dump(exclude_none=True)
    save_channel_preset(channel_id, partial)
    return load_channel_preset(channel_id)


@router.get("/channels/{channel_id}/voice")
def get_channel_voice(channel_id: str) -> dict:
    """Raw markdown content of ``channels/<id>/voice.md`` for the editor."""
    try:
        content = get_channel_voice_module(channel_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"content": content}


@router.put("/channels/{channel_id}/voice")
def update_channel_voice(channel_id: str, payload: ChannelVoicePayload) -> dict:
    """Atomic write of voice.md content."""
    try:
        save_channel_voice_module(channel_id, payload.content)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"ok": True}


# ---------------------------------------------------------------------------
# Channel creation wizard — Phase 3c
# ---------------------------------------------------------------------------


class ChannelCreatePayload(BaseModel):
    """Body for ``POST /channels``. The id regex mirrors the slug check in
    ``channel_preset_registry.create_channel`` so a 422 from Pydantic catches
    bad slugs before the service layer runs; the service still validates as a
    second line of defense."""

    model_config = ConfigDict(extra="forbid")
    id: str = Field(..., min_length=3, max_length=40, pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
    label: str = Field(..., min_length=1, max_length=80)
    description: str = Field(default="", max_length=500)
    color: str = Field(..., pattern=r"^#[0-9a-fA-F]{6}$")
    preferred_hook_archetype: Optional[str] = None
    voice_content: str = Field(..., min_length=1)
    visuals: Optional[VisualsPatch] = None


@router.post("/channels")
def create_channel(payload: ChannelCreatePayload) -> dict:
    """Create a new channel directory + preset.json + voice.md and register it
    in channels.json. Returns the created preset (same shape as
    ``GET /channels/{id}/preset``).

    Validation order: Pydantic body shape → cross-registry checks
    (hook_archetype + image_prompt_model) → service-layer id-collision check.
    Returns 409 on id collision (typed differently from 422 so the wizard can
    surface a targeted inline error)."""

    if payload.preferred_hook_archetype is not None:
        try:
            _resolve_archetype(payload.preferred_hook_archetype)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))

    if payload.visuals is not None and payload.visuals.image_prompt_model is not None:
        known = _load_visual_prompt_model_ids()
        if known and payload.visuals.image_prompt_model not in known:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Unknown image_prompt_model: "
                    f"{payload.visuals.image_prompt_model!r}"
                ),
            )

    preset_input = {
        "label": payload.label,
        "description": payload.description,
        "color": payload.color,
        "preferred_hook_archetype": payload.preferred_hook_archetype,
    }
    if payload.visuals is not None:
        preset_input["visuals"] = payload.visuals.model_dump(exclude_none=True)

    try:
        create_channel_preset(payload.id, preset_input, payload.voice_content)
    except ValueError as e:
        msg = str(e)
        # Service raises ValueError for both id-collision and slug-shape. The
        # latter shouldn't happen here (Pydantic catches it first) but we map
        # collision -> 409 and everything else -> 422.
        if "already exists" in msg:
            raise HTTPException(status_code=409, detail=msg)
        raise HTTPException(status_code=422, detail=msg)

    return load_channel_preset(payload.id)


@router.post("/scripts", response_model=ScriptResponse)
async def create_script(req: ScriptRequest) -> ScriptResponse:
    """Start a script-only generation run."""
    _validate_hook_archetype(req.hook_archetype)
    if req.project_slug:
        # Existing draft slug or existing project — keep the migration path so
        # legacy draft-XXXX folders still rename to their topic slug.
        project_slug = _migrate_draft_slug(req)
    else:
        # Unified creation flow: no folder pre-allocated; derive a unique slug
        # straight from the topic. Collisions append -2, -3, ...
        project_slug = _derive_unique_slug(req.topic, PROJECTS_ROOT)
    backend_dir = Path(__file__).resolve().parent.parent.parent
    _write_pre_research(project_slug, req.pre_research)
    _write_script_config(project_slug, req)

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
        kind="script",
        project_slug=project_slug,
    )
    return ScriptResponse(task_id=task.id, project_slug=project_slug)


@router.post("/pipeline", response_model=ScriptResponse)
async def create_pipeline(req: ScriptRequest) -> ScriptResponse:
    """Start an end-to-end pipeline run: script → voiceover → visuals → render."""
    _validate_hook_archetype(req.hook_archetype)
    if req.project_slug:
        project_slug = _migrate_draft_slug(req)
    else:
        project_slug = _derive_unique_slug(req.topic, PROJECTS_ROOT)
    backend_dir = Path(__file__).resolve().parent.parent.parent
    _write_pre_research(project_slug, req.pre_research)
    _write_script_config(project_slug, req)

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
        kind="pipeline",
        project_slug=project_slug,
    )
    return ScriptResponse(task_id=task.id, project_slug=project_slug)
