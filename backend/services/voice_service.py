import base64
import json
import os
import re
from dotenv import load_dotenv
from elevenlabs.client import ElevenLabs
from elevenlabs import VoiceSettings

from services.voice_prep_service import load_voice_units

load_dotenv()

client = ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"))
VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb")  # default: George
MODEL_ID = os.getenv("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2")

# Fixed across every chunk so prosody stays consistent throughout the video
SEED = 42
VOICE_SETTINGS = VoiceSettings(
    stability=0.5,
    similarity_boost=0.75,
    style=0.0,
    use_speaker_boost=True,
)

CHUNK_GAP = 0.3  # silence added between chunks in the timeline (no in-audio break tag)


def _tail_sentences(unit: dict, n: int = 2) -> str:
    """Last N sentences of a unit as plain text — used as previous_text context."""
    plain = re.sub(r'<[^>]+>', '', unit["text"]).strip()
    sentences = re.split(r'(?<=[.!?])\s+', plain)
    return ' '.join(sentences[-n:]).strip()


def _head_sentences(unit: dict, n: int = 2) -> str:
    """First N sentences of a unit as plain text — used as next_text context."""
    plain = re.sub(r'<[^>]+>', '', unit["text"]).strip()
    sentences = re.split(r'(?<=[.!?])\s+', plain)
    return ' '.join(sentences[:n]).strip()


def _chars_to_words(characters: list, start_times: list, end_times: list) -> list:
    """Aggregate character-level alignment to word-level timestamps (seconds).
    Characters inside SSML tags (<...>) are skipped entirely."""
    words = []
    current_word = ""
    word_start = None
    in_tag = False

    for i, char in enumerate(characters):
        if char == "<":
            in_tag = True
            if current_word:
                words.append({
                    "word": current_word,
                    "start": round(word_start, 3),
                    "end": round(end_times[i - 1], 3)
                })
                current_word = ""
                word_start = None
        elif char == ">":
            in_tag = False
        elif in_tag:
            pass
        elif char in (" ", "\n"):
            if current_word:
                words.append({
                    "word": current_word,
                    "start": round(word_start, 3),
                    "end": round(end_times[i - 1], 3)
                })
                current_word = ""
                word_start = None
        else:
            if not current_word:
                word_start = start_times[i]
            current_word += char

    if current_word:
        words.append({
            "word": current_word,
            "start": round(word_start, 3),
            "end": round(end_times[-1], 3)
        })

    return words


