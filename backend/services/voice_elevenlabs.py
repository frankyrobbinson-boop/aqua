"""ElevenLabs voice provider conforming to the VoiceProvider interface.

Wraps the existing ElevenLabs SDK call + word-alignment + trailing-trim logic
that used to live inline in ``voice_service``. Behavior matches the pre-refactor
``voice_service._generate_unit`` one-for-one:

  - Uses ``with_raw_response.convert_with_timestamps`` to capture request_id
    for prosody stitching across chunks in the same segment
  - Per-chunk seed override (unit["seed"]) honored
  - Character-level alignment aggregated to word-level timestamps; SSML tag
    characters skipped
  - Cache sidecar at ``audio_<id:02d>_<type>.json`` keyed by tts_source +
    seed + voice_speed (NO voice_id / model / settings in the key — those are
    process-level and a change implies wanting a full re-run; matches today)
  - afinfo trailing-silence tripwire kept (macOS-only, silent elsewhere)

The provider reads voice_id / model / settings primarily from ``voice_config``
(the channel-preset-aware flat schema) and falls back to env vars when the
config has no value set — preserves the current ``ELEVENLABS_VOICE_ID``
override path for ad-hoc tweaks.
"""

from __future__ import annotations

import base64
import json
import os
from typing import Any

from dotenv import load_dotenv
from elevenlabs import VoiceSettings
from elevenlabs.client import ElevenLabs

from services import cost_ledger
from services.voice_provider import (
    VoiceProvider,
    audio_dir_for,
    is_cache_valid,
    read_cache,
    write_cache,
)

load_dotenv()

# Default voice id matches the legacy hardcoded fallback ("George") so projects
# generated before the channel preset gains a voiceover block keep their voice.
_DEFAULT_VOICE_ID = "JBFqnCBsd6RMkjVDRZzb"
_DEFAULT_MODEL_ID = "eleven_multilingual_v2"

# Fixed across every chunk so prosody stays consistent throughout the video.
_SEED = 42

# ElevenLabs `speed` accepts ~0.7–1.2; clamp to a safer 0.8–1.2 range and treat
# anything else as 1.0 to avoid request rejections.
_SPEED_MIN, _SPEED_MAX = 0.8, 1.2


def _build_voice_settings(speed: float, overrides: dict | None) -> VoiceSettings:
    """Build a VoiceSettings honoring channel-preset overrides where present
    and falling back to the legacy fixed values (stability 0.5,
    similarity_boost 0.75, style 0.0, use_speaker_boost True) otherwise.
    Speed is clamped to ElevenLabs' supported range."""
    speed = max(_SPEED_MIN, min(_SPEED_MAX, float(speed)))
    overrides = overrides or {}
    return VoiceSettings(
        stability=float(overrides.get("stability", 0.5)),
        similarity_boost=float(overrides.get("similarity_boost", 0.75)),
        style=float(overrides.get("style", 0.0)),
        use_speaker_boost=bool(overrides.get("use_speaker_boost", True)),
        speed=speed,
    )


def _chars_to_words(characters: list, start_times: list, end_times: list) -> list:
    """Aggregate character-level alignment to word-level timestamps (seconds).
    Characters inside SSML tags (<...>) are skipped entirely."""
    words = []
    current_word = ""
    word_start = None
    in_tag = False

    for i, char in enumerate(characters):
        if char == "<":
            in_tag = True
            if current_word:
                words.append({
                    "word": current_word,
                    "start": round(word_start, 3),
                    "end": round(end_times[i - 1], 3)
                })
                current_word = ""
                word_start = None
        elif char == ">":
            in_tag = False
        elif in_tag:
            pass
        elif char in (" ", "\n"):
            if current_word:
                words.append({
                    "word": current_word,
                    "start": round(word_start, 3),
                    "end": round(end_times[i - 1], 3)
                })
                current_word = ""
                word_start = None
        else:
            if not current_word:
                word_start = start_times[i]
            current_word += char

    if current_word:
        words.append({
            "word": current_word,
            "start": round(word_start, 3),
            "end": round(end_times[-1], 3)
        })

    return words


