from dotenv import load_dotenv
import json
import os
import re
from pathlib import Path

from openai import OpenAI

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Path is relative to the backend/ working directory, matching the rest of the
# prompt-loading conventions in this package.
_RESEARCH_PROMPT_PATH = Path("prompts/research.md")


def _load_research_prompt() -> str:
    return _RESEARCH_PROMPT_PATH.read_text()


def generate_research(topic: str, pre_research: str | None = None) -> dict:
    """Structured research for `topic`. Returns the parsed JSON described in
    prompts/research.md (summary, key_facts, statistics, interesting_angles,
    controversies, open_questions)."""
    instructions = _load_research_prompt()
    user_input = f"Topic: {topic}"
    if pre_research and pre_research.strip():
        user_input += (
            "\n\nPre-research notes — use these as a starting point:\n\n"
            f"{pre_research.strip()}"
        )

    response = client.responses.create(
        model="gpt-5",
        instructions=instructions,
        input=user_input,
    )

    text = response.output_text.strip()
    # Strip markdown code fences that models sometimes wrap around JSON output.
    if text.startswith("```"):
        text = re.sub(r'^```(?:json)?\s*\n?', '', text)
        text = re.sub(r'\n?```\s*$', '', text)
    return json.loads(text.strip())


def save_research(project_name, content):
    folder = f"../projects/{project_name}"
    os.makedirs(folder, exist_ok=True)
    with open(f"{folder}/research.json", "w") as f:
        json.dump(content, f, indent=2)


def load_research(project_name):
    with open(f"../projects/{project_name}/research.json", "r") as f:
        return json.load(f)


def slugify(text):
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    result = text.strip("-")
    if not result:
        raise ValueError(
            "Topic produces an empty project name; "
            "use a topic with at least one letter or digit"
        )
    return result