def _generate_unit(
    unit: dict,
    audio_dir: str,
    previous_text: str = "",
    next_text: str = "",
    previous_request_id: str = "",
) -> dict:
    filename = f"audio_{unit['id']:02d}_{unit['type']}.mp3"
    filepath = os.path.join(audio_dir, filename)
    cache_path = filepath.replace(".mp3", ".json")

    tts_text = unit.get("ssml", unit["text"])
    seed = unit.get("seed", SEED)  # per-chunk override: set "seed" on the unit to force a different take

    if os.path.exists(filepath) and os.path.exists(cache_path):
        with open(cache_path) as f:
            cached = json.load(f)
        if cached.get("tts_source") == tts_text and cached.get("seed") == seed:
            return cached

    kwargs = dict(
        voice_id=VOICE_ID,
        text=tts_text,
        model_id=MODEL_ID,
        output_format="mp3_44100_128",
        apply_text_normalization="off",
        previous_text=previous_text,
        next_text=next_text,
        seed=seed,
        voice_settings=VOICE_SETTINGS,
    )
    if previous_request_id:
        kwargs["previous_request_ids"] = [previous_request_id]

    # Use with_raw_response to capture the request ID for subsequent stitching
    request_id = ""
    try:
        raw = client.text_to_speech.with_raw_response.convert_with_timestamps(**kwargs)
        request_id = raw.headers.get("request-id") or raw.headers.get("x-request-id") or ""
        response = raw.parse()
    except Exception as exc:
        print(f"  WARNING: with_raw_response failed for {unit['title']!r} ({exc!r}); "
              f"retrying without request_id — prosody stitching disabled for this chunk")
        response = client.text_to_speech.convert_with_timestamps(**kwargs)

    audio_bytes = base64.b64decode(response.audio_base_64)
    with open(filepath, "wb") as f:
        f.write(audio_bytes)

    alignment = response.alignment
    words = _chars_to_words(
        alignment.characters,
        alignment.character_start_times_seconds,
        alignment.character_end_times_seconds
    )

    duration = round(alignment.character_end_times_seconds[-1], 3)

    # Tripwire: warn if the file has more than 1s of trailing silence beyond the last spoken word.
    # Causes: bad break tags (e.g. time="zero.7s"), breaks at chunk edges, prompt regressions.
    # Uses afinfo (macOS) for real VBR duration; skips silently on other platforms.
    speech_end = words[-1]["end"] if words else duration
    try:
        import subprocess, re as _re
        out = subprocess.check_output(["afinfo", filepath], stderr=subprocess.STDOUT).decode()
        m = _re.search(r"estimated duration: ([\d.]+)", out)
        if m:
            file_duration = float(m.group(1))
            if file_duration - speech_end > 1.0:
                print(f"  WARNING [{unit['title']}]: {file_duration - speech_end:.1f}s trailing silence "
                      f"(speech {speech_end:.1f}s, file {file_duration:.1f}s) — check break tags")
    except Exception:
        pass

    result = {
        "segment_id": unit["id"],
        "type": unit["type"],
        "title": unit["title"],
        "text": unit["text"],
        "audio_file": filename,
        "duration": duration,
        "words": words,
        "tts_source": tts_text,
        "seed": seed,
        "request_id": request_id,
    }

    with open(cache_path, "w") as f:
        json.dump(result, f, indent=2)

    return result


def generate_audio(project_name: str) -> list:
    units = load_voice_units(project_name)
    audio_dir = f"../projects/{project_name}/audio"
    os.makedirs(audio_dir, exist_ok=True)

    timeline = []
    cursor = 0.0

    prev_request_id = ""

    for i, unit in enumerate(units):
        print(f"  Generating: {unit['title']}...")

        prev_unit = units[i - 1] if i > 0 else None
        next_unit = units[i + 1] if i < len(units) - 1 else None

        # Reset stitching at segment boundaries — carrying prosody across segments
        # causes the delivery style of one segment's ending to bleed into the next.
        # Use segment_key (index-based) rather than title to handle duplicate titles.
        same_segment = prev_unit and prev_unit.get("segment_key") == unit.get("segment_key")
        if not same_segment:
            prev_request_id = ""

        previous_text = _tail_sentences(prev_unit) if prev_unit else ""
        next_text = _head_sentences(next_unit) if next_unit else ""

        entry = _generate_unit(unit, audio_dir, previous_text, next_text, prev_request_id)
        prev_request_id = entry.get("request_id", "")

        words = entry["words"]
        speech_start = words[0]["start"] if words else 0.0
        speech_end = words[-1]["end"] if words else entry["duration"]
        speech_duration = speech_end - speech_start

        # assembly_service trims leading silence via inpoint, so speech starts exactly
        # at cursor in the assembled file — no speech_start offset in timeline coords.
        entry["timeline_start"] = round(cursor, 3)
        entry["timeline_end"] = round(cursor + speech_duration, 3)
        entry["speech_start"] = round(speech_start, 3)
        entry["speech_end"] = round(speech_end, 3)

        for word in words:
            word["global_start"] = round(word["start"] - speech_start + cursor, 3)
            word["global_end"] = round(word["end"] - speech_start + cursor, 3)

        cursor += speech_duration + CHUNK_GAP

        timeline.append(entry)

    return timeline


def save_audio_timeline(project_name: str, timeline: list):
    folder = f"../projects/{project_name}"
    with open(f"{folder}/audio_timeline.json", "w") as f:
        json.dump(timeline, f, indent=2)


def load_audio_timeline(project_name: str) -> list:
    with open(f"../projects/{project_name}/audio_timeline.json", "r") as f:
        return json.load(f)
