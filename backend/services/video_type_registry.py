"""Registry of video types and their per-stage prompt files.

Single source of truth: ``prompts/video_types.json``. Both the script
generation code path and the UI dropdown read from this file, so adding a new
type is one registry entry + two full prompt files (outline + script) at the
``prompts/`` root — no code changes.

Each type owns a self-contained outline file and script file. Those files carry
their own structure inline; the composer only splices in the shared ``core.md``,
the channel voice, the numeric variables, the sample script, and creator
steering. There is no separate base/module split anymore.
"""

import json
from pathlib import Path

from services.channel_registry import CHANNEL_SLOT

_PROMPTS_DIR = Path("prompts")
_REGISTRY_PATH = _PROMPTS_DIR / "video_types.json"

# Composition delimiters — must match the placeholders in the type files.
CORE_SLOT = "{{CORE}}"
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


def load_core() -> str:
    """Return the shared core prompt text spliced into every type's {{CORE}}."""
    return (_PROMPTS_DIR / "core.md").read_text()


def _resolve(type_id: str | None) -> dict:
    """Return the registry entry for ``type_id``.

    Fails loudly: a missing (None/empty) or unknown ``type_id`` raises. There is
    no silent fallback to a default type — callers must pass a real type."""
    reg = _load_registry()
    if not type_id:
        raise ValueError(
            "video_type is required but was not provided. "
            f"Known: {[t['id'] for t in reg['types']]}"
        )
    for t in reg["types"]:
        if t["id"] == type_id:
            return t
    raise ValueError(
        f"Unknown video_type: {type_id!r}. Known: {[t['id'] for t in reg['types']]}"
    )


def _load_file(rel_path: str) -> str:
    return (_PROMPTS_DIR / rel_path).read_text()


def resolve_modules(type_id: str | None) -> tuple[str, str]:
    """Return ``(outline_file_text, script_file_text)`` for the given type.

    Raises ``ValueError`` for a missing or unknown id (no silent default)."""
    t = _resolve(type_id)
    return _load_file(t["outline_module"]), _load_file(t["script_module"])


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------

def compose_outline_prompt(
    base: str,
    core_content: str,
    channel_content: str,
    *,
    topic: str,
    target_minutes: int,
    additional_instructions: str | None = None,
    item_count: int | None = None,
) -> str:
    """Splice the outline type file's slots in priority order:

    1) CORE (shared premise/frame/ground-truth — trusted system content, first)
    2) CHANNEL (narrator/audience/voice — trusted)
    3) {topic}, {target_minutes}, {item_count} (our vars)
    4) ADDITIONAL_INSTRUCTIONS (user content last, so braces in it can't be
       captured by the var step)

    ``item_count`` defaults to 5 when unset so a direct caller still produces a
    valid prompt.
    """
    text = base.replace(CORE_SLOT, core_content)
    text = text.replace(CHANNEL_SLOT, channel_content)
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
    core_content: str,
    channel_content: str,
    *,
    topic: str,
    target_minutes: int,
    total_word_target: int,
    words_per_segment: int,
    hook_word_target: int,
    conclusion_word_target: int,
    additional_instructions: str | None = None,
    sample_script: str | None = None,
    item_count: int | None = None,
) -> str:
    """Same composition contract as the outline, plus a sample_script slot.

    Trusted content (core/channel/vars) goes first; user content (sample,
    creator steering) goes last so any braces in pasted content are inert."""
    text = base.replace(CORE_SLOT, core_content)
    text = text.replace(CHANNEL_SLOT, channel_content)
    text = (
        text.replace("{topic}", topic)
        .replace("{target_minutes}", str(target_minutes))
        .replace("{total_word_target}", str(total_word_target))
        .replace("{words_per_segment}", str(words_per_segment))
        .replace("{hook_word_target}", str(hook_word_target))
        .replace("{conclusion_word_target}", str(conclusion_word_target))
        .replace("{item_count}", str(item_count if item_count is not None else 5))
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
    """Raise if any type file referenced by the registry is missing."""
    reg = _load_registry()
    missing: list[str] = []
    for t in reg["types"]:
        for key in ("outline_module", "script_module"):
            p = _PROMPTS_DIR / t[key]
            if not p.exists():
                missing.append(f"{t['id']}: {p}")
    if missing:
        raise RuntimeError(
            "video_types.json references missing type files:\n  " + "\n  ".join(missing)
        )


def verify_base_slots() -> None:
    """Raise if a type file is missing its required composition slots.

    Every outline/script type file must carry {{CORE}}, {{CHANNEL}}, and
    {{ADDITIONAL_INSTRUCTIONS}}; script files must additionally carry
    {{SAMPLE_SCRIPT}} and the hook/conclusion word-target tokens."""
    # core.md must exist so {{CORE}} can be filled.
    core_path = _PROMPTS_DIR / "core.md"
    problems: list[str] = []
    if not core_path.exists():
        raise RuntimeError("prompts/core.md is missing")

    reg = _load_registry()
    for t in reg["types"]:
        outline_text = (_PROMPTS_DIR / t["outline_module"]).read_text()
        for slot in (CORE_SLOT, CHANNEL_SLOT, ADDITIONAL_INSTRUCTIONS_SLOT):
            if slot not in outline_text:
                problems.append(f"{t['outline_module']} missing {slot}")

        script_text = (_PROMPTS_DIR / t["script_module"]).read_text()
        for slot in (CORE_SLOT, CHANNEL_SLOT, SAMPLE_SCRIPT_SLOT, ADDITIONAL_INSTRUCTIONS_SLOT):
            if slot not in script_text:
                problems.append(f"{t['script_module']} missing {slot}")
        for token in ("{hook_word_target}", "{conclusion_word_target}"):
            if token not in script_text:
                problems.append(f"{t['script_module']} missing {token}")

    if problems:
        raise RuntimeError("\n".join(problems))
