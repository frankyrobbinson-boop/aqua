"""Run only the video-assembly portion of the pipeline against a project that
already has scene_plan.json + audio_timeline.json + audio chunks on disk.

Use this to iterate on visuals/assembly without re-paying for research, script,
or voice generation. Recomputes scene_windows from saved artifacts (no API
calls), fetches/generates visuals, and assembles the final video.

    python run_video_only.py <project_name>
"""

import os
import sys

from services.scene_timing_service import compute_scene_windows, save_scene_windows
from services.visual_service import fetch_scene_footage
from services.visual_pexels import PexelsProvider
from services.assembly_service import assemble


REQUIRED_FILES = ["scene_plan.json", "audio_timeline.json"]


def _check_inputs(project_name: str):
    folder = f"../projects/{project_name}"
    if not os.path.isdir(folder):
        raise FileNotFoundError(f"Project folder not found: {folder}")

    missing = [f for f in REQUIRED_FILES if not os.path.exists(f"{folder}/{f}")]
    if missing:
        raise FileNotFoundError(
            f"Project '{project_name}' missing required artifacts: {missing}. "
            "Run the full pipeline at least once to produce them."
        )

    audio_dir = f"{folder}/audio"
    if not os.path.isdir(audio_dir) or not os.listdir(audio_dir):
        raise FileNotFoundError(
            f"No audio chunks in {audio_dir}. "
            "Run the full pipeline at least once to produce them."
        )


def run_video_only(project_name: str) -> str:
    _check_inputs(project_name)

    print(f"\n[1/3] Recomputing scene windows for '{project_name}'...")
    scene_windows = compute_scene_windows(project_name)
    save_scene_windows(project_name, scene_windows)
    print(f"      {len(scene_windows)} scenes")

    print("\n[2/3] Fetching stock footage...")
    provider = PexelsProvider()
    footage_paths = fetch_scene_footage(project_name, scene_windows, provider)

    print("\n[3/3] Assembling video...")
    final_video = assemble(project_name, footage_paths)

    print(f"\nDONE: {final_video}")
    return final_video


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    run_video_only(sys.argv[1])
