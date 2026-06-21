"""Run only the cheap, text-generation portion of the pipeline:
research → outline → script_draft.

Stops before voice generation so you can read AND EDIT the script before
paying ElevenLabs. tts_prep (numeric expansion, break-tag annotation) now
runs in the voiceover stage so any edits you make to the script flow through.

    python run_script_only.py "Your topic here" [target_minutes]
"""

import json
import os
import sys

from services.research_service import generate_research, save_research, slugify
from services.outline_service import generate_outline, save_outline
from services.script_draft_service import generate_script_draft, save_script_draft


def _word_count(text: str) -> int:
    return len(text.split())


def _print_script_summary(script: dict, target_minutes: int):
    print("\n" + "=" * 70)
    print(f"TITLE: {script.get('title', '(no title)')}")
    print("=" * 70)

    total_words = 0

    hook = script["hook"]["narration"]
    total_words += _word_count(hook)
    print(f"\nHOOK  ({_word_count(hook)} words)")
    print("-" * 70)
    print(hook)

    for i, seg in enumerate(script.get("segments", []), 1):
        n = seg["narration"]
        wc = _word_count(n)
        total_words += wc
        print(f"\nSEGMENT {i}: {seg['title']}  ({wc} words)")
        print(f"  visual: {seg.get('visual_notes', '')}")
        print("-" * 70)
        print(n)

    conc = script["conclusion"]["narration"]
    total_words += _word_count(conc)
    print(f"\nCONCLUSION  ({_word_count(conc)} words)")
    print("-" * 70)
    print(conc)
    print(f"\nCTA: {script['conclusion'].get('cta', '')}")

    target_words = target_minutes * 150
    print("\n" + "=" * 70)
    print(
        f"TOTAL: {total_words} words  "
        f"(~{total_words / 150:.1f} min spoken at 150 wpm)  "
        f"target ~{target_words} words / {target_minutes} min"
    )
    print("=" * 70)


def _load_script_config(project_dir: str) -> dict:
    """Read script_config.json if present; empty dict otherwise.

    Holds video_type, additional_instructions, sample_script — written by the
    API before the subprocess starts. Same pattern as pre_research.txt."""
    path = f"{project_dir}/script_config.json"
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)


def run_script_only(topic: str, target_minutes: int = 10, project_name: str | None = None):
    if project_name is None:
        project_name = slugify(topic)
    project_dir = f"../projects/{project_name}"
    research_path = f"{project_dir}/research.json"
    pre_research_path = f"{project_dir}/pre_research.txt"
    config = _load_script_config(project_dir)
    channel = config.get("channel")
    video_type = config.get("video_type")
    hook_archetype = config.get("hook_archetype")
    additional_instructions = config.get("additional_instructions")
    sample_script = config.get("sample_script")
    item_count = config.get("item_count")
    if channel:
        print(f"      channel: {channel}", flush=True)
    if video_type:
        print(f"      video_type: {video_type}", flush=True)
    if hook_archetype:
        print(f"      hook_archetype: {hook_archetype}", flush=True)

    if os.path.exists(research_path):
        print(f"\n[1/3] Research already exists — skipping generation.")
    else:
        pre_research = None
        if os.path.exists(pre_research_path):
            with open(pre_research_path) as f:
                pre_research = f.read()
            print(
                f"\n[1/3] Research...  (topic: {topic!r}, {target_minutes}-min target, "
                f"with {len(pre_research.split())} pre-research words)"
            )
        else:
            print(f"\n[1/3] Research...  (topic: {topic!r}, {target_minutes}-min target)")

        research = generate_research(topic, pre_research=pre_research, channel=channel)
        save_research(project_name, {"topic": topic, "research": research})
        print("      research saved")

    print("\n[2/3] Outline...")
    outline = generate_outline(
        project_name,
        topic,
        target_minutes,
        channel=channel,
        video_type=video_type,
        additional_instructions=additional_instructions,
        item_count=item_count,
    )
    save_outline(project_name, outline)
    print(f"      outline saved  ({len(outline.get('sections', []))} sections)")

    print("\n[3/3] Script draft...")
    script_draft = generate_script_draft(
        project_name,
        topic,
        target_minutes,
        channel=channel,
        video_type=video_type,
        hook_archetype=hook_archetype,
        additional_instructions=additional_instructions,
        sample_script=sample_script,
    )
    save_script_draft(project_name, script_draft)
    print("      script_draft saved")

    _print_script_summary(script_draft, target_minutes)
    print(f"\nProject: ../projects/{project_name}/")
    print("Next: review and edit the script. TTS prep happens in the voiceover stage.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    topic = sys.argv[1]
    target_minutes = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    project_name = sys.argv[3] if len(sys.argv) > 3 else None
    run_script_only(topic, target_minutes, project_name=project_name)
