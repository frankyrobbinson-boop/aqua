from dotenv import load_dotenv
from openai import OpenAI
import os
import json
import re
from services import cost_ledger
from services.channel_registry import resolve_channel
from services.paths import PROJECTS_ROOT
from services.research_filters import strip_research_sources
from services.research_service import load_research
from services.video_type_registry import (
    compose_outline_prompt,
    load_core,
    resolve_modules,
)

load_dotenv()

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY")
)


def generate_outline(
    project_name,
    topic: str,
    target_minutes: int,
    channel: str | None = None,
    video_type: str | None = None,
    additional_instructions: str | None = None,
    item_count: int | None = None,
):
    research = strip_research_sources(load_research(project_name))
    channel_content = resolve_channel(channel)
    core_content = load_core()
    outline_base, _ = resolve_modules(video_type)

    prompt = compose_outline_prompt(
        outline_base,
        core_content,
        channel_content,
        topic=topic,
        target_minutes=target_minutes,
        additional_instructions=additional_instructions,
        item_count=item_count,
    )

    response = client.responses.create(
        model="gpt-5",
        max_output_tokens=8192,
        input=f"""
{prompt}

RESEARCH:
{json.dumps(research["research"], indent=2)}
"""
    )

    usage = getattr(response, "usage", None)
    in_tok = getattr(usage, "input_tokens", 0) if usage else 0
    out_tok = getattr(usage, "output_tokens", 0) if usage else 0
    cost_ledger.record(
        project_name,
        stage="outline",
        provider="openai",
        model="gpt-5",
        input_tokens=in_tok,
        output_tokens=out_tok,
    )

    text = response.output_text.strip()
    # Strip markdown code fences that models sometimes wrap around JSON output
    if text.startswith("```"):
        text = re.sub(r'^```(?:json)?\s*\n?', '', text)
        text = re.sub(r'\n?```\s*$', '', text)

    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        # Surface what the model actually returned so future parse failures are
        # debuggable. Mirrors the research / script_draft error pattern.
        status = getattr(response, "status", "?")
        head = text[:400]
        tail = text[-400:] if len(text) > 800 else ""
        raise RuntimeError(
            f"Outline JSON did not parse (status={status}, "
            f"text_len={len(text)}, error={e!r}).\n"
            f"--- first 400 chars ---\n{head}\n"
            f"--- last 400 chars ---\n{tail}"
        ) from e


def save_outline(project_name, outline):
    folder = PROJECTS_ROOT / project_name
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / "outline.json").open("w") as f:
        json.dump(outline, f, indent=2)


def load_outline(project_name):
    with (PROJECTS_ROOT / project_name / "outline.json").open("r") as f:
        return json.load(f)
