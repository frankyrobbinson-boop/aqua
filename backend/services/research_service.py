from dotenv import load_dotenv
import json
import os
import re
from pathlib import Path

from openai import OpenAI

from services import cost_ledger
from services.paths import PROJECTS_ROOT

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Path is relative to the backend/ working directory, matching the rest of the
# prompt-loading conventions in this package.
_RESEARCH_PROMPT_PATH = Path("prompts/research.md")

AUDIENCE_SLOT = "{{AUDIENCE_BLOCK}}"


def _load_research_prompt() -> str:
    return _RESEARCH_PROMPT_PATH.read_text()


def _build_audience_block(channel: str | None) -> str:
    """Return the framing text spliced into {{AUDIENCE_BLOCK}}.

    Returns "" when channel is None so legacy callers (pipeline.py, the old
    main.py, test-research.py) keep working without modification — research
    runs in channel-agnostic mode and the slot collapses to empty.
    """
    if channel is None:
        return ""
    from services.channel_registry import resolve_channel_section
    audience = resolve_channel_section(channel, "Audience").strip()
    if not audience:
        return ""
    return (
        "Audience framing — bias your research toward what serves this viewer:\n\n"
        f"{audience}\n\n"
        "Favor facts, statistics, angles, and controversies that this audience "
        "would find surprising, useful, or emotionally resonant. Skip material "
        "they would consider obvious or off-purpose."
    )


def verify_research_slot() -> None:
    """Raise if research.md is missing the {{AUDIENCE_BLOCK}} slot."""
    text = _RESEARCH_PROMPT_PATH.read_text()
    if AUDIENCE_SLOT not in text:
        raise RuntimeError(f"research.md missing {AUDIENCE_SLOT}")


def generate_research(
    topic: str,
    pre_research: str | None = None,
    channel: str | None = None,
    project_name: str | None = None,
) -> dict:
    """Structured research for `topic`. Returns the parsed JSON described in
    prompts/research.md (summary, key_facts, statistics, interesting_angles,
    controversies, open_questions)."""
    instructions = _load_research_prompt()
    instructions = instructions.replace(AUDIENCE_SLOT, _build_audience_block(channel))
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

    if project_name:
        usage = getattr(response, "usage", None)
        in_tok = getattr(usage, "input_tokens", 0) if usage else 0
        out_tok = getattr(usage, "output_tokens", 0) if usage else 0
        cost_ledger.record(
            project_name,
            stage="research",
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
    # Extract the outermost {...} block. GPT-5 sometimes adds explanatory prose
    # before or after the JSON despite the "no extra text" instruction; this
    # regex pulls just the JSON object out so prose around it doesn't fail the
    # parse. re.DOTALL lets `.` match newlines so multi-line JSON is captured.
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        text = match.group(0)
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        # Surface what the model actually returned so future parse failures are
        # debuggable. Mirror the script_draft / tts_prep error pattern.
        head = text[:400]
        tail = text[-400:] if len(text) > 800 else ""
        raise RuntimeError(
            f"Research JSON did not parse (text_len={len(text)}, error={e!r}).\n"
            f"--- first 400 chars ---\n{head}\n"
            f"--- last 400 chars ---\n{tail}"
        ) from e


def save_research(project_name, content):
    folder = PROJECTS_ROOT / project_name
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / "research.json").open("w") as f:
        json.dump(content, f, indent=2)


def load_research(project_name):
    with (PROJECTS_ROOT / project_name / "research.json").open("r") as f:
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
