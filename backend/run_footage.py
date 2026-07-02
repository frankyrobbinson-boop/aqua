"""Footage-only runner: re-fetch footage on the existing scene plan.

Reuses the project's scene_windows.json, visual_prompts.json, and
visual_config.json as-is and runs ONLY visual_service.fetch_all_scene_footage.
Cached scenes skip; missing/failed scenes (and segments whose mode changed)
re-fetch. This does NOT re-plan scenes, recompute windows, or regenerate
prompts — use run_visuals.py for a full run (which always re-plans and busts
the footage cache).

    python run_footage.py <project_name>
"""

import sys

from services.paths import PROJECTS_ROOT
from services.visual_service import fetch_all_scene_footage


def _check_inputs(project_name: str):
    folder = PROJECTS_ROOT / project_name
    if not folder.is_dir():
        raise FileNotFoundError(f"Project folder not found: {folder}")
    if not (folder / "scene_windows.json").exists():
        raise FileNotFoundError(
            "scene_windows.json missing — run 'Generate Scenes' first."
        )


def run_footage(project_name: str) -> dict:
    _check_inputs(project_name)

    print(f"\nFetching footage for '{project_name}' (per-segment providers)...")
    print("[[STAGE:footage:started]]", flush=True)
    footage_paths, footage_errors = fetch_all_scene_footage(project_name)

    total = len(footage_paths) + len(footage_errors)
    if footage_errors:
        print(
            f"\n      WARNING: {len(footage_errors)}/{total} scene(s) failed:",
            flush=True,
        )
        for sid in sorted(footage_errors):
            print(f"        scene {sid}: {footage_errors[sid]}", flush=True)
        # Abort if more than 25% of scenes failed — past this point the output
        # video would have too many missing-footage gaps to be usable.
        if total > 0 and (len(footage_errors) / total) > 0.25:
            raise RuntimeError(
                f"Aborting: {len(footage_errors)}/{total} scene(s) failed "
                f"({len(footage_errors) / total:.0%}, threshold 25%). "
                f"Review the errors above, fix the underlying cause, and re-run."
            )

    print("[[STAGE:footage:completed]]", flush=True)
    print(
        f"\nDONE: {len(footage_paths)} clips at "
        f"{PROJECTS_ROOT / project_name / 'footage'}/"
    )
    return footage_paths


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    run_footage(sys.argv[1])
