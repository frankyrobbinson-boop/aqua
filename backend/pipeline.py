from services.research_service import (
    generate_research,
    save_research,
    slugify
)

from services.outline_service import (
    generate_outline,
    save_outline
)

from services.script_draft_service import (
    generate_script_draft,
    save_script_draft
)

from services.tts_prep_service import (
    generate_tts_prep,
    save_tts_prep
)

from services.scene_plan_service import (
    generate_scene_plan,
    save_scene_plan
)

from services.voice_prep_service import (
    build_voice_units,
    save_voice_units
)

from services.delivery_plan_service import (
    build_delivery_plan
)

from services.voice_service import (
    generate_audio,
    save_audio_timeline
)

from services.scene_timing_service import (
    compute_scene_windows,
    save_scene_windows
)

from services.visual_service import fetch_scene_footage
from services.visual_pexels import PexelsProvider

from services.assembly_service import assemble


def run_pipeline(topic: str, target_minutes: int = 10):

    project_name = slugify(topic)

    print(f"\n[1/10] Generating research ({target_minutes}-min target)...")
    research = generate_research(topic)
    save_research(project_name, {
        "topic": topic,
        "research": research
    })
    print("[2/10] Research saved")

    print("\n[3/10] Generating outline...")
    outline = generate_outline(project_name, topic, target_minutes)
    save_outline(project_name, outline)
    print("[4/10] Outline saved")

    print("\n[5/10] Generating script draft...")
    script_draft = generate_script_draft(project_name, topic, target_minutes)
    save_script_draft(project_name, script_draft)
    print("[6/10] Script saved")

    print("\n[7/10] Preparing script for TTS...")
    tts_script = generate_tts_prep(project_name)
    save_tts_prep(project_name, tts_script)
    print("[8/10] TTS script saved")

    print("\n[9/10] Generating scene plan...")
    scene_plan = generate_scene_plan(project_name)
    save_scene_plan(project_name, scene_plan)
    print("[10/10] Scene plan saved")

    print("\n[11/16] Preparing voice units...")
    voice_units = build_voice_units(project_name)
    save_voice_units(project_name, voice_units)
    print("[12/16] Voice units saved")

    print("\n[13/16] Building delivery plan...")
    annotated_units = build_delivery_plan(project_name)
    save_voice_units(project_name, annotated_units)
    print("[14/16] Delivery plan saved")

    print("\n[15/16] Generating audio...")
    timeline = generate_audio(project_name)
    save_audio_timeline(project_name, timeline)
    print("[16/16] Audio saved")

    print("\n[17/20] Computing scene windows...")
    scene_windows = compute_scene_windows(project_name)
    save_scene_windows(project_name, scene_windows)
    print(f"[18/20] Scene windows saved  ({len(scene_windows)} scenes)")

    print("\n[19/20] Fetching stock footage + assembling video...")
    provider = PexelsProvider()
    footage_paths = fetch_scene_footage(project_name, scene_windows, provider)
    final_video = assemble(project_name, footage_paths)
    print(f"[20/20] Video saved → {final_video}")

    print("\nDONE:", project_name)



if __name__ == "__main__":
    topic = "10 vegetables to grow in June (before it's too late)"
    run_pipeline(topic, target_minutes=10)
