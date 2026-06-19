"""FastAPI service exposing the Aqua pipeline over HTTP.

Run from backend/:
    uvicorn api.main:app --reload --port 8000
"""

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api.routes import pipeline, projects, scripts, tasks
from services.hook_archetype_registry import (
    verify_archetype_modules_exist,
    verify_hook_slot,
)
from services.research_service import verify_research_slot
from services.video_type_registry import verify_base_slots, verify_modules_exist

# Fail fast if the prompt bundle is broken — better at boot than mid-run.
verify_modules_exist()
verify_base_slots()
verify_research_slot()
verify_archetype_modules_exist()
verify_hook_slot()


app = FastAPI(title="Aqua API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve project artifacts (video, audio, images) for the frontend.
# /files/{slug}/video/final.mp4 → ../projects/{slug}/video/final.mp4
PROJECTS_ROOT = os.path.abspath("../projects")
if os.path.isdir(PROJECTS_ROOT):
    app.mount("/files", StaticFiles(directory=PROJECTS_ROOT), name="files")


@app.get("/health")
def health():
    return {"status": "ok"}


app.include_router(projects.router)
app.include_router(scripts.router)
app.include_router(tasks.router)
app.include_router(pipeline.router)
