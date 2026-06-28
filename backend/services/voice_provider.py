"""Provider-agnostic interface for synthesizing per-unit voiceover audio.

Concrete providers (ElevenLabs today, Qwen3 hosted/local as future stubs)
implement ``VoiceProvider``. The orchestrator in ``voice_service`` consumes the
interface, not the concrete classes — adding a new provider is one class + one
registry entry.

Each provider is responsible for placing one audio file per voice unit at
``<projects_root>/<name>/audio/audio_<id:02d>_<type>.mp3`` and writing a JSON
cache sidecar so re-runs can skip unchanged units. The cache key is provider-
defined (text + seed + speed for ElevenLabs, prompt + voice ref for Qwen3, etc).

``synth_unit`` returns the cache-entry dict the orchestrator's timeline builder
consumes — same shape as the legacy ``voice_service._generate_unit`` so the
public surface (generate_audio + save_audio_timeline) stays stable.
"""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from services.paths import PROJECTS_ROOT


def cache_path_for(audio_path: str | Path) -> str:
    """Sidecar path: ``<audio>.json`` (drops the .mp3 extension). Mirrors the
    convention the legacy ElevenLabs path used so existing on-disk caches in
    ``<projects_root>/<name>/audio/`` remain valid across the refactor."""
    p = str(audio_path)
    if p.endswith(".mp3"):
        return p[:-4] + ".json"
    return p + ".json"


def is_cache_valid(audio_path: str | Path, expected: dict[str, Any]) -> bool:
    """True iff ``audio_path`` exists with size > 0 AND its sidecar's keys all
    match ``expected``. Any unrecognized key in the sidecar is ignored — only
    the keys the caller asks about are checked, so providers can add their own
    fields (request_id, model, etc.) without breaking old caches."""
    out = str(audio_path)
    sidecar = cache_path_for(out)
    if not (os.path.exists(out) and os.path.exists(sidecar)):
        return False
    try:
        if os.path.getsize(out) == 0:
            return False
    except OSError:
        return False
    try:
        with open(sidecar) as f:
            cache = json.load(f)
    except (OSError, json.JSONDecodeError):
        return False
    return all(cache.get(k) == v for k, v in expected.items())


def read_cache(audio_path: str | Path) -> dict | None:
    """Read the sidecar dict for ``audio_path``. Returns None on any read
    failure (missing, malformed) so callers can branch cleanly on cache hit
    vs miss without try/except boilerplate."""
    try:
        with open(cache_path_for(audio_path)) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def write_cache(audio_path: str | Path, payload: dict[str, Any]) -> None:
    """Write the sidecar AFTER the audio file is fully on disk. Callers must
    not invoke this until the audio is finalized — a sidecar pointing at a
    half-written mp3 would mark a corrupt clip as a cache hit."""
    with open(cache_path_for(audio_path), "w") as f:
        json.dump(payload, f, indent=2)


def audio_dir_for(project_name: str) -> Path:
    """Canonical per-project audio directory. Created if absent so providers
    don't each re-implement the mkdir dance."""
    p = PROJECTS_ROOT / project_name / "audio"
    p.mkdir(parents=True, exist_ok=True)
    return p


class VoiceProvider(ABC):
    """One voice synthesis source (cloud TTS API, local model).

    Subclasses MUST set ``provider_id`` as a class attribute and implement
    ``synth_unit``. The id must match the entry in
    ``prompts/voice_providers.json``; the registry uses it for lookup.

    ``synth_unit`` signature mirrors the legacy ``voice_service._generate_unit``
    so existing orchestrator code (timeline stamping, request-id chaining) is
    untouched. Returns the cache-entry dict — same shape as today.
    """

    provider_id: str = ""

    @abstractmethod
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
        """Produce an audio file + cache entry for ``unit``.

        Implementations should:
          1) Check ``is_cache_valid`` against their provider-specific cache key
             and return the cached dict on a hit.
          2) On a miss, synthesize the audio to
             ``<projects_root>/<project_name>/audio/audio_<id:02d>_<type>.mp3``.
          3) Call ``write_cache`` AFTER the file is fully written.
          4) Return a dict with keys: segment_id, type, title, text, audio_file,
             duration, words, tts_source, seed, voice_speed, request_id. (Extra
             keys allowed; the orchestrator timeline builder only reads these.)
          5) Raise on failure — do not swallow.

        ``voice_config`` is the flat schema from
        ``channel_registry.resolve_channel_voiceover`` (voice_id, model, speed
        defaults, settings, voice_reference_path). Providers pick what they need.
        """
