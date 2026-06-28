import json
import os
from dotenv import load_dotenv
import anthropic

from services import cost_ledger
from services.channel_registry import resolve_channel
from services.outline_service import load_outline
from services.paths import PROJECTS_ROOT
from services.research_filters import strip_research_sources
from services.research_service import load_research
from services.video_type_registry import (
    compose_script_prompt,
    resolve_modules,
)

load_dotenv()

client = anthropic.Anthropic(
    api_key=os.getenv("ANTHROPIC_API_KEY")
)

WORDS_PER_MINUTE = 150  # spoken narration pace

SCRIPT_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "hook": {
            "type": "object",
            "properties": {
                "narration": {"type": "string"}
            },
            "required": ["narration"],
            "additionalProperties": False
        },
        "segments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "narration": {"type": "string"},
                    "visual_notes": {"type": "string"}
                },
                "required": ["title", "narration", "visual_notes"],
                "additionalProperties": False
            }
        },
        "conclusion": {
            "type": "object",
            "properties": {
                "narration": {"type": "string"}
            },
            "required": ["narration"],
            "additionalProperties": False
        }
    },
    "required": ["title", "hook", "segments", "conclusion"],
    "additionalProperties": False
}


def _load_script_base() -> str:
    with open("prompts/script_base.md", "r") as f:
        return f.read()


def generate_script_draft(
    project_name,
    topic: str,
    target_minutes: int,
    channel: str | None = None,
    video_type: str | None = None,
    hook_archetype: str | None = None,
    additional_instructions: str | None = None,
    sample_script: str | None = None,
):
    outline = load_outline(project_name)
    research = strip_research_sources(load_research(project_name))
    base = _load_script_base()
    channel_content = resolve_channel(channel)
    _, script_module = resolve_modules(video_type)
    from services.hook_archetype_registry import resolve_archetype, build_archetype_block
    resolved_archetype_id = resolve_archetype(hook_archetype, channel)
    hook_archetype_block = build_archetype_block(resolved_archetype_id)

    n_sections = max(1, len(outline.get("sections", [])))
    total_word_target = target_minutes * WORDS_PER_MINUTE
    hook_word_target = 150
    conclusion_word_target = 150
    remainder = max(n_sections * 80, total_word_target - hook_word_target - conclusion_word_target)
    words_per_segment = remainder // n_sections

    prompt = compose_script_prompt(
        base,
        channel_content,
        script_module,
        topic=topic,
        target_minutes=target_minutes,
        total_word_target=total_word_target,
        words_per_segment=words_per_segment,
        hook_word_target=hook_word_target,
        conclusion_word_target=conclusion_word_target,
        hook_archetype_block=hook_archetype_block,
        additional_instructions=additional_instructions,
        sample_script=sample_script,
    )

    # max_tokens covers thinking + structured output combined. Opus 4.7 uses
    # `thinking.type=adaptive` with `output_config.effort` to cap thinking
    # (not `thinking.budget_tokens` — that errors on this model). With the
    # round-4 prompt simplification (~50% smaller), the model wastes less
    # thinking on rule reconciliation, so the freed budget can go into actual
    # script craft. effort=medium is the right default — low would just bank
    # the simplification savings as cost reduction instead of letting them
    # become quality. Bump to high if scripts feel under-cooked; drop to low
    # only if cost becomes a problem and quality is still strong.
    with client.messages.stream(
        # Sonnet 4.6 — ~5x cheaper than Opus, handles structured creative
        # work (script-from-outline) well. If script quality drops noticeably
        # on real videos, revert to claude-opus-4-7 (keep effort=medium).
        model="claude-sonnet-4-6",
        # 65536: adaptive thinking + structured output share this budget.
        # An 8-item 16-min listicle (~2400 spoken words) is ~3500 tokens of
        # JSON output; Sonnet's thinking can chew through 20K+ tokens before
        # the output starts. 24K crashed on this case with stop_reason=
        # max_tokens. 64K leaves comfortable headroom for even larger scripts.
        max_tokens=65536,
        thinking={"type": "adaptive"},
        output_config={
            "format": {"type": "json_schema", "schema": SCRIPT_SCHEMA},
            "effort": "medium",
        },
        messages=[
            {
                "role": "user",
                "content": f"""
{prompt}

OUTLINE:
{json.dumps(outline, indent=2)}

RESEARCH:
{json.dumps(research["research"], indent=2)}
"""
            }
        ]
    ) as stream:
        response = stream.get_final_message()

    usage = getattr(response, "usage", None)
    in_tok = getattr(usage, "input_tokens", 0) if usage else 0
    out_tok = getattr(usage, "output_tokens", 0) if usage else 0
    cost_ledger.record(
        project_name,
        stage="script_draft",
        provider="anthropic",
        model="claude-sonnet-4-6",
        input_tokens=in_tok,
        output_tokens=out_tok,
    )

    text = next((b.text for b in response.content if b.type == "text"), None)
    if text is None:
        raise RuntimeError(
            f"No text block in Claude response; block types present: "
            f"{[b.type for b in response.content]}"
            f"\nstop_reason={getattr(response, 'stop_reason', '?')}"
        )
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        # Surface the partial output so truncated-JSON failures are debuggable
        # (mirrors the ffmpeg-stderr fix). If stop_reason is "max_tokens" the
        # model ran out mid-response — bump max_tokens above.
        stop_reason = getattr(response, "stop_reason", "?")
        head = text[:400]
        tail = text[-400:] if len(text) > 800 else ""
        raise RuntimeError(
            f"Script JSON did not parse (stop_reason={stop_reason}, "
            f"text_len={len(text)}, error={e!r}).\n"
            f"--- first 400 chars ---\n{head}\n"
            f"--- last 400 chars ---\n{tail}"
        ) from e


def save_script_draft(project_name, script_draft):
    folder = PROJECTS_ROOT / project_name
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / "script_draft.json").open("w") as f:
        json.dump(script_draft, f, indent=2)


def load_script_draft(project_name):
    with (PROJECTS_ROOT / project_name / "script_draft.json").open("r") as f:
        return json.load(f)
