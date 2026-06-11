import json
import os
from dotenv import load_dotenv
import anthropic

from services.outline_service import load_outline
from services.research_service import load_research

load_dotenv()

client = anthropic.Anthropic(
    api_key=os.getenv("ANTHROPIC_API_KEY")
)

SCRIPT_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "hook": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "duration_seconds": {"type": "number"}
            },
            "required": ["text", "duration_seconds"],
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
                "text": {"type": "string"},
                "cta": {"type": "string"}
            },
            "required": ["text", "cta"],
            "additionalProperties": False
        }
    },
    "required": ["title", "hook", "segments", "conclusion"],
    "additionalProperties": False
}


def load_script_draft_prompt():
    with open("prompts/script_draft.md", "r") as f:
        return f.read()


def generate_script_draft(project_name):

    outline = load_outline(project_name)
    research = load_research(project_name)
    prompt = load_script_draft_prompt()

    with client.messages.stream(
        model="claude-opus-4-7",
        max_tokens=4096,
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
{research["research"]}
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