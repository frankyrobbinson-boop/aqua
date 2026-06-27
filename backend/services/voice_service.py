"""Voiceover orchestrator: dispatch each unit to its configured provider.

Reads voice units (via ``voice_prep_service``), looks up the channel's
voiceover config (via ``channel_registry.resolve_channel_voiceover``),
resolves the provider via ``voice_provider_registry``, and calls
``synth_unit`` per unit. Cache, request-id chaining, and per-segment
serialization live here; provider-specific work (SDK calls, alignment,
trimming) lives in the provider classes.

Behavioral preservation: with the default (no channel override) the orchestrator
routes every unit to ``ElevenLabsProvider`` with the same defaults the legacy
inline code used, so projects predating this refactor run exactly as before
— same timeline, same audio files, same cache compatibility.

Public surface (kept stable for existing callers in pipeline.py, run_audio.py,
test_voice.py):
    generate_audio(project_name, voice_speed=1.0, channel_id=None) -> list
    save_audio_timeline(project_name, timeline)
    load_audio_timeline(project_name) -> list
    CHUNK_GAP                                  # consumed by assembly_service
    _generate_unit(unit, audio_dir, ...)       # legacy single-unit helper
                                               # used by test_voice.py
"""

from __future__ import annotations

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from itertools import groupby
from typing import Optional

from dotenv import load_dotenv

from services.channel_registry import resolve_channel_voiceover
from services.voice_prep_service import load_voice_units
from services.voice_provider_registry import default_provider_id, get_provider

load_dotenv()

# ElevenLabs concurrency: free tier allows 2, paid tiers allow more. Default 3
# is safe on most plans. Set ELEVENLABS_CONCURRENCY to override (drop to 2 on
# free tier if you see 429s). Kept here (vs. in the provider) because it bounds
# segment-level parallelism in the orchestrator; per-provider rate caps for
# future Qwen3 providers can layer in on top.
_ELEVEN_CONCURRENCY = int(os.getenv("ELEVENLABS_CONCURRENCY", "3"))

# Silence added between chunks in the timeline (no in-audio break tag). Stays
# at module level so assembly_service can import it for video alignment.
CHUNK_GAP = 0.3

# Trim a small slice off the end of each chunk's spoken span before stamping
# timeline coords. Providers may emit a tiny artifact (lip smack, click,
# breath) after the last word's transcript-end timestamp; trimming before
# speech_end keeps that artifact out of the assembled audio. The timeline
# reflects the trimmed span, so assembly_service consumes speech_end as-is —
# no second trim downstream.
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


def _resolve_voice_config(channel_id: str | None) -> dict:
    """Look up the channel's voiceover config. Falls back to ALL defaults
    (provider=elevenlabs) when the channel has no voiceover block yet —
    preserves pre-refactor behavior for projects that predate the channel
    preset's voiceover field."""
    try:
        return resolve_channel_voiceover(channel_id)
    except ValueError:
        # Unknown / unset channel — return defaults so the legacy hardcoded
        # ElevenLabs path keeps working without forcing every caller to
        # thread a channel_id through.
        from services.channel_registry import _VOICEOVER_DEFAULTS
        return dict(_VOICEOVER_DEFAULTS)


# ---------------------------------------------------------------------------
# Legacy single-unit helper (test_voice.py imports this directly)
# ---------------------------------------------------------------------------

def _generate_unit(
    unit: dict,
    audio_dir: str,
    voice_speed: float = 1.0,
    previous_text: str = "",
    next_text: str = "",
    previous_request_id: str = "",
) -> dict:
    """Backward-compatible wrapper around ``ElevenLabsProvider.synth_unit``.

    ``audio_dir`` is accepted for signature compatibility but ignored — the
    provider derives its own canonical path from ``project_name``. We extract
    the project name from the conventional ``../projects/<name>/audio`` path
    so existing callers keep working.

    Used by ``test_voice.py``'s --hook path; not used by the orchestrator
    itself (which goes through the registry directly).
    """
    project_name = _infer_project_name(audio_dir)
    provider = get_provider(default_provider_id())
    voice_config = _resolve_voice_config(None)
    return provider.synth_unit(
        project_name=project_name,
        unit=unit,
        voice_config=voice_config,
        voice_speed=voice_speed,
        previous_text=previous_text,
        next_text=next_text,
        previous_request_id=previous_request_id,
    )


def _infer_project_name(audio_dir: str) -> str:
    """Extract the project name from a ``../projects/<name>/audio[/]`` path.
    Tolerant of trailing slash. Raises ValueError if the path doesn't look
    like the conventional layout."""
    norm = os.path.normpath(audio_dir).replace("\\", "/")
    parts = norm.split("/")
    try:
        idx = parts.index("projects")
    except ValueError as e:
        raise ValueError(
            f"Cannot infer project name from audio_dir={audio_dir!r}; "
            f"expected '.../projects/<name>/audio'"
        ) from e
    if idx + 1 >= len(parts):
        raise ValueError(
            f"audio_dir={audio_dir!r} has no project name after 'projects/'"
        )
    return parts[idx + 1]


# ---------------------------------------------------------------------------
# Public orchestrator
# ---------------------------------------------------------------------------

def generate_audio(
    project_name: str,
    voice_speed: float = 1.0,
    channel_id: str | None = None,
) -> list:
    """Synthesize every voice unit + build the timeline.

    Channel routing: if ``channel_id`` is None, falls back to all-defaults
    voiceover config (provider=elevenlabs). Once the channel preset gains a
    voiceover block, callers can pass channel_id to honor it. The
    pipeline/run_audio entrypoints don't pass it yet — that wiring is a
    future phase. Behavior is unchanged today.
    """
    units = load_voice_units(project_name)
    audio_dir = f"../projects/{project_name}/audio"
    os.makedirs(audio_dir, exist_ok=True)

    voice_config = _resolve_voice_config(channel_id)
    provider_id = voice_config.get("provider") or default_provider_id()
    provider = get_provider(provider_id)

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
            entry = provider.synth_unit(
                project_name=project_name,
                unit=unit,
                voice_config=voice_config,
                voice_speed=voice_speed,
                previous_text=contexts[idx]["previous_text"],
                next_text=contexts[idx]["next_text"],
                previous_request_id=prev_request_id,
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
        # Trim before the last word's transcript-end to drop provider artifacts.
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
