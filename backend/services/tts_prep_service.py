"""TTS-prep: mechanical GPT-5 pass that readies the script draft for ElevenLabs.

Sanitation contract: script_draft.json on disk keeps its original punctuation —
on-screen text (chips, section cards) is sourced from it. The sanitation in this
module happens only at the TTS boundary: em/en dashes and hyphen separators are
rewritten to commas BEFORE the script is sent to GPT-5, and control characters
are scrubbed from the parsed output AFTER. Everything downstream of
generate_tts_prep (voice units → ElevenLabs → audio_timeline → subtitles)
therefore sees clean, speakable text.
"""

import json
import os
import re
from dotenv import load_dotenv
from openai import OpenAI

from services import cost_ledger
from services.paths import PROJECTS_ROOT
from services.script_draft_service import load_script_draft, SCRIPT_SCHEMA

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

PROMPT = """You are a TTS (text-to-speech) script editor preparing a YouTube narration for spoken delivery. This is a mechanical pass, not a rewrite — apply ONLY the edits below to each text field.

1. CRITICAL — preserve the narration's words EXACTLY. Do not add, delete, reorder, substitute, merge, split, or rephrase ANY word. The ONLY permitted modifications are: (a) expanding standalone numerals to their spoken words, and (b) inserting <break time="0.7s"/> tags. The sequence of spoken words must be identical to the script (aside from number expansion).
2. Expand a standalone numeral to its spoken words: "104" → "one hundred and four"; a four-digit year like "2026" → "twenty twenty-six". Leave a number exactly as written when it is attached to a currency symbol ($, £, €), a percent sign (%), or letters — e.g. "$3", "5%", "104th", and "3D" all stay as written. Do NOT expand or replace any symbol or abbreviation: "&", "%", "$", "vs.", "approx.", "TBA", and acronyms such as FIFA, NFL, USA, and AI all stay exactly as written.
3. You may insert <break time="0.7s"/> tags for pacing — directly before a key reveal or directly after a punchy one-liner that needs to land. Maximum 2–3 per segment; rely on punctuation for everything else, since too many breaks cause ElevenLabs artifacts. For a long sentence you may insert a <break> at a natural clause boundary — but NEVER split it into separate sentences, and NEVER add, remove, or change any word to do so.
4. Return the exact same JSON structure — only edit the text fields, and only as permitted above."""


def _sanitize_spoken_text(text: str) -> str:
    """Rewrite punctuation that TTS reads badly into speakable commas.

    Em/en dashes and standalone hyphen separators become ", "; the collapse
    rules then clean up any punctuation artifacts the substitution created.
    Hyphenated words ("year-old", "half-inch") and negative numbers ("-5")
    are untouched because the hyphen rule requires whitespace on BOTH sides.
    """
    # 1. Em/en dash runs, spaced or not: "word — word" / "word—word" → "word, word".
    text = re.sub(r'\s*[—–]+\s*', ', ', text)
    # 2. Standalone hyphen separators (whitespace both sides): "a -- b" → "a, b".
    text = re.sub(r'\s+-+\s+', ', ', text)
    # 3. Punctuation-artifact collapse (order matters).
    text = re.sub(r',(\s*,)+', ',', text)
    text = re.sub(r'([.!?;:])\s*,\s*', r'\1 ', text)
    text = re.sub(r',\s*([.!?;:])', r'\1', text)
    text = re.sub(r'^\s*,\s*', '', text)
    text = re.sub(r',\s*$', '', text)
    text = re.sub(r' {2,}', ' ', text)  # spaces only — leave \n and \t alone
    return text


def _scrub_control_chars(text: str) -> str:
    """Replace C0 control chars + DEL (keeping \\n and \\t) with a space.

    GPT-5 occasionally emits stray control characters; a run becomes a single
    space, then doubled spaces are collapsed.
    """
    text = re.sub(r'[\x00-\x08\x0b-\x1f\x7f]+', ' ', text)
    return re.sub(r' {2,}', ' ', text)


def _walk_strings(obj, fn):
    """Return a copy of obj with fn applied to every string value."""
    if isinstance(obj, str):
        return fn(obj)
    if isinstance(obj, dict):
        return {k: _walk_strings(v, fn) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_walk_strings(v, fn) for v in obj]
    return obj


def generate_tts_prep(project_name: str) -> dict:
    # Sanitize at the TTS boundary only — script_draft.json keeps its original
    # punctuation on disk (on-screen text is sourced from it).
    script = _walk_strings(load_script_draft(project_name), _sanitize_spoken_text)

    # max_output_tokens must comfortably exceed the FULL rewritten script — every
    # text field comes back transformed, so the visible output is roughly the
    # same size as the input plus a little (numbers expand: "2026" → "twenty
    # twenty-six" grows). A 10-min script is ~5K tokens of JSON, and GPT-5 also
    # spends reasoning tokens against this same budget, so keep it generous:
    # 32768 leaves ample room for reasoning + the full rewritten JSON. The old
    # 4096 default silently truncated on anything over ~600 words — never again.
    response = client.responses.create(
        # Mechanical rewrite (expand numerals, insert breaks) constrained by a
        # strict json_schema. GPT-5 per the model audit; the responses API +
        # structured-output idiom mirrors scene_plan_service / visual_prompt_service.
        model="gpt-5",
        instructions=PROMPT,
        input=f"SCRIPT:\n{json.dumps(script, indent=2, ensure_ascii=False)}",
        max_output_tokens=32768,
        text={
            "format": {
                "type": "json_schema",
                "name": "tts_script",
                "schema": SCRIPT_SCHEMA,
                "strict": True,
            }
        },
    )

    usage = getattr(response, "usage", None)
    in_tok = getattr(usage, "input_tokens", 0) if usage else 0
    out_tok = getattr(usage, "output_tokens", 0) if usage else 0
    cost_ledger.record(
        project_name,
        stage="tts_prep",
        provider="openai",
        model="gpt-5",
        input_tokens=in_tok,
        output_tokens=out_tok,
    )

    text = response.output_text.strip()
    # Strip markdown code fences some models wrap around JSON output.
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
        # Scrub stray control characters from the parsed output so run_audio
        # persists clean text for everything downstream (voice units →
        # ElevenLabs → audio_timeline → subtitles).
        return _walk_strings(json.loads(text), _scrub_control_chars)
    except json.JSONDecodeError as e:
        # Surface status + the text head/tail so parse failures are debuggable
        # (mirrors scene_plan / research / visual_prompt). A truncated response
        # (past the silent-truncation history above) means bump max_output_tokens.
        status = getattr(response, "status", "?")
        head = text[:400]
        tail = text[-400:] if len(text) > 800 else ""
        raise RuntimeError(
            f"TTS-prep JSON did not parse (status={status}, "
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
