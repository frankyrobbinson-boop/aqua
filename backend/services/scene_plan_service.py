import json
import os
import re
from dotenv import load_dotenv
from openai import OpenAI

from services import cost_ledger
from services.paths import PROJECTS_ROOT
from services.research_service import load_research
from services.script_draft_service import load_script_draft

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

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
                    "on_screen_text": {"type": "string"},
                    "visual_mode": {
                        "type": "string",
                        "enum": ["stock_video", "ai_image"],
                    }
                },
                "required": [
                    "id",
                    "segment_id",
                    "segment_title",
                    "narration",
                    "emotional_purpose",
                    "visual_description",
                    "on_screen_text",
                    "visual_mode",
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

    # Force valid JSON via OpenAI structured outputs (strict json_schema),
    # mirroring research_service / outline_service / visual_prompt_service. The
    # scene_plan prompt is the model's instruction set; the full script draft is
    # the input. GPT-5 handles this structured creative task (a visual concept
    # per narration beat) well.
    response = client.responses.create(
        model="gpt-5",
        instructions=prompt,
        input=f"SCRIPT:\n{json.dumps(script, indent=2)}",
        text={
            "format": {
                "type": "json_schema",
                "name": "scene_plan",
                "schema": SCENE_PLAN_SCHEMA,
                "strict": True,
            }
        },
    )

    usage = getattr(response, "usage", None)
    in_tok = getattr(usage, "input_tokens", 0) if usage else 0
    out_tok = getattr(usage, "output_tokens", 0) if usage else 0
    cost_ledger.record(
        project_name,
        stage="scene_plan",
        provider="openai",
        model="gpt-5",
        input_tokens=in_tok,
        output_tokens=out_tok,
    )

    text = response.output_text.strip()
    # Strip markdown code fences that models sometimes wrap around JSON output.
    if text.startswith("```"):
        text = re.sub(r'^```(?:json)?\s*\n?', '', text)
        text = re.sub(r'\n?```\s*$', '', text)
    text = text.strip()
    # Pull the outermost {...} block out in case GPT-5 adds prose around the
    # JSON despite the schema. re.DOTALL lets `.` span newlines.
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        text = match.group(0)
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        # Surface status + the text head/tail so parse failures are debuggable
        # (mirrors research / outline / visual_prompt).
        status = getattr(response, "status", "?")
        head = text[:400]
        tail = text[-400:] if len(text) > 800 else ""
        raise RuntimeError(
            f"Scene plan JSON did not parse (status={status}, "
            f"text_len={len(text)}, error={e!r}).\n"
            f"--- first 400 chars ---\n{head}\n"
            f"--- last 400 chars ---\n{tail}"
        ) from e


def save_scene_plan(project_name, scene_plan):

    folder = PROJECTS_ROOT / project_name

    folder.mkdir(parents=True, exist_ok=True)

    with (folder / "scene_plan.json").open("w") as f:
        json.dump(scene_plan, f, indent=2)
