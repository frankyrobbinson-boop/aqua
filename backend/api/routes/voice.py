"""Voice provider registry endpoint + per-channel preview synthesis.

Routes:
    GET  /voice-providers                       -> registry dump for future frontend dropdown
    POST /channels/{channel_id}/voice-preview   -> one-shot preview MP3

Phase 1 only exposes the registry list — segment/unit-level provider routing
analogous to the visual_config flow is a later phase. The per-project
voiceover dispatch entrypoint (POST /voiceover) lives in
``api.routes.pipeline`` and is intentionally not duplicated here.
"""

from __future__ import annotations

import os
from io import BytesIO
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from services.channel_registry import resolve_channel_voiceover, _resolve as _resolve_channel
from services.voice_elevenlabs import synth_preview
from services.voice_provider_registry import (
    default_provider_id,
    list_providers,
)

router = APIRouter(tags=["voice"])

_DEFAULT_PREVIEW_TEXT = "Hello, this is a quick preview of how the voice sounds."


@router.get("/voice-providers")
def get_voice_providers() -> dict:
    """Full registry: providers + default. Mirrors the shape of
    ``GET /visual-providers`` so the frontend can render the dropdown with
    the same component."""
    return {
        "providers": list_providers(),
        "default_provider": default_provider_id(),
    }


class VoicePreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: Optional[str] = None
    voice_speed: float = Field(default=1.0, ge=0.5, le=2.0)
    voice_config_override: Optional[dict] = None


@router.post("/channels/{channel_id}/voice-preview")
def preview_channel_voice(channel_id: str, payload: VoicePreviewRequest) -> StreamingResponse:
    """Synthesize a short preview clip with the channel's voice settings.

    Shallow-merges ``voice_config_override`` on top of the channel's resolved
    voiceover config so the editor can A/B a setting without persisting it.
    The ``settings`` sub-dict is also shallow-merged so a partial override
    (e.g. ``{"settings": {"speed": 1.1}}``) keeps the channel's other voice
    settings intact."""
    try:
        _resolve_channel(channel_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    if not os.getenv("ELEVENLABS_API_KEY"):
        raise HTTPException(
            status_code=503,
            detail="ELEVENLABS_API_KEY not set on the server",
        )

    voice_config = resolve_channel_voiceover(channel_id)
    override = payload.voice_config_override or {}
    merged: dict = dict(voice_config)
    for k, v in override.items():
        if k == "settings" and isinstance(v, dict) and isinstance(voice_config.get("settings"), dict):
            merged_settings = dict(voice_config["settings"])
            merged_settings.update(v)
            merged["settings"] = merged_settings
        else:
            merged[k] = v

    text = (payload.text or "").strip() or _DEFAULT_PREVIEW_TEXT

    try:
        audio_bytes = synth_preview(text, merged, voice_speed=payload.voice_speed)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"ElevenLabs preview failed: {exc!r}")

    return StreamingResponse(BytesIO(audio_bytes), media_type="audio/mpeg")
