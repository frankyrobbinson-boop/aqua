"""Voiceover stage: tts_prep → voice_prep → delivery_plan → ElevenLabs audio.

Re-runs tts_prep from the current script_draft.json every time, so script edits
flow through. Scene planning + scene-window timing live in the visuals stage now.

    python run_audio.py <project_name>
"""

import json
import os
import sys

from services.stage_graph import missing_inputs
from services.tts_prep_service import generate_tts_prep, save_tts_prep
from services.voice_prep_service import build_voice_units, save_voice_units
from services.delivery_plan_service import build_delivery_plan
from services.voice_service import generate_audio, save_audio_timeline


def _load_voice_speed(project_name: str) -> float:
    """Read voice_speed from script_config.json (default 1.0)."""
    path = f"../projects/{project_name}/script_config.json"
    if not os.path.exists(path):
        return 1.0
    try:
        with open(path) as f:
            config = json.load(f)
        return float(config.get("voice_speed") or 1.0)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return 1.0


def _check_inputs(project_name: str):
    folder = f"../projects/{project_name}"
    if not os.path.isdir(folder):
        raise FileNotFoundError(
            f"Project folder not found: {folder}. "
            "Run run_script_only.py first."
        )
    missing = missing_inputs(folder, "voiceover")
    if missing:
        raise FileNotFoundError(
            f"Project '{project_name}' missing required artifacts: {missing}. "
            "Run run_script_only.py first to produce them."
        )


def run_audio(project_name: str):
    _check_inputs(project_name)
    voice_speed = _load_voice_speed(project_name)

    print(f"\n[1/4] TTS prep (expand numbers, add breaks)...")
    tts_script = generate_tts_prep(project_name)
    save_tts_prep(project_name, tts_script)
    print("      tts_script saved")

    print("\n[2/4] Voice units...")
    voice_units = build_voice_units(project_name)
    save_voice_units(project_name, voice_units)
    print(f"      {len(voice_units)} units")

    print("\n[3/4] Delivery plan...")
    annotated = build_delivery_plan(project_name)
    save_voice_units(project_name, annotated)

    print(f"\n[4/4] Generating audio (ElevenLabs, speed {voice_speed}x)...")
    timeline = generate_audio(project_name, voice_speed=voice_speed)
    save_audio_timeline(project_name, timeline)
    total = timeline[-1]["timeline_end"]
    print(f"      audio saved, total {total:.1f}s ({total/60:.1f} min)")

    print(f"\nDONE: ../projects/{project_name}/")
    print("Next: python run_visuals.py", project_name)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    run_audio(sys.argv[1])
