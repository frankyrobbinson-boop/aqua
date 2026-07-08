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
    # Section cards front each section-intro scene with a title card that eats
    # into that scene's own frames (zero added time). Off by default so the CLI
    # and existing callers are unchanged. RENDER_OUTPUT_NAME lets a card render
    # land beside an untouched final.mp4.
    section_cards = os.environ.get("RENDER_SECTION_CARDS", "0") == "1"
    # Section transitions crossfade each section boundary (segment_id change)
    # instead of hard-cutting. Duration-neutral, off by default. Distinct from
    # RENDER_TRANSITION (per-clip fade). If section cards are also on, cards win.
    section_transitions = os.environ.get("RENDER_SECTION_TRANSITIONS", "0") == "1"
    output_name = os.environ.get("RENDER_OUTPUT_NAME", "final.mp4")

    # Ensure a current-version EDL exists before assembly. The EDL is the
    # per-scene render decision list (transition, ken_burns, overlays); when
    # absent OR at a stale schema version we (re)generate one using the
    # Render-tab options so the behavior matches pre-EDL rendering for users who
    # skip the dedicated edit stage. An on-disk EDL already at the current
    # version (e.g. from a prior run_edit.py) is authoritative and left
    # untouched; regeneration is deterministic, so a stale-version upgrade
    # reproduces all prior data plus the current overlays shape.
    existing_edl = load_edl(project_name)
    if existing_edl is None or not is_current_version(existing_edl):
        print("[1/2] Generating EDL...")
        print("[[STAGE:edl:started]]", flush=True)
        edl = generate_default_edl(
            project_name, transition=transition, ken_burns=ken_burns,
        )
        save_edl(project_name, edl)
        print(f"  edl.json saved ({len(edl['scenes'])} scenes)")
        print("[[STAGE:edl:completed]]", flush=True)

    print(
        f"\nAssembling video for '{project_name}' ({len(footage_paths)} scenes; "
        f"transition={transition}, ken_burns={ken_burns}, "
        f"section_cards={section_cards}, section_transitions={section_transitions}, "
        f"output={output_name})..."
    )
    print("[[STAGE:render:started]]", flush=True)
    final_video = assemble(
        project_name, footage_paths, transition=transition, ken_burns=ken_burns,
        section_cards=section_cards, section_transitions=section_transitions,
        output_name=output_name,
    )
    print("[[STAGE:render:completed]]", flush=True)

    print(f"\nDONE: {final_video}")
    return final_video


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    run_render(sys.argv[1])
