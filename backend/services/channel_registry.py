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


def resolve_channel_section(channel_id: str | None, section: str) -> str:
    """Return the BODY of a `## <section>` heading from the channel's module.

    Matching is case-insensitive on the heading text. Body = lines after the
    heading up to the next `## ` heading or EOF, stripped of leading/trailing
    whitespace. Raises ValueError if the section is absent so misconfiguration
    fails loudly instead of silently producing an empty audience block.
    """
    c = _resolve(channel_id)
    resolved_id = c["id"]
    text = (_PROMPTS_DIR / c["channel_module"]).read_text()
    target = section.strip().lower()
    lines = text.splitlines()
    in_section = False
    body: list[str] = []
    for line in lines:
        if line.startswith("## "):
            if in_section:
                break
            if line[3:].strip().lower() == target:
                in_section = True
                continue
        elif in_section:
            body.append(line)
    if not in_section:
        raise ValueError(
            f"Channel {resolved_id!r} module has no '## {section}' section"
        )
    return "\n".join(body).strip()


def channel_preferred_hook_archetype(channel_id: str | None) -> str | None:
    """Return the channel's preferred_hook_archetype field, or None if absent.

    Used by hook_archetype_registry.resolve_archetype to walk the fallback chain
    without reaching into private internals."""
    c = _resolve(channel_id)
    return c.get("preferred_hook_archetype")


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


def list_channel_sections(channel_id: str | None) -> dict[str, str]:
    """Return ALL `## <heading>` sections of the channel module as
    {heading_text: body_text}, preserving file order. Returns {} if the module
    has no `## ` headings. Raises ValueError for unknown channel_id.

    Used by the UI's channel detail page so future channels with new sections
    (e.g. `## Pacing`) surface automatically without code changes.
    """
    c = _resolve(channel_id)
    text = (_PROMPTS_DIR / c["channel_module"]).read_text()
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            sections[current] = []
        elif current is not None:
            sections[current].append(line)
    return {k: "\n".join(v).strip() for k, v in sections.items()}
