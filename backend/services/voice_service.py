import base64
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from itertools import groupby
from typing import Optional

from dotenv import load_dotenv
from elevenlabs.client import ElevenLabs
from elevenlabs import VoiceSettings

from services.voice_prep_service import load_voice_units

# ElevenLabs concurrency: free tier allows 2, paid tiers allow more. Default 3
# is safe on most plans. Set ELEVENLABS_CONCURRENCY to override (drop to 2 on
# free tier if you see 429s).
_ELEVEN_CONCURRENCY = int(os.getenv("ELEVENLABS_CONCURRENCY", "3"))

load_dotenv()

client = ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"))
VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb")  # default: George
MODEL_ID = os.getenv("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2")

# Fixed across every chunk so prosody stays consistent throughout the video
SEED = 42

# ElevenLabs `speed` accepts ~0.7–1.2; clamp to a safer 0.8–1.2 range and treat
# anything else as 1.0 to avoid request rejections.
_SPEED_MIN, _SPEED_MAX = 0.8, 1.2


def _voice_settings(speed: float = 1.0) -> VoiceSettings:
    """Build a VoiceSettings with the given speed; other params are fixed so
    voice character stays consistent across runs."""
    speed = max(_SPEED_MIN, min(_SPEED_MAX, float(speed)))
    return VoiceSettings(
        stability=0.5,
        similarity_boost=0.75,
        style=0.0,
        use_speaker_boost=True,
        speed=speed,
    )


CHUNK_GAP = 0.3  # silence added between chunks in the timeline (no in-audio break tag)

# Trim a small slice off the end of each chunk's spoken span before stamping
# timeline coords. ElevenLabs occasionally emits a tiny artifact (lip smack,
# click, breath) after the last word's transcript-end timestamp; trimming
# before speech_end keeps that artifact out of the assembled audio. The
# timeline reflects the trimmed span, so assembly_service consumes
# speech_end as-is — no second trim downstream.
TRAILING_TRIM = 0.03


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
    voice_speed: float = 1.0,
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
        # Cache key includes voice_speed so a speed change forces regeneration.
        if (
            cached.get("tts_source") == tts_text
            and cached.get("seed") == seed
            and cached.get("voice_speed", 1.0) == voice_speed
        ):
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
        voice_settings=_voice_settings(voice_speed),
    )
    if previous_request_id:
        kwargs["previous_request_ids"] = [previous_request_id]

    # Use with_raw_response to capture the request ID for subsequent stitching
    request_id = ""
    try:
        raw = client.text_to_speech.with_raw_response.convert_with_timestamps(**kwargs)
        request_id = raw.headers.get("request-id") or raw.headers.get("x-request-id") or ""
        response = raw.data
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
        "voice_speed": voice_speed,
        "request_id": request_id,
    }

    with open(cache_path, "w") as f:
        json.dump(result, f, indent=2)

    return result


def generate_audio(project_name: str, voice_speed: float = 1.0) -> list:
    units = load_voice_units(project_name)
    audio_dir = f"../projects/{project_name}/audio"
    os.makedirs(audio_dir, exist_ok=True)

    # Pre-compute previous_text/next_text for every unit from global neighbors.
    # These are prosody HINTS only (not spoken), so segment boundaries can still
    # share neighbor context across the boundary.
    contexts: list[dict] = []
    for i, unit in enumerate(units):
        prev_unit = units[i - 1] if i > 0 else None
        next_unit = units[i + 1] if i < len(units) - 1 else None
        contexts.append({
            "previous_text": _tail_sentences(prev_unit) if prev_unit else "",
            "next_text": _head_sentences(next_unit) if next_unit else "",
        })

    # Group unit indices by segment_key. Within a segment, units must run
    # sequentially so previous_request_id can chain (request stitching). The
    # original code already reset prev_request_id at segment boundaries, so
    # different segments are independent and run in parallel.
    segments: list[list[int]] = [
        list(group)
        for _, group in groupby(range(len(units)), key=lambda i: units[i].get("segment_key"))
    ]

    def _run_segment(seg: list[int]) -> dict[int, dict]:
        local: dict[int, dict] = {}
        prev_request_id = ""
        for idx in seg:
            unit = units[idx]
            print(f"  Generating: {unit['title']}...", flush=True)
            entry = _generate_unit(
                unit, audio_dir, voice_speed,
                contexts[idx]["previous_text"], contexts[idx]["next_text"],
                prev_request_id,
            )
            prev_request_id = entry.get("request_id", "")
            local[idx] = entry
        return local

    workers = max(1, min(_ELEVEN_CONCURRENCY, len(segments)))
    print(f"  Generating {len(segments)} segment(s) with {workers} parallel worker(s)...", flush=True)

    results: dict[int, dict] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_run_segment, seg) for seg in segments]
        first_exc: Optional[BaseException] = None
        for fut in as_completed(futures):
            try:
                results.update(fut.result())
            except BaseException as exc:
                if first_exc is None:
                    first_exc = exc
                    print(f"  ERROR in voiceover worker: {exc!r} — "
                          f"waiting for in-flight segments to settle...", flush=True)
        if first_exc is not None:
            raise first_exc

    # Walk units in ORIGINAL order to build the timeline, threading cursor
    # through. cursor is purely arithmetic — no ordering issue with parallelism.
    timeline = []
    cursor = 0.0
    for i in range(len(units)):
        entry = results[i]
        words = entry["words"]
        speech_start = words[0]["start"] if words else 0.0
        raw_speech_end = words[-1]["end"] if words else entry["duration"]
        # Trim before the last word's transcript-end to drop ElevenLabs artifacts.
        # Floor at speech_start + 0.05 so chunks with very short single-word spans
        # never collapse to <=0 duration (mirrors the safety floor assembly_service
        # used previously).
        speech_end = max(speech_start + 0.05, raw_speech_end - TRAILING_TRIM)
        speech_duration = speech_end - speech_start

        entry["timeline_start"] = round(cursor, 3)
        entry["timeline_end"] = round(cursor + speech_duration, 3)
        entry["speech_start"] = round(speech_start, 3)
        entry["speech_end"] = round(speech_end, 3)

        # Clip any word whose end exceeds the trimmed speech_end (see edge-case
        # note in plan), then stamp global_*.
        for word in words:
            if word["end"] > speech_end:
                word["end"] = speech_end
            if word["start"] > speech_end:
                word["start"] = speech_end  # zero-width; will be filtered/clamped
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
