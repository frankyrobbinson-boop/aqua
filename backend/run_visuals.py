"""Visuals stage: scene_plan -> scene_windows -> fetch per-segment footage.

scene_plan reads script_draft.json; scene_windows reads scene_plan.json +
audio_timeline.json. Footage fetch is dispatched per-segment via
visual_service.fetch_all_scene_footage, which reads visual_config.json (or
falls back to the all-Pexels default).

    python run_visuals.py <project_name>
"""

import os
import sys

from services.scene_plan_service import generate_scene_plan, save_scene_plan
from services.scene_timing_service import compute_scene_windows, save_scene_windows
from services.stage_graph import missing_inputs
from services.visual_service import fetch_all_scene_footage


def _check_inputs(project_name: str):
    folder = f"../projects/{project_name}"
    if not os.path.isdir(folder):
        raise FileNotFoundError(f"Project folder not found: {folder}")
    missing = missing_inputs(folder, "visuals")
    if missing:
        raise FileNotFoundError(
            f"Project '{project_name}' missing required artifacts: {missing}. "
            "Run run_audio.py first."
        )


def run_visuals(project_name: str) -> dict:
    _check_inputs(project_name)

    print(f"\n[1/3] Scene plan for '{project_name}'...")
    scene_plan = generate_scene_plan(project_name)
    save_scene_plan(project_name, scene_plan)
    print(f"      {len(scene_plan.get('scene_intent', []))} scenes planned")

    print("\n[2/3] Computing scene windows...")
    scene_windows = compute_scene_windows(project_name)
    save_scene_windows(project_name, scene_windows)
    print(f"      {len(scene_windows)} scene windows")

    print("\n[3/3] Fetching footage (per-segment providers)...")
    footage_paths = fetch_all_scene_footage(project_name)

    print(f"\nDONE: {len(footage_paths)} clips at ../projects/{project_name}/footage/")
    return footage_paths


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    run_visuals(sys.argv[1])
