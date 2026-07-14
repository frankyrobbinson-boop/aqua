"""Assemble the final video from existing footage + audio. Assumes
run_visuals.py (or run_video_only.py) has already populated the footage/ folder.

    python run_render.py <project_name>
"""

import os
import sys

from services.assembly_service import assemble
from services.edl_service import (
    generate_default_edl,
    is_current_version,
    load_edl,
    save_edl,
)
from services.paths import PROJECTS_ROOT
from services.stage_graph import missing_inputs


def _check_inputs(project_name: str):
    folder = PROJECTS_ROOT / project_name
    if not folder.is_dir():
        raise FileNotFoundError(f"Project folder not found: {folder}")
    # edl.json is a declared render input but we auto-generate it below if
    # missing — filter it out so a fresh project that's never run the edit
    # stage doesn't false-positive here.
    missing = [m for m in missing_inputs(str(folder), "render") if m != "edl.json"]
    if missing:
        raise FileNotFoundError(
            f"Project '{project_name}' missing required artifacts: {missing}. "
            "Run run_visuals.py first."
        )
    footage_dir = folder / "footage"
    # footage is a declared input but missing_inputs only checks existence;
    # an empty footage dir means visuals didn't actually fetch anything.
    if not os.listdir(footage_dir):
        raise FileNotFoundError(
            f"No footage in {footage_dir}. Run run_visuals.py first."
        )


