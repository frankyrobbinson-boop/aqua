"""Qwen3 local voice provider — STUB. Phase 3 target.

Registered in ``voice_providers.json`` with ``available: false`` so the frontend
dropdown can already render it greyed-out. Calling ``synth_unit`` raises
``NotImplementedError`` with a phase-pointer message — no silent fallthrough.

Future implementation (Phase 3):
    - Run Qwen3-TTS locally via Apple Silicon MLX inference. The community
      port ``kapi2800/qwen3-tts-apple-silicon`` is the current reference
      starting point — wraps MLX with a CLI / Python entrypoint matching
      Qwen's expected interface.
    - Voice clone via ``voice_config["voice_reference_path"]`` (same field
      as the hosted variant, so swapping between the two is purely a
      provider-id flip on the channel preset).
    - Zero per-clip cost; latency depends on local hardware. Best fit for
      bulk re-renders during script iteration where API spend would
      accumulate. Cache key should include the local model checkpoint hash
      so weight updates trigger regeneration.

No env vars needed — runs against local files / models.
"""

from __future__ import annotations

from services.voice_provider import VoiceProvider


class Qwen3LocalProvider(VoiceProvider):
    """Stub provider for local Qwen3-TTS on Apple Silicon. Raises on use."""

    provider_id = "qwen3_local"

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
            "qwen3_local is registered but not yet implemented. Run via local "
            "MLX inference (see kapi2800/qwen3-tts-apple-silicon) — Phase 3 in "
            "the voice-provider roadmap."
        )
