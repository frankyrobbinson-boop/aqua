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
from services.script_edit_service import (
    generate_script_edit,
    save_script_edit
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

from services.visual_service import generate_all_placeholders

from services.assembly_service import assemble


def run_pipeline(topic: str):

    # 1. Create project name
    project_name = slugify(topic)

    print("\n[1/10] Generating research...")

    # 2. Generate research
    research = generate_research(topic)

    # 3. Save research
    save_research(project_name, {
        "topic": topic,
        "research": research
    })

    print("[2/10] Research saved")

    print("\n[3/10] Generating outline...")

    # 4. Generate outline
    outline = generate_outline(project_name)

    # 5. Save outline
    save_outline(project_name, outline)

    print("[4/10] Outline saved")


    print("\n[5/10] Generating script draft...")

    script_draft = generate_script_draft(project_name)

    save_script_draft(project_name, script_draft)

    print("[6/10] Script saved")

    print("\n[7/10] Generating script edit...")

    script_edit = generate_script_edit(project_name)

    save_script_edit(project_name, script_edit)

    print("[8/12] Script Edit saved")

    print("\n[9/12] Preparing script for TTS...")

    tts_script = generate_tts_prep(project_name)

    save_tts_prep(project_name, tts_script)

    print("[10/12] TTS script saved")

    print("\n[11/12] Generating scenes...")

    scene_plan = generate_scene_plan(project_name)

    save_scene_plan(project_name, scene_plan)

    print("[12/12] Scenes saved")

    print("\n[13/18] Preparing voice units...")

    voice_units = build_voice_units(project_name)

    save_voice_units(project_name, voice_units)

    print("[14/18] Voice units saved")

    print("\n[15/18] Building delivery plan...")

    annotated_units = build_delivery_plan(project_name)

    save_voice_units(project_name, annotated_units)

    print("[16/18] Delivery plan saved")

    print("\n[17/18] Generating audio...")

    timeline = generate_audio(project_name)

    save_audio_timeline(project_name, timeline)

    print("[18/22] Audio saved")

    print("\n[19/22] Computing scene windows...")

    scene_windows = compute_scene_windows(project_name)

    save_scene_windows(project_name, scene_windows)

    print(f"[20/22] Scene windows saved  ({len(scene_windows)} scenes)")

    print("\n[21/22] Generating placeholder images + assembling video...")

    image_paths = generate_all_placeholders(project_name, scene_windows)

    final_video = assemble(project_name, image_paths)

    print(f"[22/22] Video saved → {final_video}")

    print("\nDONE:", project_name)
    


if __name__ == "__main__":
    topic = "Why the 2026 World Cup is a Total Mess"
    run_pipeline(topic)