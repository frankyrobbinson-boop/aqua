"""FastAPI service exposing the Aqua pipeline over HTTP.

Run from backend/:
    uvicorn api.main:app --reload --port 8000
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api.routes import (
    edit,
    pipeline,
    projects,
    remotion,
    scripts,
    tasks,
    visuals,
    voice,
)
from services.channel_migration import run_channel_migration
from services.channel_preset_registry import verify_presets
from services.hook_archetype_registry import verify_archetype_modules_exist
from services.paths import PROJECTS_ROOT
from services.research_service import verify_research_slot
from services.video_type_registry import verify_base_slots, verify_modules_exist
from services.visual_provider_registry import verify_providers_exist
from services.voice_provider_registry import verify_voice_providers_exist

# Channel preset auto-migration runs FIRST — flips legacy
# channels/<id>.md + companion .visuals.json into channels/<id>/{preset.json,
# voice.md}. Idempotent. Must precede the verify guards so they see the new
# layout.
run_channel_migration()

# Fail fast if the prompt bundle is broken — better at boot than mid-run.
verify_modules_exist()
verify_base_slots()
verify_research_slot()
verify_archetype_modules_exist()
verify_providers_exist()
verify_voice_providers_exist()
verify_presets()


app = FastAPI(title="Aqua API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve project artifacts (video, audio, images) for the frontend.
# /files/{slug}/video/final.mp4 → <projects_root>/{slug}/video/final.mp4
if PROJECTS_ROOT.is_dir():
    app.mount("/files", StaticFiles(directory=str(PROJECTS_ROOT)), name="files")

# Serve rendered Remotion MP4s. Scoped to backend/output/remotion/ ONLY — we do
# not expose the rest of output/. Created at boot so the mount has a directory.
remotion.REMOTION_OUT_DIR.mkdir(parents=True, exist_ok=True)
if remotion.REMOTION_OUT_DIR.is_dir():
    app.mount(
        "/remotion-out",
        StaticFiles(directory=str(remotion.REMOTION_OUT_DIR)),
        name="remotion-out",
    )


@app.get("/health")
def health():
    return {"status": "ok"}


app.include_router(projects.router)
app.include_router(scripts.router)
app.include_router(tasks.router)
app.include_router(pipeline.router)
app.include_router(visuals.router)
app.include_router(voice.router)
app.include_router(edit.router)
app.include_router(remotion.router)
