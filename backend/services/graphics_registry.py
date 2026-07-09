"""Registry for per-channel graphics design presets — the save/load/delete
library behind the /remotion designer's "Save as preset" feature (Phase 1 of
graphics persistence).

Presets are grouped by ROLE (title screens, section headers, overlays,
transitions). One JSON file per channel per role under
``prompts/channels/<id>/`` — ``title_cards.json``, ``section_headers.json``,
``overlays.json``, ``transitions.json`` (see ``_ROLE_FILES``). Each file holds a
``default`` (the NAME of that role's channel-default preset, or ``null``) plus
an ordered list of named presets, each ``{name, card_id, props}``. ``default``
is a forward hook for Phase 2 (a channel baking one design in for that role);
Phase 1 never points it at a name — it only preserves an existing value and
nulls it when the pointed-at preset is deleted.

Mirrors ``channel_preset_registry`` and reuses its helpers so the two registries
agree on what a valid channel is and never race a half-written file: the
channel-dir root (``_CHANNELS_DIR``), the atomic JSON writer
(``_atomic_write_json``), and channel-id validation (``load_preset`` raises
``ValueError`` on an unknown channel — the route maps that to 404, matching how
``scripts.py`` validates channel ids).

The role set is mirrored by ``ALLOWED_ROLES`` in ``api/routes/remotion.py`` and
``ROLES`` in the frontend ``cards/registry.ts`` — keep the three in sync.
"""

from __future__ import annotations

import json
from pathlib import Path

from services.channel_preset_registry import (
    _CHANNELS_DIR,
    _atomic_write_json,
    load_preset,
)

# One JSON file per role, under prompts/channels/<id>/. Mirrors ALLOWED_ROLES in
# api/routes/remotion.py and ROLES in frontend/src/remotion/cards/registry.ts.
_ROLE_FILES = {
    "title": "title_cards.json",
    "section_header": "section_headers.json",
    "overlay": "overlays.json",
    "transition": "transitions.json",
}


def _role_path(channel_id: str, role: str) -> Path:
    """Path to a channel's per-role library file. Raises ``ValueError`` on an
    unknown role (the route validates the role first and maps this to 422)."""
    try:
        filename = _ROLE_FILES[role]
    except KeyError:
        raise ValueError(f"Unknown graphic role: {role!r}")
    return _CHANNELS_DIR / channel_id / filename


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_library(channel_id: str, role: str) -> dict:
    """Return the channel's graphics library for ``role``, or a bare skeleton
    (``{"default": None, "presets": []}``) when the file doesn't exist yet.

    Validates the channel id via ``load_preset`` (raises ``ValueError`` on an
    unknown channel, which the route maps to 404) and the role via
    ``_role_path`` (``ValueError`` on an unknown role, mapped to 422)."""
    load_preset(channel_id)  # validates channel id exists; ValueError -> 404
    path = _role_path(channel_id, role)
    if not path.exists():
        return {"default": None, "presets": []}
    with path.open() as f:
        return json.load(f)


def save_preset(
    channel_id: str, role: str, name: str, card_id: str, props: dict
) -> dict:
    """Upsert a named graphics design by ``name`` within ``role`` — overwrite a
    same-named preset in place, else append — preserving ``default``. Atomically
    writes and returns the updated library."""
    lib = load_library(channel_id, role)
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
    _atomic_write_json(_role_path(channel_id, role), lib)
    return lib


def resolve_section_header_default(channel_id: str | None) -> dict | None:
    """Resolve the channel's DEFAULT section-header design to a renderable
    ``{"comp", "props"}`` pair, or ``None`` when no default is set (or it names
    a preset that isn't present in the library).

    ``comp`` is the default preset's ``card_id`` (the Remotion comp to render)
    and ``props`` its saved design props. This is the opt-in switch for
    section-header cards: the EDL generator emits a section-header ``card`` at
    each section start only when this returns non-None, and assembly re-resolves
    it at render time so a design edit re-renders the cards without an EDL
    regen. ``channel_id=None`` resolves the registry default channel (matching
    ``resolve_channel_editing``)."""
    lib = load_library(channel_id, "section_header")
    default_name = lib.get("default")
    if not default_name:
        return None
    for preset in lib.get("presets") or []:
        if preset.get("name") == default_name:
            return {"comp": preset["card_id"], "props": preset.get("props") or {}}
    return None


def resolve_title_card_default(channel_id: str | None) -> dict | None:
    """Resolve the channel's DEFAULT title-card design to a renderable
    ``{"comp", "props"}`` pair, or ``None`` when no default is set (or it names
    a preset that isn't present in the library).

    ``comp`` is the default preset's ``card_id`` (the Remotion comp to render)
    and ``props`` its saved design props. This is the opt-in switch for the
    mid-hook title card: the EDL generator emits a title ``card`` at the hook
    scene whose narration opens with the spoken title only when this returns
    non-None, and assembly re-resolves it at render time so a design edit
    re-renders the card without an EDL regen. ``channel_id=None`` resolves the
    registry default channel (matching ``resolve_channel_editing``)."""
    lib = load_library(channel_id, "title")
    default_name = lib.get("default")
    if not default_name:
        return None
    for preset in lib.get("presets") or []:
        if preset.get("name") == default_name:
            return {"comp": preset["card_id"], "props": preset.get("props") or {}}
    return None


def delete_preset(channel_id: str, role: str, name: str) -> dict:
    """Remove the named preset from ``role`` (raises ``ValueError`` if absent —
    the route maps that to 404). If it was that role's channel default, null the
    default. Atomically writes and returns the updated library."""
    lib = load_library(channel_id, role)
    lib.setdefault("default", None)
    presets = lib.get("presets") or []
    remaining = [p for p in presets if p.get("name") != name]
    if len(remaining) == len(presets):
        raise ValueError(f"Unknown graphics preset: {name!r}")
    lib["presets"] = remaining
    if lib.get("default") == name:
        lib["default"] = None
    _atomic_write_json(_role_path(channel_id, role), lib)
    return lib
