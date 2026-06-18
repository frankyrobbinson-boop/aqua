#!/usr/bin/env python3
"""
ElevenLabs voice generation test.
Runs against a project that has a finished script_draft.json.

Usage:
  python test_voice.py            # prep only — no API call, free
  python test_voice.py --hook     # generate hook audio only (~25s, cheapest real test)
  python test_voice.py --full     # generate all units (~5 min of audio)
"""

import argparse
import json
import os
import sys

# Ensure imports resolve from the backend directory
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

PROJECT = "why-potatoes-were-so-common-to-eat-a-few-hundred-years-ago"

# ── helpers ───────────────────────────────────────────────────────────────────

def _check_env():
    key = os.getenv("ELEVENLABS_API_KEY")
    voice = os.getenv("ELEVENLABS_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb")
    if not key:
        print("ERROR: ELEVENLABS_API_KEY not set in .env")
        sys.exit(1)
    print(f"API key: {'*' * (len(key) - 4)}{key[-4:]}")
    print(f"Voice ID: {voice}\n")


def _print_timeline_summary(timeline: list):
    print("\nTimeline:")
    for entry in timeline:
        bar_len = int(entry["duration"] / 0.5)
        bar = "█" * min(bar_len, 40)
        print(
            f"  [{entry['segment_id']}] {entry['title'][:28]:28}  "
            f"{entry['timeline_start']:5.1f}s – {entry['timeline_end']:5.1f}s  "
            f"({entry['duration']:.1f}s)  {bar}"
        )
    total = timeline[-1]["timeline_end"]
    print(f"\n  Total: {total:.1f}s  ({total / 60:.1f} min)")


def _print_words(words: list, n: int = 6):
    print(f"\n  First {n} words:")
    for w in words[:n]:
        print(f"    {w['word']:20}  {w['start']:.3f}s → {w['end']:.3f}s")
    if len(words) > n:
        last = words[-1]
        print(f"    ...({len(words) - n} more)...")
        print(f"    {last['word']:20}  {last['start']:.3f}s → {last['end']:.3f}s  (last)")


# ── stages ────────────────────────────────────────────────────────────────────

def run_prep():
    """Build voice units from tts_script.json. No API call."""
    from services.voice_prep_service import build_voice_units, save_voice_units

    print("=" * 60)
    print("STAGE: Voice Prep (no API call)")
    print("=" * 60)

    units = build_voice_units(PROJECT)
    save_voice_units(PROJECT, units)

    print(f"\nBuilt {len(units)} voice units:\n")
    for u in units:
        words = len(u["text"].split())
        print(f"  [{u['id']}] {u['type'].upper()}: {u['title']}")
        print(f"       {words} words")
        print(f"       {u['text'][:90]}{'...' if len(u['text']) > 90 else ''}")
        print()

    print(f"Saved → ../projects/{PROJECT}/voice_units.json")


def run_annotate():
    """Run delivery plan annotation on all voice units (Claude, no ElevenLabs)."""
    from services.delivery_plan_service import build_delivery_plan
    from services.voice_prep_service import save_voice_units

    print("\n" + "=" * 60)
    print("STAGE: Delivery Plan Annotation")
    print("=" * 60)

    annotated = build_delivery_plan(PROJECT)
    save_voice_units(PROJECT, annotated)

    hook = next(u for u in annotated if u["type"] == "hook")
    print(f"\nHook SSML preview:\n")
    print(f"  {hook['ssml'][:300]}...")
    print(f"\nAll units annotated and saved.")


def run_hook():
    """Generate audio for the hook only — cheapest real ElevenLabs test."""
    from services.voice_prep_service import load_voice_units
    from services.voice_service import _generate_unit

    print("\n" + "=" * 60)
    print("STAGE: Hook Audio Generation (ElevenLabs)")
    print("=" * 60)
    _check_env()

    units = load_voice_units(PROJECT)
    hook = next(u for u in units if u["type"] == "hook")

    print(f"Text ({len(hook['text'].split())} words):")
    print(f"  {hook['text']}\n")
    print("Sending to ElevenLabs...")

    audio_dir = f"../projects/{PROJECT}/audio"
    os.makedirs(audio_dir, exist_ok=True)

    entry = _generate_unit(hook, audio_dir)

    filepath = os.path.join(audio_dir, entry["audio_file"])
    size_kb = os.path.getsize(filepath) / 1024

    print(f"\n  Audio file:  {entry['audio_file']}  ({size_kb:.1f} KB)")
    print(f"  Duration:    {entry['duration']:.3f}s")
    print(f"  Words found: {len(entry['words'])}")

    _print_words(entry["words"])

    print(f"\nPlay it:")
    print(f"  open ../projects/{PROJECT}/audio/{entry['audio_file']}")


def run_full():
    """Generate audio for all voice units and build audio_timeline.json."""
    from services.voice_service import generate_audio, save_audio_timeline

    print("\n" + "=" * 60)
    print("STAGE: Full Audio Generation (ElevenLabs)")
    print("=" * 60)
    _check_env()

    timeline = generate_audio(PROJECT)
    save_audio_timeline(PROJECT, timeline)

    _print_timeline_summary(timeline)

    print(f"\nSaved → ../projects/{PROJECT}/audio_timeline.json")
    print(f"Audio  → ../projects/{PROJECT}/audio/")


# ── main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--annotate", action="store_true", help="Run delivery plan annotation only (Claude, no ElevenLabs)")
    group.add_argument("--hook", action="store_true", help="Annotate then generate hook audio only (cheapest real test)")
    group.add_argument("--full", action="store_true", help="Annotate then generate all voice units")
    args = parser.parse_args()

    if args.annotate:
        run_prep()
        run_annotate()
    elif args.hook:
        run_prep()
        run_annotate()
        run_hook()
    elif args.full:
        run_prep()
        run_annotate()
        run_full()
    else:
        run_prep()
        print("\nDry run complete. No API credits used.")
        print("\nNext steps:")
        print("  python test_voice.py --annotate  # add SSML pauses via Claude (no ElevenLabs)")
        print("  python test_voice.py --hook      # annotate + generate hook audio (~25s)")
        print("  python test_voice.py --full      # annotate + generate all units (~5 min)")
