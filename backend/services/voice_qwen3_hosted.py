"""Qwen3 hosted voice provider — STUB. Phase 2a target.

Registered in ``voice_providers.json`` with ``available: false`` so the frontend
dropdown can already render it greyed-out. Calling ``synth_unit`` raises
``NotImplementedError`` with a phase-pointer message — no silent fallthrough.

Future implementation (Phase 2a):
    - Make an HTTP call to either DashScope (Alibaba's official Qwen API) or
      WaveSpeed (independent hosted backend). Both expose Qwen3-TTS with the
      same voice clone capability; final pick depends on latency + price.
    - Use ``voice_config["voice_reference_path"]`` from the channel preset as
      the cloned voice. Upload once per channel, reference by id thereafter.
    - Cost target ~$0.005 per clip (vs ElevenLabs' ~$0.02-$0.05 per clip for
      comparable length), so this becomes the cost-sensitive default once
      voice quality clears the bar.
    - Cache key should include the model version + voice reference id so a
      reference swap on the channel preset invalidates only that channel's
      clips. Reuse ``voice_provider.is_cache_valid`` / ``write_cache``.

Env (future, currently commented in .env.example):
    DASHSCOPE_API_KEY — for the DashScope backend
    WAVESPEED_API_KEY — for the WaveSpeed backend
"""

from __future__ import annotations

from services.voice_provider import VoiceProvider


class Qwen3HostedProvider(VoiceProvider):
    """Stub provider for Qwen3-TTS via DashScope or WaveSpeed. Raises on use."""

    provider_id = "qwen3_hosted"

    def synth_unit(
        self,
        project_name: str,
        unit: dict,
        voice_config: dict,
        voice_speed: float = 1.0,
        previous_text: str = "",
        next_text: str = "",
        previous_request_id: str = "",
    ) -> dict:
        raise NotImplementedError(
            "qwen3_hosted is registered but not yet implemented. Run via API "
            "gateway (DashScope or WaveSpeed) — see Phase 2a in the "
            "voice-provider roadmap."
        )
