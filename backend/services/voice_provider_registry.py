"""Registry of voice providers (ElevenLabs today, Qwen3 hosted/local stubs).

Single source of truth: ``prompts/voice_providers.json``. Mirror of the
``visual_provider_registry`` pattern — keep these symmetric so adding a new
voice provider is one registry entry + one class + (if the class is new) one
import below in ``_PROVIDER_CLASSES``.

Providers marked ``available: false`` in the JSON resolve to a stub that raises
``NotImplementedError`` when called. That keeps the frontend dropdown honest
(grayed-out options still surface) without forcing us to ship the SDK or env
plumbing before each provider is wired.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Type

from services.voice_elevenlabs import ElevenLabsProvider
from services.voice_provider import VoiceProvider
from services.voice_qwen3_hosted import Qwen3HostedProvider
from services.voice_qwen3_local import Qwen3LocalProvider

_PROMPTS_DIR = Path("prompts")
_REGISTRY_PATH = _PROMPTS_DIR / "voice_providers.json"


# Map of provider_id -> concrete VoiceProvider class. Add an entry here when
# you flip a provider from ``available: false`` to ``available: true`` AND ship
# the implementing class.
_PROVIDER_CLASSES: dict[str, Type[VoiceProvider]] = {
    "elevenlabs": ElevenLabsProvider,
    # Stubs are registered so introspection (provider_id matching) works at
    # boot. ``get_provider`` returns the stub class for ``available: false``
    # entries; ``synth_unit`` raises NotImplementedError clearly when called.
    "qwen3_hosted": Qwen3HostedProvider,
    "qwen3_local": Qwen3LocalProvider,
}


# Instance cache: providers are reused across units within a single process
# run. Stateless for ElevenLabs but harmless; symmetric with the visual
# registry pattern so future stateful providers (Qwen3 with a cached HTTP
# session) drop in without refactoring.
_INSTANCES: dict[str, VoiceProvider] = {}


def _load_registry() -> dict:
    with _REGISTRY_PATH.open() as f:
        return json.load(f)


def list_providers() -> list[dict]:
    """Public registry contents for the frontend dropdown.

    Returns every provider (available or not) with all metadata fields. The UI
    decides which to show as enabled — knowing about future providers up-front
    lets the dropdown render placeholders consistently."""
    reg = _load_registry()
    return list(reg["providers"])


def default_provider_id() -> str:
    return _load_registry()["default_provider"]


def _registry_entry(provider_id: str) -> dict:
    reg = _load_registry()
    for p in reg["providers"]:
        if p["id"] == provider_id:
            return p
    raise ValueError(
        f"Unknown voice provider: {provider_id!r}. "
        f"Known: {[p['id'] for p in reg['providers']]}"
    )


def get_provider(provider_id: str) -> VoiceProvider:
    """Return a cached provider instance. Caching is symmetric with the visual
    registry pattern so future stateful providers drop in unchanged."""
    if provider_id in _INSTANCES:
        return _INSTANCES[provider_id]

    entry = _registry_entry(provider_id)
    cls = _PROVIDER_CLASSES.get(provider_id)
    if cls is None:
        raise RuntimeError(
            f"Voice provider {provider_id!r} is in voice_providers.json but "
            f"has no class registered in "
            f"voice_provider_registry._PROVIDER_CLASSES."
        )
    instance = cls()
    # The stub classes carry the right provider_id at class level and raise on
    # synth_unit; available: false simply means "calling will raise", not "the
    # instance is fake". This keeps registry semantics uniform.
    _INSTANCES[provider_id] = instance
    return instance


def verify_voice_providers_exist() -> None:
    """Startup contract guard: every provider in the JSON must have a class
    registered, and every class's provider_id must match its JSON entry. Bad
    config fails at boot rather than at the first generation."""
    reg = _load_registry()
    problems: list[str] = []
    for p in reg["providers"]:
        cls = _PROVIDER_CLASSES.get(p["id"])
        if cls is None:
            problems.append(
                f"provider {p['id']!r} has no class in _PROVIDER_CLASSES"
            )
            continue
        if cls.provider_id != p["id"]:
            problems.append(
                f"class {cls.__name__}.provider_id={cls.provider_id!r} != "
                f"JSON id {p['id']!r}"
            )
    if reg["default_provider"] not in {p["id"] for p in reg["providers"]}:
        problems.append(
            f"default_provider {reg['default_provider']!r} is not in providers"
        )
    if problems:
        raise RuntimeError(
            "voice_providers.json is inconsistent:\n  " + "\n  ".join(problems)
        )
