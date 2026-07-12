"""Registry of channels (narrator + audience + voice rules).

Phase 3a layout — data now lives in:
  - ``prompts/channels.json``               slim registry (default + id list)
  - ``prompts/channels/<id>/preset.json``   structured config (identity + visuals)
  - ``prompts/channels/<id>/voice.md``      the narrator/audience/voice-rules markdown

The legacy layout (loose ``channels/<id>.md`` + companion ``.visuals.json``)
is auto-migrated at boot by ``services.channel_migration``. Idempotent.

Public surface is intentionally unchanged from the pre-3a version — all the
existing pipeline consumers (script_draft, outline, research, visual_prompt)
keep working through these same functions. Only the internal file readers
flipped. The richer editor-facing surface lives in
``services.channel_preset_registry``.
"""

import json
from pathlib import Path

_PROMPTS_DIR = Path("prompts")
_CHANNELS_DIR = _PROMPTS_DIR / "channels"
_REGISTRY_PATH = _PROMPTS_DIR / "channels.json"

# Composition delimiter — must match the placeholder in *_base.md files.
CHANNEL_SLOT = "{{CHANNEL}}"


def _read_slim_registry() -> dict:
    """Raw slim registry. Phase 3a shape:
       {"default_channel": "<id>", "channels": ["<id>", ...]}
    """
    with _REGISTRY_PATH.open() as f:
        return json.load(f)


def _read_preset(channel_id: str) -> dict:
    path = _CHANNELS_DIR / channel_id / "preset.json"
    if not path.exists():
        raise ValueError(
            f"Channel preset missing: {path} (channel_id={channel_id!r})"
        )
    with path.open() as f:
        return json.load(f)


def _load_registry() -> dict:
    """Internal: registry hydrated to the legacy dict shape so internal callers
    (and ``hook_archetype_registry``, which iterates ``channels[*]`` for the
    boot guard) don't need to change.

    Returns:
        {
          "default_channel": "<id>",
          "channels": [
            {"id": ..., "name": ..., "description": ...,
             "channel_module": "channels/<id>/voice.md",
             "preferred_hook_archetype": ...},
            ...
          ]
        }
    """
    slim = _read_slim_registry()
    hydrated_channels: list[dict] = []
    for cid in slim.get("channels", []):
        preset = _read_preset(cid)
        hydrated_channels.append({
            "id": preset["id"],
            # ``label`` is the new key; ``name`` is retained for the legacy
            # dict shape consumers expect.
            "name": preset.get("label", cid),
            "description": preset.get("description", ""),
            "color": preset.get("color", "#888888"),
            "channel_module": f"channels/{cid}/voice.md",
            "preferred_hook_archetype": preset.get("preferred_hook_archetype"),
        })
    return {
        "default_channel": slim["default_channel"],
        "channels": hydrated_channels,
    }


