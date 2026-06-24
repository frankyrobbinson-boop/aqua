"""Registry for channel presets — the Phase 3a structured replacement for the
loose ``channels/<id>.md`` + companion ``.visuals.json`` files.

Single source of truth: ``prompts/channels.json`` (slim registry of channel
ids + the default), plus one ``prompts/channels/<id>/preset.json`` per channel
with the structured config (identity + per-stage fields).

Mirrors the pattern of ``video_type_registry`` and ``visual_provider_registry``
— a single JSON registry + per-entry assets, registered in one place so adding
a new channel is data-only.

Public surface intentionally minimal for Phase 3a — the edit UI in 3b is the
first consumer of ``save_preset`` / ``get_voice_module``. The existing pipeline
consumers (script_draft, outline, research, visual_prompt) continue to go
through ``channel_registry`` unchanged.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

_PROMPTS_DIR = Path("prompts")
_CHANNELS_DIR = _PROMPTS_DIR / "channels"
_REGISTRY_PATH = _PROMPTS_DIR / "channels.json"


@dataclass(frozen=True)
class ChannelSummary:
    id: str
    label: str
    description: str
    color: str


def _load_registry() -> dict:
    with _REGISTRY_PATH.open() as f:
        return json.load(f)


def _preset_path(channel_id: str) -> Path:
    return _CHANNELS_DIR / channel_id / "preset.json"


def _voice_path(channel_id: str) -> Path:
    return _CHANNELS_DIR / channel_id / "voice.md"


def _read_preset(channel_id: str) -> dict:
    path = _preset_path(channel_id)
    if not path.exists():
        raise ValueError(
            f"Channel preset missing: {path} (channel_id={channel_id!r})"
        )
    with path.open() as f:
        return json.load(f)


def _atomic_write_json(target: Path, payload: dict) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent)
    )
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


def _deep_merge(base: dict, patch: dict) -> dict:
    """Recursive dict merge — patch wins. Lists and scalars are replaced
    wholesale (no element-wise merge). Intended for partial preset updates from
    the editor UI."""
    out = dict(base)
    for k, v in patch.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def list_channels() -> list[ChannelSummary]:
    """Lightweight summary for dropdowns / chip lists. One preset.json read per
    channel — fine at registry scale (handful of channels)."""
    reg = _load_registry()
    summaries: list[ChannelSummary] = []
    for cid in reg["channels"]:
        preset = _read_preset(cid)
        summaries.append(
            ChannelSummary(
                id=preset["id"],
                label=preset.get("label", cid),
                description=preset.get("description", ""),
                color=preset.get("color", "#888888"),
            )
        )
    return summaries


def default_channel_id() -> str:
    return _load_registry()["default_channel"]


def load_preset(channel_id: str | None) -> dict:
    """Full preset dict — every section, all fields. ``channel_id=None``
    resolves to the registry default."""
    cid = channel_id or default_channel_id()
    reg = _load_registry()
    if cid not in reg["channels"]:
        raise ValueError(
            f"Unknown channel: {cid!r}. Known: {reg['channels']}"
        )
    return _read_preset(cid)


def save_preset(channel_id: str, partial: dict) -> None:
    """Deep-merge ``partial`` into the existing preset and atomically write.
    Unknown top-level keys are accepted (forward-compat for 3b sections that
    don't exist yet — script/voiceover/render/etc)."""
    current = load_preset(channel_id)
    merged = _deep_merge(current, partial)
    _atomic_write_json(_preset_path(channel_id), merged)


def get_voice_module(channel_id: str | None) -> str:
    """Read ``channels/<id>/voice.md``. The narrator + audience + voice-rules
    markdown that script/outline/research prompts splice into the
    ``{{CHANNEL}}`` slot."""
    cid = channel_id or default_channel_id()
    path = _voice_path(cid)
    if not path.exists():
        raise ValueError(f"Voice module missing for channel {cid!r}: {path}")
    return path.read_text()


def verify_presets() -> None:
    """Boot guard: every channel in the slim registry must have a preset.json
    and a voice.md. Surfaces broken state at boot rather than mid-run."""
    reg = _load_registry()
    problems: list[str] = []
    for cid in reg.get("channels", []):
        if not isinstance(cid, str):
            problems.append(
                f"channels.json entry {cid!r} is not a string id — "
                f"channel_migration may not have run"
            )
            continue
        if not _preset_path(cid).exists():
            problems.append(f"{cid}: missing {_preset_path(cid)}")
        if not _voice_path(cid).exists():
            problems.append(f"{cid}: missing {_voice_path(cid)}")
    default = reg.get("default_channel")
    if default and default not in reg.get("channels", []):
        problems.append(
            f"default_channel {default!r} not in channels list {reg.get('channels')!r}"
        )
    if problems:
        raise RuntimeError(
            "channel preset registry is inconsistent:\n  " + "\n  ".join(problems)
        )
