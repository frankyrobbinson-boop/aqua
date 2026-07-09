"""Project listing and detail endpoints. Reads from the canonical projects root."""

import json
import shutil
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from services import cost_ledger
from services.paths import PROJECTS_ROOT
from services.stage_graph import invalidate_dependents


router = APIRouter(prefix="/projects", tags=["projects"])


def _project_dir(slug: str) -> Path:
    # Defensive: slug must be a simple name, not a path traversal.
    if "/" in slug or ".." in slug or slug.startswith("."):
        raise HTTPException(status_code=400, detail=f"Invalid project slug: {slug!r}")
    p = PROJECTS_ROOT / slug
    if not p.is_dir():
        raise HTTPException(status_code=404, detail=f"Project not found: {slug}")
    return p


def _load_json(path: Path) -> Any | None:
    if not path.exists():
        return None
    try:
        with path.open() as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _project_summary(slug: str, p: Path) -> dict:
    script_path = p / "script_draft.json"
    timeline_path = p / "audio_timeline.json"
    audio_dir = p / "audio"
    final_video = p / "video" / "final.mp4"

    script = _load_json(script_path)
    title = (script or {}).get("title") or slug.replace("-", " ").title()

    has_script = script_path.exists()
    has_audio = (
        timeline_path.exists()
        and audio_dir.is_dir()
        and any(audio_dir.iterdir())
    )
    has_video = final_video.exists()

    # modified_at: max mtime over a small fixed set of indicator paths instead
    # of rglob'ing the entire project. A rendered video can have hundreds of
    # files (footage/, clips/, video/) — recursing them on every /projects call
    # was an O(file count) stat avalanche that scaled with rendered output.
    # These four cover every meaningful "last change" the listing UI cares about.
    candidates = [p, script_path, timeline_path, final_video]
    mtimes: list[float] = []
    for c in candidates:
        try:
            mtimes.append(c.stat().st_mtime)
        except OSError:
            pass
    modified_at = max(mtimes) if mtimes else 0.0

    return {
        "slug": slug,
        "title": title,
        "has_script": has_script,
        "has_audio": has_audio,
        "has_video": has_video,
        "modified_at": modified_at,
    }


@router.get("")
def list_projects() -> list[dict]:
    if not PROJECTS_ROOT.is_dir():
        return []
    out = []
    for child in PROJECTS_ROOT.iterdir():
        if not child.is_dir() or child.name.startswith("."):
            continue
        out.append(_project_summary(child.name, child))
    out.sort(key=lambda r: r["modified_at"], reverse=True)
    return out


@router.get("/{slug}")
def get_project(slug: str) -> dict:
    p = _project_dir(slug)
    summary = _project_summary(slug, p)
    return {
        **summary,
        "research": _load_json(p / "research.json"),
        "outline": _load_json(p / "outline.json"),
        "script_draft": _load_json(p / "script_draft.json"),
        "tts_script": _load_json(p / "tts_script.json"),
        "scene_plan": _load_json(p / "scene_plan.json"),
        "audio_timeline": _load_json(p / "audio_timeline.json"),
        "scene_windows": _load_json(p / "scene_windows.json"),
    }


@router.delete("/{slug}")
def delete_project(slug: str) -> dict:
    p = _project_dir(slug)
    shutil.rmtree(p)
    return {"slug": slug, "deleted": True}


@router.get("/{slug}/cost")
def get_project_cost(slug: str) -> dict:
    # _project_dir validates existence; cost_ledger.total handles missing file.
    _project_dir(slug)
    return cost_ledger.total(slug)


# Cascade-invalidation is delegated to services.stage_graph. The graph knows
# which stages consume which artifacts and which outputs to delete; content-
# keyed caches (audio/, footage/, clips/) are preserved across cascades to
# avoid re-billing ElevenLabs and re-downloading Pexels footage that the
# per-item sidecar logic will validate on the next run anyway.


# ---------------------------------------------------------------------------
# Script payload validation
#
# The shape here mirrors SCRIPT_SCHEMA in services/script_draft_service.py.
# Using Pydantic instead of jsonschema gives us FastAPI's auto-422 on bad
# payloads + typed access in the handler. Keep in sync with SCRIPT_SCHEMA.
# ---------------------------------------------------------------------------

class _HookPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    narration: str


class _SegmentPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    narration: str
    visual_notes: str


class _ConclusionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    narration: str


class ScriptDraftPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    # title_spoken + item_noun default to "" so editor saves of scripts that
    # carry them (every script generated since those fields were added) don't
    # trip extra="forbid" with a 422; both mirror SCRIPT_SCHEMA.
    title_spoken: str = ""
    item_noun: str = ""
    hook: _HookPayload
    segments: list[_SegmentPayload]
    conclusion: _ConclusionPayload


@router.put("/{slug}/script")
def update_script(slug: str, payload: ScriptDraftPayload) -> dict:
    """Overwrite script_draft.json with edited content. The voiceover, scenes,
    and rendered video all depend on the script — they're deleted here so the
    next downstream-stage run regenerates against the new script instead of
    silently reusing stale content.

    The payload is validated against ScriptDraftPayload (mirrors SCRIPT_SCHEMA
    in script_draft_service.py). Malformed inputs are rejected with 422 BEFORE
    the cascade runs, so a bad edit can't take the project's downstream
    artifacts with it."""
    p = _project_dir(slug)
    with (p / "script_draft.json").open("w") as f:
        json.dump(payload.model_dump(), f, indent=2)
    invalidated = invalidate_dependents(str(p), "script_draft.json")
    return {"ok": True, "invalidated": invalidated}
