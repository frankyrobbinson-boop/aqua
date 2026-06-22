import json
import os
from dotenv import load_dotenv
import anthropic

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
        # If scene cuts get sloppy on real videos, the next step is "keep Opus
        # but drop adaptive thinking," not a return to Opus + thinking.
        model="claude-sonnet-4-6",
        max_tokens=32000,
        thinking={"type": "adaptive"},
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

    text = next((b.text for b in response.content if b.type == "text"), None)
    if text is None:
        raise RuntimeError(
            f"No text block in Claude response; block types present: "
            f"{[b.type for b in response.content]}"
        )
    return json.loads(text)


def save_scene_plan(project_name, scene_plan):

    folder = f"../projects/{project_name}"

    os.makedirs(folder, exist_ok=True)

    with open(f"{folder}/scene_plan.json", "w") as f:
        json.dump(scene_plan, f, indent=2)
