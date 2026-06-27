"""Voice provider registry endpoint.

Routes:
    GET /voice-providers    -> registry dump for future frontend dropdown

Phase 1 only exposes the registry list — segment/unit-level provider routing
analogous to the visual_config flow is a later phase. The per-project
voiceover dispatch entrypoint (POST /voiceover) lives in
``api.routes.pipeline`` and is intentionally not duplicated here.
"""

from __future__ import annotations

from fastapi import APIRouter

from services.voice_provider_registry import (
    default_provider_id,
    list_providers,
)

router = APIRouter(tags=["voice"])


@router.get("/voice-providers")
def get_voice_providers() -> dict:
    """Full registry: providers + default. Mirrors the shape of
    ``GET /visual-providers`` so the frontend can render the dropdown with
    the same component."""
    return {
        "providers": list_providers(),
        "default_provider": default_provider_id(),
    }
