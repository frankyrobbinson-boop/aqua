"""Registry of channels (narrator + audience + voice rules).

Single source of truth: ``prompts/channels.json``. Mirror of the video_type
registry pattern in ``video_type_registry.py`` — keep these symmetric so adding
a new channel is one registry entry + one module file (no code changes).
"""

import json
from pathlib import Path

_PROMPTS_DIR = Path("prompts")
_REGISTRY_PATH = _PROMPTS_DIR / "channels.json"

# Composition delimiter — must match the placeholder in *_base.md files.
CHANNEL_SLOT = "{{CHANNEL}}"


def _load_registry() -> dict:
    with _REGISTRY_PATH.open() as f:
        return json.load(f)


def list_channels() -> list[dict]:
    """Public registry contents for the UI dropdown."""
    reg = _load_registry()
    return [
        {"id": c["id"], "name": c["name"], "description": c["description"]}
        for c in reg["channels"]
    ]


def default_channel_id() -> str:
    return _load_registry()["default_channel"]


def _resolve(channel_id: str | None) -> dict:
    reg = _load_registry()
    target = channel_id or reg["default_channel"]
    for c in reg["channels"]:
        if c["id"] == target:
            return c
    raise ValueError(
        f"Unknown channel: {target!r}. Known: {[c['id'] for c in reg['channels']]}"
    )


def resolve_channel(channel_id: str | None) -> str:
    """Return the channel module's body for splicing into the {{CHANNEL}} slot.

    Falls back to the registry's ``default_channel`` when ``channel_id`` is None.
    Raises ``ValueError`` for an unknown id.
    """
    c = _resolve(channel_id)
    return (_PROMPTS_DIR / c["channel_module"]).read_text()


def verify_channel_modules_exist() -> None:
    """Raise if any module file referenced by the registry is missing."""
    reg = _load_registry()
    missing: list[str] = []
    for c in reg["channels"]:
        p = _PROMPTS_DIR / c["channel_module"]
        if not p.exists():
            missing.append(f"{c['id']}: {p}")
    if missing:
        raise RuntimeError(
            "channels.json references missing module files:\n  " + "\n  ".join(missing)
        )
