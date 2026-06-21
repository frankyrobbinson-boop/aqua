"""Registry of video types and their per-stage structure modules.

Single source of truth: ``prompts/video_types.json``. Both the script
generation code path and the UI dropdown read from this file, so adding a new
type is one registry entry + two module files (no code changes).
"""

import json
from pathlib import Path
from typing import Iterable

from services.channel_registry import CHANNEL_SLOT
from services.hook_archetype_registry import HOOK_ARCHETYPE_SLOT

_PROMPTS_DIR = Path("prompts")
_REGISTRY_PATH = _PROMPTS_DIR / "video_types.json"

# Composition delimiters — must match the placeholders in *_base.md files.
STRUCTURE_SLOT = "{{STRUCTURE_MODULE}}"
SAMPLE_SCRIPT_SLOT = "{{SAMPLE_SCRIPT}}"
ADDITIONAL_INSTRUCTIONS_SLOT = "{{ADDITIONAL_INSTRUCTIONS}}"
# CHANNEL_SLOT is owned by channel_registry; re-exported above for callers.


def _load_registry() -> dict:
    with _REGISTRY_PATH.open() as f:
        return json.load(f)


def list_types() -> list[dict]:
    """Return the public registry contents for the UI dropdown."""
    reg = _load_registry()
    return [
        {"id": t["id"], "label": t["label"], "description": t["description"]}
        for t in reg["types"]
    ]


def default_type_id() -> str:
    return _load_registry()["default_type"]


def _resolve(type_id: str | None) -> dict:
    reg = _load_registry()
    target = type_id or reg["default_type"]
    for t in reg["types"]:
        if t["id"] == target:
            return t
    raise ValueError(
        f"Unknown video_type: {target!r}. Known: {[t['id'] for t in reg['types']]}"
    )


def _load_module(rel_path: str) -> str:
    return (_PROMPTS_DIR / rel_path).read_text()


def resolve_modules(type_id: str | None) -> tuple[str, str]:
    """Return ``(outline_module_text, script_module_text)`` for the given type.

    Falls back to the registry's ``default_type`` when ``type_id`` is None.
    Raises ``ValueError`` for an unknown id.
    """
    t = _resolve(type_id)
    return _load_module(t["outline_module"]), _load_module(t["script_module"])


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------

def compose_outline_prompt(
    base: str,
    channel_content: str,
    structure_module: str,
    *,
    topic: str,
    target_minutes: int,
    additional_instructions: str | None = None,
    item_count: int | None = None,
) -> str:
    """Splice channel + structure module + variable substitutions in priority order:

    1) CHANNEL (narrator/audience/voice — trusted system content, first)
    2) STRUCTURE_MODULE (per-video-type structure — trusted)
    3) {topic}, {target_minutes}, {item_count} (our vars)
    4) ADDITIONAL_INSTRUCTIONS (user content last, so braces in it can't be
       captured by the var step)

    ``item_count`` is only meaningful for the listicle module (whose template
    uses ``{item_count}``); other modules ignore the token. Defaults to 5 so
    callers that don't know about listicles still produce a valid prompt.
    """
    text = base.replace(CHANNEL_SLOT, channel_content)
    text = text.replace(STRUCTURE_SLOT, structure_module)
    text = (
        text.replace("{topic}", topic)
        .replace("{target_minutes}", str(target_minutes))
        .replace("{item_count}", str(item_count if item_count is not None else 5))
    )
    text = text.replace(
        ADDITIONAL_INSTRUCTIONS_SLOT,
        _additional_block(additional_instructions),
    )
    return text


def compose_script_prompt(
    base: str,
    channel_content: str,
    structure_module: str,
    *,
    topic: str,
    target_minutes: int,
    total_word_target: int,
    words_per_segment: int,
    hook_archetype_block: str,
    additional_instructions: str | None = None,
    sample_script: str | None = None,
) -> str:
    """Same composition contract as the outline, plus a sample_script slot.

    Sample script goes through last so any braces in pasted content are inert."""
    text = base.replace(CHANNEL_SLOT, channel_content)
    text = text.replace(STRUCTURE_SLOT, structure_module)
    text = text.replace(HOOK_ARCHETYPE_SLOT, hook_archetype_block)
    text = (
        text.replace("{topic}", topic)
        .replace("{target_minutes}", str(target_minutes))
        .replace("{total_word_target}", str(total_word_target))
        .replace("{words_per_segment}", str(words_per_segment))
    )
    text = text.replace(SAMPLE_SCRIPT_SLOT, _sample_block(sample_script))
    text = text.replace(
        ADDITIONAL_INSTRUCTIONS_SLOT,
        _additional_block(additional_instructions),
    )
    return text


def _additional_block(content: str | None) -> str:
    if not content or not content.strip():
        return ""
    return (
        "Extra instructions from the creator — follow where they don't "
        "conflict with the schema or structure above:\n\n"
        f"{content.strip()}"
    )


def _sample_block(content: str | None) -> str:
    if not content or not content.strip():
        return ""
    return (
        "Reference script — match the rhythm and pacing of this example. "
        "Do NOT copy its structure or topic; your structure comes from the "
        "section above.\n\n"
        f"<example>\n{content.strip()}\n</example>"
    )


# ---------------------------------------------------------------------------
# Startup contract guards
# ---------------------------------------------------------------------------

def verify_modules_exist() -> None:
    """Raise if any module file referenced by the registry is missing."""
    reg = _load_registry()
    missing: list[str] = []
    for t in reg["types"]:
        for key in ("outline_module", "script_module"):
            p = _PROMPTS_DIR / t[key]
            if not p.exists():
                missing.append(f"{t['id']}: {p}")
    if missing:
        raise RuntimeError(
            "video_types.json references missing module files:\n  " + "\n  ".join(missing)
        )


def verify_base_slots() -> None:
    """Raise if a base file is missing its required slots."""
    outline_base = (_PROMPTS_DIR / "outline_base.md").read_text()
    script_base = (_PROMPTS_DIR / "script_base.md").read_text()
    problems: list[str] = []
    for slot in (CHANNEL_SLOT, STRUCTURE_SLOT, ADDITIONAL_INSTRUCTIONS_SLOT):
        if slot not in outline_base:
            problems.append(f"outline_base.md missing {slot}")
    for slot in (CHANNEL_SLOT, STRUCTURE_SLOT, SAMPLE_SCRIPT_SLOT, ADDITIONAL_INSTRUCTIONS_SLOT):
        if slot not in script_base:
            problems.append(f"script_base.md missing {slot}")
    if problems:
        raise RuntimeError("\n".join(problems))