def run_render(project_name: str) -> str:
    _check_inputs(project_name)

    # Build the {scene_id: footage_path} dict from disk.
    import json
    with (PROJECTS_ROOT / project_name / "scene_windows.json").open() as f:
        scene_windows = json.load(f)

    footage_dir = str(PROJECTS_ROOT / project_name / "footage")
    # Either .mp4 (stock / AI video) or .png (AI image) — visual providers may
    # produce either, and assembly_service.render_scene_clip accepts both
    # transparently via ffmpeg -stream_loop on stills.
    footage_paths = {}
    for scene in scene_windows:
        sid = scene["id"]
        path = None
        for ext in ("mp4", "png"):
            candidate = os.path.join(footage_dir, f"scene_{sid:03d}.{ext}")
            if os.path.exists(candidate):
                path = candidate
                break
        if path is None:
            raise FileNotFoundError(
                f"Missing footage for scene {sid} in {footage_dir} "
                f"(looked for scene_{sid:03d}.mp4 and .png). Run run_visuals.py."
            )
        footage_paths[sid] = path

    # Per-render options injected by the API via env vars (defaults preserve
    # the original behavior when invoked from the CLI with no env set).
    transition = os.environ.get("RENDER_TRANSITION", "cut")
    if transition not in ("cut", "fade"):
        print(f"  WARN: RENDER_TRANSITION={transition!r} invalid, falling back to 'cut'")
        transition = "cut"
    ken_burns = os.environ.get("RENDER_KEN_BURNS", "0") == "1"
    # Section cards are EDL-driven now: a card is placed wherever the EDL marks a
    # scene with one, which happens only for channels that have a section-header
    # DEFAULT design (opt-in per channel). RENDER_SECTION_CARDS is a kill-switch:
    # unset → EDL-driven; "=0" forces cards off. RENDER_OUTPUT_NAME lets a card
    # render land beside an untouched final.mp4.
    section_cards = os.environ.get("RENDER_SECTION_CARDS") != "0"
    # Section transitions crossfade INTO each scene the EDL marks with a crossfade
    # lead_in (the section starts + the conclusion) instead of hard-cutting.
    # Duration-neutral. Distinct from RENDER_TRANSITION (per-clip fade).
    # RENDER_SECTION_TRANSITIONS is a kill-switch: unset → EDL-driven; "=0" forces
    # crossfades off. Cards and crossfades coexist (a section start gets BOTH a
    # card AND a dissolve into it).
    section_transitions = os.environ.get("RENDER_SECTION_TRANSITIONS") != "0"
    output_name = os.environ.get("RENDER_OUTPUT_NAME", "final.mp4")

    # Background-music bed (MVP): RENDER_MUSIC=="1" mixes the songs dropped in
    # backend/music/ low under the narration (filename order, looped to fill the
    # video); default off. RENDER_MUSIC_VOLUME is the bed's linear gain under the
    # voice (default 0.05 — a flat low bed). An empty/missing music folder degrades
    # to no music.
    music = os.environ.get("RENDER_MUSIC", "0") == "1"
    try:
        music_volume = float(os.environ.get("RENDER_MUSIC_VOLUME", "0.05"))
    except ValueError:
        print("  WARN: RENDER_MUSIC_VOLUME invalid, falling back to 0.05")
        music_volume = 0.05

    # Three more render knobs are read directly by services/assembly_service
    # (module level), so they need no plumbing here — documented for discoverability:
    #   RENDER_KB_CAMERA  — default ON. One continuous Ken Burns ping-pong zoom
    #     SHARED across each run of consecutive stills (motion flows through the
    #     cuts) + an auto-target aiming the zoom at each still's subject (aim mode
    #     set by RENDER_KB_DRIFT). "=0" restores the legacy per-scene center zoom.
    #   RENDER_KB_DRIFT — default OFF. Crop-centre aim for the KB camera: OFF pivots
    #     on a FIXED anchor (targeted zoom — the subject stays put and the zoom
    #     tightens on it, no lateral slide); "=1" DRIFTS the crop from the frame
    #     centre toward the subject as the zoom rises (drift-to-center). Center-
    #     gated stills zoom on (0.5,0.5) either way.
    #   RENDER_OST_DRAWTEXT — default OFF. No burned-in drawtext OST (header /
    #     callout / counter overlays) ships; "=1" re-enables it for debugging.
    #     Remotion section/title cards and the karaoke subtitles are unaffected.

    # Ensure a current-version EDL exists before assembly. The EDL is the
    # per-scene render decision list (transition, ken_burns, overlays); when
    # absent OR at a stale schema version we (re)generate one using the
    # Render-tab options so the behavior matches pre-EDL rendering for users who
    # skip the dedicated edit stage. An on-disk EDL already at the current
    # version is otherwise authoritative and left untouched; regeneration is
    # deterministic, so a stale-version upgrade reproduces all prior data plus the
    # current overlays shape.
    edl = load_edl(project_name)
    if edl is None or not is_current_version(edl):
        print("[1/2] Generating EDL...")
        print("[[STAGE:edl:started]]", flush=True)
        edl = generate_default_edl(
            project_name, transition=transition, ken_burns=ken_burns,
        )
        print(f"  edl.json generated ({len(edl['scenes'])} scenes)")
        print("[[STAGE:edl:completed]]", flush=True)

    # The Render-tab Ken Burns toggle is AUTHORITATIVE on every render: stamp its
    # value onto every scene's per-scene ken_burns and re-save, so a re-render
    # against an existing edl.json honors the toggle too (generate_default_edl only
    # sets ken_burns on a FRESH EDL — without this an existing EDL would keep its
    # old value and silently ignore the toggle). Camera vs static-still is then
    # driven by RENDER_KB_CAMERA / RENDER_KB_DRIFT (set by the API from the same
    # toggle).
    for scene in edl.get("scenes", []):
        scene["ken_burns"] = ken_burns
    save_edl(project_name, edl)

    print(
        f"\nAssembling video for '{project_name}' ({len(footage_paths)} scenes; "
        f"transition={transition}, ken_burns={ken_burns}, "
        f"section_cards={section_cards}, section_transitions={section_transitions}, "
        f"music={music}, output={output_name})..."
    )
    print("[[STAGE:render:started]]", flush=True)
    final_video = assemble(
        project_name, footage_paths, transition=transition, ken_burns=ken_burns,
        section_cards=section_cards, section_transitions=section_transitions,
        output_name=output_name, music=music, music_volume=music_volume,
    )
    print("[[STAGE:render:completed]]", flush=True)

    print(f"\nDONE: {final_video}")
    return final_video


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    run_render(sys.argv[1])