class ElevenLabsProvider(VoiceProvider):
    """ElevenLabs SDK-backed voice provider. Stateless across units — the
    request-id chaining for prosody continuity is threaded through the
    orchestrator's per-segment loop, not stored on the instance."""

    provider_id = "elevenlabs"

    def __init__(self, client: ElevenLabs | None = None):
        # Lazy default so importing the module without ELEVENLABS_API_KEY set
        # doesn't blow up — the registry constructs providers eagerly at boot
        # via verify_providers_exist's instance cache, and we don't want that
        # to require credentials.
        self._client = client
        self._api_key = os.getenv("ELEVENLABS_API_KEY")

    def _get_client(self) -> ElevenLabs:
        if self._client is None:
            self._client = ElevenLabs(api_key=self._api_key)
        return self._client

    def _resolve_voice_id(self, voice_config: dict) -> str:
        """Channel preset > env override > built-in default. Mirrors the
        existing precedence: explicit preset wins, env still works as a quick
        knob, default is George."""
        return (
            voice_config.get("voice_id")
            or os.getenv("ELEVENLABS_VOICE_ID")
            or _DEFAULT_VOICE_ID
        )

    def _resolve_model_id(self, voice_config: dict) -> str:
        return (
            voice_config.get("model")
            or os.getenv("ELEVENLABS_MODEL_ID")
            or _DEFAULT_MODEL_ID
        )

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
        audio_dir = audio_dir_for(project_name)
        filename = f"audio_{unit['id']:02d}_{unit['type']}.mp3"
        filepath = audio_dir / filename

        tts_text = unit.get("ssml", unit["text"])
        seed = unit.get("seed", _SEED)

        # Cache key: tts_source + seed + voice_speed (same as legacy). Voice id
        # / model / settings changes intentionally do NOT invalidate per-unit
        # cache here — a global re-render is the right response to that, and
        # forcing it would auto-burn credits on every channel-preset tweak.
        expected = {
            "tts_source": tts_text,
            "seed": seed,
            "voice_speed": voice_speed,
        }
        if is_cache_valid(filepath, expected):
            cached = read_cache(filepath)
            if cached is not None:
                return cached

        voice_id = self._resolve_voice_id(voice_config)
        model_id = self._resolve_model_id(voice_config)
        settings = _build_voice_settings(voice_speed, voice_config.get("settings"))

        kwargs: dict[str, Any] = dict(
            voice_id=voice_id,
            text=tts_text,
            model_id=model_id,
            output_format="mp3_44100_128",
            apply_text_normalization="off",
            previous_text=previous_text,
            next_text=next_text,
            seed=seed,
            voice_settings=settings,
        )
        if previous_request_id:
            kwargs["previous_request_ids"] = [previous_request_id]

        client = self._get_client()

        # Use with_raw_response to capture the request ID for subsequent stitching
        request_id = ""
        try:
            raw = client.text_to_speech.with_raw_response.convert_with_timestamps(**kwargs)
            request_id = raw.headers.get("request-id") or raw.headers.get("x-request-id") or ""
            response = raw.data
        except Exception as exc:
            print(f"  WARNING: with_raw_response failed for {unit['title']!r} ({exc!r}); "
                  f"retrying without request_id — prosody stitching disabled for this chunk")
            response = client.text_to_speech.convert_with_timestamps(**kwargs)

        audio_bytes = base64.b64decode(response.audio_base_64)
        with open(filepath, "wb") as f:
            f.write(audio_bytes)

        alignment = response.alignment
        words = _chars_to_words(
            alignment.characters,
            alignment.character_start_times_seconds,
            alignment.character_end_times_seconds,
        )

        duration = round(alignment.character_end_times_seconds[-1], 3)

        # Tripwire: warn if the file has more than 1s of trailing silence beyond the last spoken word.
        # Causes: bad break tags (e.g. time="zero.7s"), breaks at chunk edges, prompt regressions.
        # Uses afinfo (macOS) for real VBR duration; skips silently on other platforms.
        speech_end = words[-1]["end"] if words else duration
        try:
            import subprocess
            import re as _re
            out = subprocess.check_output(
                ["afinfo", str(filepath)],
                stderr=subprocess.STDOUT,
            ).decode()
            m = _re.search(r"estimated duration: ([\d.]+)", out)
            if m:
                file_duration = float(m.group(1))
                if file_duration - speech_end > 1.0:
                    print(f"  WARNING [{unit['title']}]: {file_duration - speech_end:.1f}s trailing silence "
                          f"(speech {speech_end:.1f}s, file {file_duration:.1f}s) — check break tags")
        except Exception:
            pass

        result = {
            "segment_id": unit["id"],
            "type": unit["type"],
            "title": unit["title"],
            "text": unit["text"],
            "audio_file": filename,
            "duration": duration,
            "words": words,
            "tts_source": tts_text,
            "seed": seed,
            "voice_speed": voice_speed,
            "request_id": request_id,
        }

        # Sidecar written AFTER the mp3 is fully on disk so a partial file
        # never gets mistaken for a cache hit.
        write_cache(filepath, result)

        # Charge the ledger on cache MISS only — cache hits cost nothing.
        # Units = characters of TTS source actually sent (post-SSML).
        cost_ledger.record(
            project_name,
            stage="voiceover",
            provider="elevenlabs",
            model=model_id,
            units=len(tts_text),
            extra={"unit_id": unit["id"], "unit_type": unit["type"]},
        )

        return result
