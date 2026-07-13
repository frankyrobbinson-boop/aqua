"""Registry of visual providers (Pexels, Nano Banana, future Veo/Imagen/Grok).

Single source of truth: ``prompts/visual_providers.json``. Mirror of the
``channel_registry`` / ``hook_archetype_registry`` pattern — keep these
symmetric so adding a new provider is one registry entry + one class +
(if the class is new) one import below in ``_PROVIDER_CLASSES``.

Providers marked ``available: false`` in the JSON resolve to a stub that raises
``NotImplementedError`` when called. That keeps the frontend dropdown honest
(grayed-out options still surface) without forcing us to ship the SDK or env
plumbing before each provider is wired.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Type

from services.visual_nano_banana import NanoBananaProvider
from services.visual_pexels import PexelsVisualProvider
from services.visual_provider import VisualProvider
from services.visual_seedream import SeedreamProvider

_PROMPTS_DIR = Path("prompts")
_REGISTRY_PATH = _PROMPTS_DIR / "visual_providers.json"


# Map of provider_id -> concrete VisualProvider class. Add an entry here when
# you flip a provider from ``available: false`` to ``available: true`` AND ship
# the implementing class.
_PROVIDER_CLASSES: dict[str, Type[VisualProvider]] = {
    "pexels": PexelsVisualProvider,
    "seedream": SeedreamProvider,
    # nano_banana is deprecated as the ai_image default (replaced by seedream)
    # and marked available:false in the JSON, but the class stays mapped so it
    # can be flipped back on for comparison without re-wiring.
    "nano_banana": NanoBananaProvider,
}


# Instance cache: providers are reused across scenes within a single process
# run so dedup state (Pexels' used_clip_ids, Nano Banana's lazy client +
# semaphore) accumulates. Cleared implicitly on process restart.
_INSTANCES: dict[str, VisualProvider] = {}


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


def list_modes() -> list[dict]:
    """Mode list for the UI mode picker."""
    return list(_load_registry()["modes"])


def default_mode() -> str:
    return _load_registry()["default_mode"]


def default_provider_id() -> str:
    return _load_registry()["default_provider"]


def default_provider_for_mode(mode: str) -> str:
    """First available provider for the given mode, or the global default if
    nothing in the registry handles that mode yet (which would be a config
    error worth surfacing as ValueError rather than silently misrouting)."""
    reg = _load_registry()
    for p in reg["providers"]:
        if p["mode"] == mode and p.get("available"):
            return p["id"]
    known_modes = {p["mode"] for p in reg["providers"]}
    if mode not in known_modes:
        raise ValueError(
            f"Unknown visual mode: {mode!r}. Known: {sorted(known_modes)}"
        )
    raise ValueError(
        f"No available provider for mode {mode!r}. Known providers: "
        f"{[p['id'] for p in reg['providers'] if p['mode'] == mode]}"
    )


def _registry_entry(provider_id: str) -> dict:
    reg = _load_registry()
    for p in reg["providers"]:
        if p["id"] == provider_id:
            return p
    raise ValueError(
        f"Unknown visual provider: {provider_id!r}. "
        f"Known: {[p['id'] for p in reg['providers']]}"
    )


def get_provider(provider_id: str) -> VisualProvider:
    """Return a cached provider instance. Caching is critical for Pexels
    (per-run dedup state lives on the instance) and harmless for the others.
    """
    if provider_id in _INSTANCES:
        return _INSTANCES[provider_id]

    entry = _registry_entry(provider_id)
    if not entry.get("available"):
        # Stub: registered but not yet implemented. Build a stub instance so
        # introspection still works; raise on the actual fetch call so the
        # error message names the provider clearly.
        instance: VisualProvider = _StubProvider(provider_id, entry["mode"])
        _INSTANCES[provider_id] = instance
        return instance

    cls = _PROVIDER_CLASSES.get(provider_id)
    if cls is None:
        # Marked available in JSON but no class registered above. Most likely
        # cause: forgot to import + add to _PROVIDER_CLASSES.
        raise RuntimeError(
            f"Visual provider {provider_id!r} is marked available in "
            f"visual_providers.json but has no class registered in "
            f"visual_provider_registry._PROVIDER_CLASSES."
        )
    instance = cls()
    _INSTANCES[provider_id] = instance
    return instance


def verify_providers_exist() -> None:
    """Startup contract guard: every available provider in the JSON must have
    a class registered, and every class's provider_id/mode must match its JSON
    entry. Bad config fails at boot rather than at the first generation."""
    reg = _load_registry()
    problems: list[str] = []
    mode_ids = {m["id"] for m in reg["modes"]}
    for p in reg["providers"]:
        if p["mode"] not in mode_ids:
            problems.append(
                f"provider {p['id']!r} declares unknown mode {p['mode']!r}"
            )
        if not p.get("available"):
            continue
        cls = _PROVIDER_CLASSES.get(p["id"])
        if cls is None:
            problems.append(
                f"provider {p['id']!r} is available but has no class in "
                f"_PROVIDER_CLASSES"
            )
            continue
        if cls.provider_id != p["id"]:
            problems.append(
                f"class {cls.__name__}.provider_id={cls.provider_id!r} != "
                f"JSON id {p['id']!r}"
            )
        if cls.mode != p["mode"]:
            problems.append(
                f"class {cls.__name__}.mode={cls.mode!r} != JSON mode {p['mode']!r}"
            )
    if reg["default_provider"] not in {p["id"] for p in reg["providers"]}:
        problems.append(
            f"default_provider {reg['default_provider']!r} is not in providers"
        )
    if reg["default_mode"] not in mode_ids:
        problems.append(f"default_mode {reg['default_mode']!r} is not in modes")
    if problems:
        raise RuntimeError(
            "visual_providers.json is inconsistent:\n  " + "\n  ".join(problems)
        )


class _StubProvider(VisualProvider):
    """Placeholder for ``available: false`` entries. Raises with a clear
    message on use so calls don't fall through to a generic AttributeError."""

    def __init__(self, provider_id: str, mode: str):
        self.provider_id = provider_id
        self.mode = mode

    def fetch_for_scene(self, project_name: str, scene: dict):  # type: ignore[override]
        raise NotImplementedError(
            f"Provider {self.provider_id!r} is registered but not yet "
            f"implemented. Set 'available': false in visual_providers.json "
            f"or wire it up in visual_provider_registry._PROVIDER_CLASSES."
        )
