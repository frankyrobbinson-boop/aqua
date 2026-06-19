import json
import os
from dotenv import load_dotenv
import anthropic

from services.channel_registry import resolve_channel
from services.outline_service import load_outline
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
                "narration": {"type": "string"},
                "cta": {"type": "string"}
            },
            "required": ["narration", "cta"],
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
    research = load_research(project_name)
    base = _load_script_base()
    channel_content = resolve_channel(channel)
    _, script_module = resolve_modules(video_type)
    from services.hook_archetype_registry import resolve_archetype, build_archetype_block
    resolved_archetype_id = resolve_archetype(hook_archetype, channel)
    hook_archetype_block = build_archetype_block(resolved_archetype_id)

    n_sections = max(1, len(outline.get("sections", [])))
    total_word_target = target_minutes * WORDS_PER_MINUTE
    # Hook + conclusion ~75 words each; remainder split across sections.
    words_per_segment = max(100, (total_word_target - 150) // n_sections)

    prompt = compose_script_prompt(
        base,
        channel_content,
        script_module,
        topic=topic,
        target_minutes=target_minutes,
        total_word_target=total_word_target,
        words_per_segment=words_per_segment,
        hook_archetype_block=hook_archetype_block,
        additional_instructions=additional_instructions,
        sample_script=sample_script,
    )

    with client.messages.stream(
        model="claude-opus-4-7",
        max_tokens=8192,
        thinking={"type": "adaptive"},
        output_config={"format": {"type": "json_schema", "schema": SCRIPT_SCHEMA}},
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

    text = next((b.text for b in response.content if b.type == "text"), None)
    if text is None:
        raise RuntimeError(
            f"No text block in Claude response; block types present: "
            f"{[b.type for b in response.content]}"
        )
    return json.loads(text)


def save_script_draft(project_name, script_draft):
    folder = f"../projects/{project_name}"
    os.makedirs(folder, exist_ok=True)
    with open(f"{folder}/script_draft.json", "w") as f:
        json.dump(script_draft, f, indent=2)


def load_script_draft(project_name):
    with open(
        f"../projects/{project_name}/script_draft.json",
        "r"
    ) as f:
        return json.load(f)
