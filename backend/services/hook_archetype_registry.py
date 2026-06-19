"""Registry of hook archetypes (Beat-1 opening moves).

Single source of truth: ``prompts/hook_archetypes.json``. Mirror of the
video_type / channel registry pattern — adding a new archetype is one registry
entry + one module file (no code changes).
"""

import json
from pathlib import Path

_PROMPTS_DIR = Path("prompts")
_REGISTRY_PATH = _PROMPTS_DIR / "hook_archetypes.json"

HOOK_ARCHETYPE_SLOT = "{{HOOK_ARCHETYPE_BLOCK}}"


def _load_registry() -> dict:
    with _REGISTRY_PATH.open() as f:
        return json.load(f)


def list_archetypes() -> list[dict]:
    """Public registry contents for the UI dropdown: id, label, description."""
    reg = _load_registry()
    return [
        {"id": a["id"], "label": a["label"], "description": a["description"]}
        for a in reg["archetypes"]
    ]


def default_archetype_id() -> str:
    return _load_registry()["default_archetype"]


def _resolve(archetype_id: str | None) -> dict:
    reg = _load_registry()
    target = archetype_id or reg["default_archetype"]
    for a in reg["archetypes"]:
        if a["id"] == target:
            return a
    raise ValueError(
        f"Unknown hook_archetype: {target!r}. Known: {[a['id'] for a in reg['archetypes']]}"
    )


def resolve_archetype_module(archetype_id: str | None) -> tuple[str, str]:
    """Return ``(label, module_body_text)`` for the given archetype id.

    Falls back to the registry's ``default_archetype`` when ``archetype_id`` is
    None. Raises ``ValueError`` for an unknown id.
    """
    a = _resolve(archetype_id)
    body = (_PROMPTS_DIR / a["prompt_module"]).read_text()
    return a["label"], body


def resolve_archetype(per_video: str | None, channel_id: str | None) -> str:
    """Resolution chain:
       per_video → channels.json[channel_id].preferred_hook_archetype
                 → hook_archetypes.json.default_archetype
                 → 'scene'  (hard-coded last-resort if registry is broken)
       Unknown per_video → ValueError.
       Unknown channel-preferred value → ValueError.
       Channel entry missing the field → silent fall-through to registry default.
    """
    if per_video:
        _resolve(per_video)
        return per_video

    from services.channel_registry import channel_preferred_hook_archetype
    ch_pref = channel_preferred_hook_archetype(channel_id)
    if ch_pref:
        _resolve(ch_pref)
        return ch_pref

    try:
        return default_archetype_id()
    except (FileNotFoundError, KeyError):
        return "scene"


def build_archetype_block(archetype_id: str) -> str:
    """Render the splice-ready block for {{HOOK_ARCHETYPE_BLOCK}}:

        Beat 1 archetype: <Label>

        <module body>

    Built here (not in script_base.md) so the prompt reads naturally with OR
    without an override — the slot is always filled."""
    label, body = resolve_archetype_module(archetype_id)
    return f"Beat 1 archetype: {label}\n\n{body.strip()}"


def verify_archetype_modules_exist() -> None:
    """Raise if any module file referenced by the registry is missing, OR if any
    channel's preferred_hook_archetype is unknown."""
    reg = _load_registry()
    missing: list[str] = []
    for a in reg["archetypes"]:
        p = _PROMPTS_DIR / a["prompt_module"]
        if not p.exists():
            missing.append(f"{a['id']}: {p}")
    if missing:
        raise RuntimeError(
            "hook_archetypes.json references missing module files:\n  "
            + "\n  ".join(missing)
        )
    # Validate channel-preferred values
    from services.channel_registry import _load_registry as _load_channels
    known_ids = {a["id"] for a in reg["archetypes"]}
    bad: list[str] = []
    for c in _load_channels()["channels"]:
        pref = c.get("preferred_hook_archetype")
        if pref is not None and pref not in known_ids:
            bad.append(f"{c['id']}: preferred_hook_archetype={pref!r}")
    if bad:
        raise RuntimeError(
            "channels.json has unknown preferred_hook_archetype:\n  "
            + "\n  ".join(bad)
        )


def verify_hook_slot() -> None:
    """Raise if script_base.md is missing {{HOOK_ARCHETYPE_BLOCK}}."""
    text = (_PROMPTS_DIR / "script_base.md").read_text()
    if HOOK_ARCHETYPE_SLOT not in text:
        raise RuntimeError(f"script_base.md missing {HOOK_ARCHETYPE_SLOT}")
