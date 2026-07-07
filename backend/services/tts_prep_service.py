import json
import os
from dotenv import load_dotenv
import anthropic

from services import cost_ledger
from services.paths import PROJECTS_ROOT
from services.script_draft_service import load_script_draft, SCRIPT_SCHEMA

load_dotenv()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

PROMPT = """You are a TTS (text-to-speech) script editor preparing a YouTube narration for spoken delivery. This is a mechanical pass, not a rewrite — apply ONLY the edits below to each text field.

1. CRITICAL — preserve the narration's words EXACTLY. Do not add, delete, reorder, substitute, merge, split, or rephrase ANY word. The ONLY permitted modifications are: (a) expanding standalone numerals to their spoken words, and (b) inserting <break time="0.7s"/> tags. The sequence of spoken words must be identical to the script (aside from number expansion).
2. Expand a standalone numeral to its spoken words: "104" → "one hundred and four"; a four-digit year like "2026" → "twenty twenty-six". Leave a number exactly as written when it is attached to a currency symbol ($, £, €), a percent sign (%), or letters — e.g. "$3", "5%", "104th", and "3D" all stay as written. Do NOT expand or replace any symbol or abbreviation: "&", "%", "$", "vs.", "approx.", "TBA", and acronyms such as FIFA, NFL, USA, and AI all stay exactly as written.
3. You may insert <break time="0.7s"/> tags for pacing — directly before a key reveal or directly after a punchy one-liner that needs to land. Maximum 2–3 per segment; rely on punctuation for everything else, since too many breaks cause ElevenLabs artifacts. For a long sentence you may insert a <break> at a natural clause boundary — but NEVER split it into separate sentences, and NEVER add, remove, or change any word to do so.
4. Return the exact same JSON structure — only edit the text fields, and only as permitted above."""


def generate_tts_prep(project_name: str) -> dict:
    script = load_script_draft(project_name)

    # max_tokens must comfortably exceed the FULL rewritten script — every
    # text field comes back transformed, so output is roughly the same size as
    # input plus a little (numbers expand: "2026" → "twenty twenty-six" grows).
    # A 10-min script can be ~5K tokens of JSON; 16K leaves a safe margin.
    # Old default of 4096 silently truncated on anything over ~600 words.
    with client.messages.stream(
        # Mechanical rewrite (expand numerals, replace symbols, split long
        # sentences, insert breaks) — no Opus-level reasoning needed. Haiku 4.5
        # handles JSON-schema enforcement identically and is ~15x cheaper here.
        model="claude-haiku-4-5-20251001",
        max_tokens=16384,
        output_config={"format": {"type": "json_schema", "schema": SCRIPT_SCHEMA}},
        messages=[{
            "role": "user",
            "content": f"{PROMPT}\n\nSCRIPT:\n{json.dumps(script, indent=2)}"
        }],
    ) as stream:
        response = stream.get_final_message()

    usage = getattr(response, "usage", None)
    in_tok = getattr(usage, "input_tokens", 0) if usage else 0
    out_tok = getattr(usage, "output_tokens", 0) if usage else 0
    cost_ledger.record(
        project_name,
        stage="tts_prep",
        provider="anthropic",
        model="claude-haiku-4-5-20251001",
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
        # Surface stop_reason + the text head/tail so truncation failures are
        # debuggable (mirrors the ffmpeg-stderr and script_draft fixes).
        stop_reason = getattr(response, "stop_reason", "?")
        head = text[:400]
        tail = text[-400:] if len(text) > 800 else ""
        raise RuntimeError(
            f"TTS-prep JSON did not parse (stop_reason={stop_reason}, "
            f"text_len={len(text)}, error={e!r}).\n"
            f"--- first 400 chars ---\n{head}\n"
            f"--- last 400 chars ---\n{tail}"
        ) from e


def save_tts_prep(project_name: str, tts_script: dict):
    folder = PROJECTS_ROOT / project_name
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / "tts_script.json").open("w") as f:
        json.dump(tts_script, f, indent=2)


def load_tts_prep(project_name: str) -> dict:
    with (PROJECTS_ROOT / project_name / "tts_script.json").open() as f:
        return json.load(f)
