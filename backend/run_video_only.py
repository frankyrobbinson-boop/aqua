"""Run only the video-assembly portion of the pipeline against a project that
already has scene_plan.json + audio_timeline.json + audio chunks on disk.

Use this to iterate on visuals/assembly without re-paying for research, script,
or voice generation. Recomputes scene_windows from saved artifacts (no API
calls), dispatches per-segment visual providers via fetch_all_scene_footage
(same orchestrator run_visuals uses), and assembles the final video.

    python run_video_only.py <project_name>
"""

import os
import sys

from services.assembly_service import assemble
from services.paths import PROJECTS_ROOT
from services.scene_timing_service import compute_scene_windows, save_scene_windows
from services.visual_service import fetch_all_scene_footage


REQUIRED_FILES = ["scene_plan.json", "audio_timeline.json"]


def _check_inputs(project_name: str):
    folder = PROJECTS_ROOT / project_name
    if not folder.is_dir():
        raise FileNotFoundError(f"Project folder not found: {folder}")

    missing = [f for f in REQUIRED_FILES if not (folder / f).exists()]
    if missing:
        raise FileNotFoundError(
            f"Project '{project_name}' missing required artifacts: {missing}. "
            "Run the full pipeline at least once to produce them."
        )

    audio_dir = folder / "audio"
    if not audio_dir.is_dir() or not os.listdir(audio_dir):
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

    print("\n[2/3] Fetching footage (per-segment providers)...")
    footage_paths, footage_errors = fetch_all_scene_footage(project_name)

    # Mirror run_visuals.py's tolerance handling: abort if more than 25% of
    # scenes failed; otherwise warn and proceed.
    total = len(footage_paths) + len(footage_errors)
    if footage_errors:
        print(
            f"\n      WARNING: {len(footage_errors)}/{total} scene(s) failed:",
            flush=True,
        )
        for sid in sorted(footage_errors):
            print(f"        scene {sid}: {footage_errors[sid]}", flush=True)
        if total > 0 and (len(footage_errors) / total) > 0.25:
            raise RuntimeError(
                f"Aborting: {len(footage_errors)}/{total} scene(s) failed "
                f"({len(footage_errors) / total:.0%}, threshold 25%). "
                f"Review the errors above, fix the underlying cause, and re-run."
            )

    print("\n[3/3] Assembling video...")
    final_video = assemble(project_name, footage_paths)

    print(f"\nDONE: {final_video}")
    return final_video


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    run_video_only(sys.argv[1])