def list_channels() -> list[dict]:
    """Public registry contents for the UI dropdown. Includes ``color`` so
    the channels list page can render the chip without a second per-channel
    preset fetch."""
    reg = _load_registry()
    return [
        {
            "id": c["id"],
            "name": c["name"],
            "description": c["description"],
            "color": c["color"],
        }
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

    Phase 3a: reads ``channels/<id>/voice.md`` (was ``channels/<id>.md``).
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


# ---------------------------------------------------------------------------
# Channel visuals
# ---------------------------------------------------------------------------

# Defaults used when a channel's preset has no ``visuals`` block or a field is
# missing. Shape matches what callers (visual_prompt_service) currently read —
# the flat Phase 1 shape, NOT the nested preset.json shape. The resolver below
# translates from nested back to flat so visual_prompt_service stays stable.
_VISUALS_DEFAULTS: dict = {
    "style_description": "",
    "world": "",
    "cast": "",
    "props": "",
    "reference_image_paths": [],
    "character_enabled": False,
    "character_image_path": None,
    "character_strength": 0.7,
    "creative_direction": "",
    "prompt_enhancement_model": "gpt-5",
}


def _flatten_visuals(nested: dict) -> dict:
    """preset.json ``visuals`` block (nested character{}, image_prompt_model)
    → the flat shape ``visual_prompt_service`` consumes
    (character_enabled / character_image_path / character_strength /
    prompt_enhancement_model). Refactoring the consumer is a later migration."""
    character = nested.get("character") or {}
    flat = {
        "style_description": nested.get("style_description", ""),
        "world": nested.get("world", ""),
        "cast": nested.get("cast", ""),
        "props": nested.get("props", ""),
        "reference_image_paths": list(nested.get("reference_image_paths", []) or []),
        "character_enabled": bool(character.get("enabled", False)),
        "character_image_path": character.get("image_path"),
        "character_strength": float(character.get("strength", 0.7)),
        "creative_direction": nested.get("creative_direction", ""),
        "prompt_enhancement_model": nested.get(
            "image_prompt_model", "gpt-5"
        ),
    }
    merged = dict(_VISUALS_DEFAULTS)
    merged.update({k: v for k, v in flat.items() if k in _VISUALS_DEFAULTS})
    return merged


def resolve_channel_visuals(channel_id: str | None) -> dict:
    """Read the channel's visuals config from ``channels/<id>/preset.json``
    under the ``visuals`` key (Phase 3a).

    Public signature is identical to the Phase 1 version that read
    ``channels/<id>.visuals.json`` — callers (visual_prompt_service) see the
    same flat schema. The nested-character + renamed
    ``image_prompt_model`` shape lives only inside preset.json and gets flat-
    tened here. Refactoring the consumer to use the nested shape is a follow-up
    migration.

    Missing fields are backfilled from ``_VISUALS_DEFAULTS`` so callers always
    get the full schema. Missing visuals block = all defaults (passthrough
    mode triggers downstream when style/creative_direction are empty).
    """
    c = _resolve(channel_id)
    preset = _read_preset(c["id"])
    return _flatten_visuals(preset.get("visuals") or {})


# ---------------------------------------------------------------------------
# Channel voiceover
# ---------------------------------------------------------------------------

# Defaults used when a channel's preset has no ``voiceover`` block or a field
# is missing. Shape matches what voice_service / voice providers consume —
# flat dict mirroring resolve_channel_visuals semantics. ``voice_id``,
# ``voice_reference_path`` are None when unset (no fallback id baked here so
# the provider's own default-voice precedence stays the single source of
# truth — for ElevenLabs that's env ELEVENLABS_VOICE_ID > built-in George).
_VOICEOVER_DEFAULTS: dict = {
    "provider": "elevenlabs",
    "voice_id": None,
    "model": "eleven_multilingual_v2",
    "speed": 1.0,
    "settings": {
        "stability": 0.5,
        "similarity_boost": 0.75,
        "style": 0.0,
        "use_speaker_boost": True,
    },
    "voice_reference_path": None,
}


def _flatten_voiceover(nested: dict) -> dict:
    """preset.json ``voiceover`` block → flat schema consumed by voice
    providers. Missing fields are backfilled from ``_VOICEOVER_DEFAULTS``;
    ``settings`` is shallow-merged so a preset can override only the keys it
    cares about without re-stating the whole settings dict."""
    merged: dict = dict(_VOICEOVER_DEFAULTS)
    for k, v in (nested or {}).items():
        if k not in _VOICEOVER_DEFAULTS:
            continue
        if k == "settings" and isinstance(v, dict):
            merged_settings = dict(_VOICEOVER_DEFAULTS["settings"])
            merged_settings.update(v)
            merged["settings"] = merged_settings
        else:
            merged[k] = v
    return merged


def resolve_channel_voiceover(channel_id: str | None) -> dict:
    """Read the channel's voiceover config from ``channels/<id>/preset.json``
    under the ``voiceover`` key. Returns the flat schema with defaults filled
    in; if the preset has no voiceover block (e.g., the gardening preset
    pre-migration), returns all defaults.

    Public signature mirrors ``resolve_channel_visuals`` and is meant to stay
    stable across the channel-preset architecture migration — callers in
    voice_service and the provider classes consume this dict and rely on the
    full schema being present.
    """
    c = _resolve(channel_id)
    preset = _read_preset(c["id"])
    return _flatten_voiceover(preset.get("voiceover") or {})


# ---------------------------------------------------------------------------
# Channel editing (on-screen motion / overlays)
# ---------------------------------------------------------------------------

# Defaults used when a channel's preset has no ``editing`` block or a field is
# missing. Nested per-kind look + policy (header / callout / counter), flattened
# by ``_flatten_editing`` the same way visuals are — the render layer
# (assembly_service) and EDL generator consume the flat per-kind dicts. This is
# the seam where per-channel on-screen styles will source LATER; no channel
# editor writes an ``editing`` block yet, so every channel gets these defaults.
_EDITING_DEFAULTS: dict = {
    "header": {
        "enabled": True,
        "animation": "slide_up",
        "position": "top",
        "entrance": 0.4,
        "exit_fade": 0.3,
        "slide_distance": 40,
        "fontsize": 64,
        "box_opacity": 0.6,
        "box_border": 20,
    },
    "callout": {
        "enabled": False,
        "animation": "pop",
        "position": "upper_third",
        "start_offset": 0.3,
        "duration": 1.8,
        "settle": 0.15,
        "fontsize": 56,
        "box_opacity": 0.55,
        "box_border": 16,
    },
    "counter": {
        "enabled": False,
        "position": "top_right",
        "margin": 40,
        "fontsize": 40,
        "box_opacity": 0.5,
        "box_border": 12,
    },
}


def _flatten_editing(nested: dict) -> dict:
    """preset.json ``editing`` block → the flat per-kind schema the EDL
    generator + render layer consume. Each kind (header/callout/counter) is
    shallow-merged onto its defaults so a preset can override only the fields
    it cares about without restating the whole block; unknown keys are dropped.
    Mirrors ``_flatten_visuals`` / ``_flatten_voiceover`` semantics."""
    merged: dict = {}
    for kind, kind_defaults in _EDITING_DEFAULTS.items():
        merged_kind = dict(kind_defaults)
        override = (nested or {}).get(kind)
        if isinstance(override, dict):
            merged_kind.update(
                {k: v for k, v in override.items() if k in kind_defaults}
            )
        merged[kind] = merged_kind
    return merged


def resolve_channel_editing(channel_id: str | None = None) -> dict:
    """Read the channel's editing (on-screen motion) config from
    ``channels/<id>/preset.json`` under the ``editing`` key. Returns the flat
    per-kind schema with defaults filled in; if the preset has no editing block
    (the case for every channel today — no editor writes one yet), returns all
    defaults.

    Public signature mirrors ``resolve_channel_visuals`` /
    ``resolve_channel_voiceover`` and is meant to stay stable across the
    channel-preset architecture migration — the EDL generator and render layer
    consume this dict and rely on the full per-kind schema being present."""
    c = _resolve(channel_id)
    preset = _read_preset(c["id"])
    return _flatten_editing(preset.get("editing") or {})


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
