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
    footage_paths = {}
    for scene in scene_windows:
        sid = scene["id"]
        path = os.path.join(footage_dir, f"scene_{sid:03d}.mp4")
        if not os.path.exists(path):
            raise FileNotFoundError(
                f"Missing footage for scene {sid}: {path}. Run run_visuals.py."
            )
        footage_paths[sid] = path

    print(f"\nAssembling video for '{project_name}' ({len(footage_paths)} scenes)...")
    final_video = assemble(project_name, footage_paths)

    print(f"\nDONE: {final_video}")
    return final_video


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    run_render(sys.argv[1])
