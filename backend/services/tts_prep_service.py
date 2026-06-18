import json
import os
from dotenv import load_dotenv
import anthropic

from services.script_draft_service import load_script_draft, SCRIPT_SCHEMA

load_dotenv()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

PROMPT = """You are a TTS (text-to-speech) script editor preparing a YouTube narration for spoken delivery.

Rewrite each text field so it sounds natural when read aloud:

1. Expand all numerals to words: "2026" → "twenty twenty-six", "104" → "one hundred and four", "$3 billion" → "three billion dollars"
2. Replace symbols: "&" → "and", "%" → "percent"
3. Expand unpronounceable abbreviations: "vs." → "versus", "approx." → "approximately", "TBA" → "to be announced"
4. Leave pronounceable acronyms as-is: FIFA, NFL, VAR, USA, UK, AI
5. Break any sentence over 25 words into two shorter ones at a natural clause boundary
6. Add <break time="0.7s"/> directly before a key reveal or directly after a punchy one-liner that needs to land — maximum 2–3 per segment; rely on punctuation for everything else; too many breaks causes ElevenLabs artifacts
7. Never change facts, names, numbers (once expanded), or the meaning of any sentence
8. Return the exact same JSON structure — only rewrite the text fields"""


def generate_tts_prep(project_name: str) -> dict:
    script = load_script_draft(project_name)

    with client.messages.stream(
        model="claude-opus-4-7",
        max_tokens=4096,
        output_config={"format": {"type": "json_schema", "schema": SCRIPT_SCHEMA}},
        messages=[{
            "role": "user",
            "content": f"{PROMPT}\n\nSCRIPT:\n{json.dumps(script, indent=2)}"
        }],
    ) as stream:
        response = stream.get_final_message()

    text = next((b.text for b in response.content if b.type == "text"), None)
    if text is None:
        raise RuntimeError(
            f"No text block in Claude response; block types present: "
            f"{[b.type for b in response.content]}"
        )
    return json.loads(text)


def save_tts_prep(project_name: str, tts_script: dict):
    folder = f"../projects/{project_name}"
    os.makedirs(folder, exist_ok=True)
    with open(f"{folder}/tts_script.json", "w") as f:
        json.dump(tts_script, f, indent=2)


def load_tts_prep(project_name: str) -> dict:
    with open(f"../projects/{project_name}/tts_script.json") as f:
        return json.load(f)
