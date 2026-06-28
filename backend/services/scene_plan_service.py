import json
import os
from dotenv import load_dotenv
import anthropic

from services import cost_ledger
from services.research_service import load_research
from services.script_draft_service import load_script_draft

load_dotenv()

client = anthropic.Anthropic(
    api_key=os.getenv("ANTHROPIC_API_KEY")
)

SCENE_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "scene_intent": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "segment_id": {"type": "integer"},
                    "segment_title": {"type": "string"},
                    "narration": {"type": "string"},
                    "emotional_purpose": {"type": "string"},
                    "visual_description": {"type": "string"},
                    "on_screen_text": {"type": "string"}
                },
                "required": [
                    "id",
                    "segment_id",
                    "segment_title",
                    "narration",
                    "emotional_purpose",
                    "visual_description",
                    "on_screen_text",
                ],
                "additionalProperties": False
            }
        }
    },
    "required": ["scene_intent"],
    "additionalProperties": False
}


def load_scene_plan_prompt():
    with open("prompts/scene_plan.md", "r") as f:
        return f.read()


def generate_scene_plan(project_name):

    script = load_script_draft(project_name)
    research = load_research(project_name)
    topic = research.get("topic", script.get("title", ""))
    prompt = load_scene_plan_prompt().replace("{topic}", topic)

    with client.messages.stream(
        # Structured creative judgment (visual concept per beat) — Sonnet 4.6
        # handles this class of task well at ~5x lower cost than Opus 4.7.
        # Thinking disabled: adaptive thinking was burning the full 32K token
        # budget before any output, leaving response.content with only a
        # thinking block and no text block. Sonnet handles this structured
        # task fine without thinking; if quality drops, re-enable but cap
        # budget tightly (e.g., output_config.effort="low").
        model="claude-sonnet-4-6",
        max_tokens=32000,
        output_config={"format": {"type": "json_schema", "schema": SCENE_PLAN_SCHEMA}},
        messages=[
            {
                "role": "user",
                "content": f"""
{prompt}

SCRIPT:
{json.dumps(script, indent=2)}
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
        stage="scene_plan",
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
        )
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        # Surface stop_reason + the text head/tail so truncation failures are
        # debuggable (mirrors script_draft / tts_prep).
        stop_reason = getattr(response, "stop_reason", "?")
        head = text[:400]
        tail = text[-400:] if len(text) > 800 else ""
        raise RuntimeError(
            f"Scene plan JSON did not parse (stop_reason={stop_reason}, "
            f"text_len={len(text)}, error={e!r}).\n"
            f"--- first 400 chars ---\n{head}\n"
            f"--- last 400 chars ---\n{tail}"
        ) from e


def save_scene_plan(project_name, scene_plan):

    folder = f"../projects/{project_name}"

    os.makedirs(folder, exist_ok=True)

    with open(f"{folder}/scene_plan.json", "w") as f:
        json.dump(scene_plan, f, indent=2)
