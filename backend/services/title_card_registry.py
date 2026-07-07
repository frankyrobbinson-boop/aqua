"""Registry for per-channel title-card design presets — the save/load/delete
library behind the /remotion designer's "Save as preset" feature (Phase 1 of
title-card persistence).

One JSON file per channel: ``prompts/channels/<id>/title_cards.json``, holding a
``default`` (the NAME of the channel-default preset, or ``null``) plus an ordered
list of named presets, each ``{name, card_id, props}``. ``default`` is a forward
hook for Phase 2 (a channel baking one design in as its card); Phase 1 never
points it at a name — it only preserves an existing value and nulls it when the
pointed-at preset is deleted.

Mirrors ``channel_preset_registry`` and reuses its helpers so the two registries
agree on what a valid channel is and never race a half-written file: the
channel-dir root (``_CHANNELS_DIR``), the atomic JSON writer
(``_atomic_write_json``), and channel-id validation (``load_preset`` raises
``ValueError`` on an unknown channel — the route maps that to 404, matching how
``scripts.py`` validates channel ids).
"""

from __future__ import annotations

import json
from pathlib import Path

from services.channel_preset_registry import (
    _CHANNELS_DIR,
    _atomic_write_json,
    load_preset,
)


def _title_cards_path(channel_id: str) -> Path:
    return _CHANNELS_DIR / channel_id / "title_cards.json"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_library(channel_id: str) -> dict:
    """Return the channel's title-card library, or a bare skeleton
    (``{"default": None, "presets": []}``) when the file doesn't exist yet.

    Validates the channel id via ``load_preset`` (raises ``ValueError`` on an
    unknown channel, which the route maps to 404)."""
    load_preset(channel_id)  # validates channel id exists; ValueError -> 404
    path = _title_cards_path(channel_id)
    if not path.exists():
        return {"default": None, "presets": []}
    with path.open() as f:
        return json.load(f)


def save_preset(channel_id: str, name: str, card_id: str, props: dict) -> dict:
    """Upsert a named title-card design by ``name`` — overwrite a same-named
    preset in place, else append — preserving ``default``. Atomically writes and
    returns the updated library."""
    lib = load_library(channel_id)
    lib.setdefault("default", None)  # preserve existing; never set in Phase 1
    presets = lib.get("presets") or []
    entry = {"name": name, "card_id": card_id, "props": props}
    for i, existing in enumerate(presets):
        if existing.get("name") == name:
            presets[i] = entry
            break
    else:
        presets.append(entry)
    lib["presets"] = presets
    _atomic_write_json(_title_cards_path(channel_id), lib)
    return lib


def delete_preset(channel_id: str, name: str) -> dict:
    """Remove the named preset (raises ``ValueError`` if absent — the route maps
    that to 404). If it was the channel default, null the default. Atomically
    writes and returns the updated library."""
    lib = load_library(channel_id)
    lib.setdefault("default", None)
    presets = lib.get("presets") or []
    remaining = [p for p in presets if p.get("name") != name]
    if len(remaining) == len(presets):
        raise ValueError(f"Unknown title-card preset: {name!r}")
    lib["presets"] = remaining
    if lib.get("default") == name:
        lib["default"] = None
    _atomic_write_json(_title_cards_path(channel_id), lib)
    return lib
