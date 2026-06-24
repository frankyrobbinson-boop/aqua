"""Auto-migration: loose `channels/<id>.md` + companion `.visuals.json`
→ structured `channels/<id>/preset.json` + `channels/<id>/voice.md`.

Phase 3a of the channel preset architecture. Runs at API boot (see
``api/main.py``) BEFORE the existing verify guards so downstream code sees the
new layout. Idempotent — a second run on already-migrated state is a no-op.

Detection: a channel is "legacy" if ``channels/<id>.md`` exists and
``channels/<id>/`` directory does not.

Field renames applied while writing ``preset.json#/visuals``:
  character_enabled         -> character.enabled
  character_image_path      -> character.image_path
  character_strength        -> character.strength
  prompt_enhancement_model  -> image_prompt_model

The ``_note`` documentation field from Phase 1 companion files is stripped.

If migration fails partway through, raise — better to fail boot loudly than
half-migrate and confuse later guards.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

_PROMPTS_DIR = Path("prompts")
_CHANNELS_DIR = _PROMPTS_DIR / "channels"
_REGISTRY_PATH = _PROMPTS_DIR / "channels.json"

# Deterministic color palette — keyed by short hash of the channel id so the
# UI chip color is stable across boots without storing anything yet.
_COLOR_PALETTE = [
    "#4a7c3a",  # gardening green
    "#3a5a7c",  # cool blue
    "#7c3a5a",  # plum
    "#7c5a3a",  # warm earth
    "#3a7c7c",  # teal
    "#5a3a7c",  # violet
    "#7c7c3a",  # olive
    "#3a7c5a",  # forest
]


def _color_for(channel_id: str) -> str:
    h = hashlib.sha256(channel_id.encode("utf-8")).digest()
    return _COLOR_PALETTE[h[0] % len(_COLOR_PALETTE)]


def _atomic_write_json(target: Path, payload: dict) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(payload, f, indent=2)
            f.write("\n")
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _translate_visuals(legacy: dict) -> dict:
    """Phase 1 flat companion shape -> Phase 3a nested preset shape."""
    # Drop the documentation field outright.
    legacy.pop("_note", None)
    return {
        "style_description": legacy.get("style_description", ""),
        "reference_image_paths": list(legacy.get("reference_image_paths", []) or []),
        "character": {
            "enabled": bool(legacy.get("character_enabled", False)),
            "image_path": legacy.get("character_image_path"),
            "strength": float(legacy.get("character_strength", 0.7)),
        },
        "creative_direction": legacy.get("creative_direction", ""),
        "image_prompt_model": legacy.get(
            "prompt_enhancement_model", "claude-haiku-4-5-20251001"
        ),
    }


def _legacy_channel_ids(registry: dict) -> list[tuple[str, dict]]:
    """Return [(channel_id, full_legacy_entry_dict)] for channels still on the
    old layout. Legacy entries in channels.json are dicts; slim ones are bare
    strings. So we can tell them apart structurally."""
    out: list[tuple[str, dict]] = []
    for entry in registry.get("channels", []):
        if isinstance(entry, dict) and "id" in entry:
            channel_dir = _CHANNELS_DIR / entry["id"]
            md_path = _CHANNELS_DIR / f"{entry['id']}.md"
            if md_path.exists() and not channel_dir.exists():
                out.append((entry["id"], entry))
    return out


def _migrate_one(channel_id: str, legacy_entry: dict) -> None:
    """Per-channel migration. See module docstring for the step list."""
    channel_dir = _CHANNELS_DIR / channel_id
    md_src = _CHANNELS_DIR / f"{channel_id}.md"
    visuals_src = _CHANNELS_DIR / f"{channel_id}.visuals.json"

    print(f"[channel_migration] migrating channel {channel_id!r}")

    # 1. mkdir + 2. move voice.md
    channel_dir.mkdir(parents=True, exist_ok=False)
    voice_dst = channel_dir / "voice.md"
    shutil.move(str(md_src), str(voice_dst))
    print(f"[channel_migration]   moved {md_src} -> {voice_dst}")

    # 3. translate visuals (if present); else use the defaults via empty input
    legacy_visuals: dict = {}
    if visuals_src.exists():
        with visuals_src.open() as f:
            legacy_visuals = json.load(f)
    visuals_block = _translate_visuals(legacy_visuals)

    # 4 + 5. identity + color
    preset = {
        "id": channel_id,
        "label": legacy_entry.get("name", channel_id),
        "description": legacy_entry.get("description", ""),
        "color": _color_for(channel_id),
        "preferred_hook_archetype": legacy_entry.get("preferred_hook_archetype"),
        "visuals": visuals_block,
    }

    # 6. write preset.json
    preset_path = channel_dir / "preset.json"
    _atomic_write_json(preset_path, preset)
    print(f"[channel_migration]   wrote {preset_path}")

    # 7. delete the legacy companion visuals file (data now in preset.json)
    if visuals_src.exists():
        visuals_src.unlink()
        print(f"[channel_migration]   deleted {visuals_src}")


def _rewrite_registry(registry: dict) -> None:
    """Rewrite channels.json into slim form. Idempotent."""
    slim_channels: list[str] = []
    for entry in registry.get("channels", []):
        if isinstance(entry, str):
            slim_channels.append(entry)
        elif isinstance(entry, dict) and "id" in entry:
            slim_channels.append(entry["id"])
    payload = {
        "default_channel": registry["default_channel"],
        "channels": slim_channels,
    }
    _atomic_write_json(_REGISTRY_PATH, payload)
    print(f"[channel_migration] rewrote {_REGISTRY_PATH} to slim format")


def _registry_is_slim(registry: dict) -> bool:
    return all(isinstance(c, str) for c in registry.get("channels", []))


def run_channel_migration() -> None:
    """Idempotent boot hook. Migrate any legacy channels and slim the registry.

    Safe to call repeatedly — does nothing if everything is already on the new
    layout."""
    if not _REGISTRY_PATH.exists():
        # Nothing to migrate. Fresh checkout without channels would hit this;
        # later verify guards will complain if that's not the intended state.
        return

    with _REGISTRY_PATH.open() as f:
        registry = json.load(f)

    legacy = _legacy_channel_ids(registry)

    if not legacy and _registry_is_slim(registry):
        # Fully migrated. No-op.
        return

    print(
        f"[channel_migration] starting (legacy_channels={len(legacy)}, "
        f"registry_slim={_registry_is_slim(registry)})"
    )

    for channel_id, legacy_entry in legacy:
        _migrate_one(channel_id, legacy_entry)

    if not _registry_is_slim(registry):
        _rewrite_registry(registry)

    print("[channel_migration] complete")
