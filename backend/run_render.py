"""Assemble the final video from existing footage + audio. Assumes
run_visuals.py (or run_video_only.py) has already populated the footage/ folder.

    python run_render.py <project_name>
"""

import os
import sys

from services.assembly_service import assemble
from services.stage_graph import missing_inputs


def _check_inputs(project_name: str):
    folder = f"../projects/{project_name}"
    if not os.path.isdir(folder):
        raise FileNotFoundError(f"Project folder not found: {folder}")
    missing = missing_inputs(folder, "render")
    if missing:
        raise FileNotFoundError(
            f"Project '{project_name}' missing required artifacts: {missing}. "
            "Run run_visuals.py first."
        )
    footage_dir = f"{folder}/footage"
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
    with open(f"../projects/{project_name}/scene_windows.json") as f:
        scene_windows = json.load(f)

    footage_dir = f"../projects/{project_name}/footage"
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

    print(
        f"\nAssembling video for '{project_name}' ({len(footage_paths)} scenes; "
        f"transition={transition}, ken_burns={ken_burns})..."
    )
    final_video = assemble(
        project_name, footage_paths, transition=transition, ken_burns=ken_burns,
    )

    print(f"\nDONE: {final_video}")
    return final_video


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    run_render(sys.argv[1])
