"""Visuals stage: scene_plan -> scene_windows -> visual_prompts -> footage.

scene_plan reads script_draft.json; scene_windows reads scene_plan.json +
audio_timeline.json; visual_prompts reads scene_plan.json + the channel's
visuals config and emits per-scene AI-image prompts (passthrough when the
channel has no style configured). Footage fetch is dispatched per-segment via
visual_service.fetch_all_scene_footage, which reads visual_config.json (or
falls back to the all-Pexels default).

    python run_visuals.py <project_name>
"""

import os
import sys
import traceback

from services.channel_registry import resolve_channel_visuals
from services.paths import PROJECTS_ROOT
from services.scene_plan_service import generate_scene_plan, save_scene_plan
from services.scene_timing_service import compute_scene_windows, save_scene_windows
from services.stage_graph import missing_inputs
from services.visual_prompt_service import (
    _build_passthrough_payload,
    _load_channel_id,
    compute_cache_key,
    generate_visual_prompts,
    save_visual_prompts,
)
from services.visual_service import fetch_all_scene_footage


def _check_inputs(project_name: str):
    folder = PROJECTS_ROOT / project_name
    if not folder.is_dir():
        raise FileNotFoundError(f"Project folder not found: {folder}")
    missing = missing_inputs(str(folder), "visuals")
    if missing:
        raise FileNotFoundError(
            f"Project '{project_name}' missing required artifacts: {missing}. "
            "Run run_audio.py first."
        )


def _safe_visual_prompts(project_name: str) -> dict:
    """Run the enhancer; on any failure, fall back to a passthrough payload so
    footage gen still proceeds. The expensive step is image generation —
    mediocre prompts beat no prompts at all."""
    try:
        return generate_visual_prompts(project_name)
    except Exception as exc:
        print(
            f"      ERROR: visual-prompt enhancement failed: {exc!r}",
            flush=True,
        )
        traceback.print_exc()
        # Build a minimal passthrough payload directly from scene_plan so the
        # provider lookup still finds entries. Re-uses service internals so
        # the payload shape stays in lockstep.
        import json
        with (PROJECTS_ROOT / project_name / "scene_plan.json").open() as f:
            scene_plan = json.load(f)
        scenes = scene_plan.get("scene_intent", []) or []
        channel_id = _load_channel_id(project_name)
        channel_visuals = resolve_channel_visuals(channel_id)
        model = channel_visuals.get("prompt_enhancement_model") or "claude-haiku-4-5-20251001"
        cache_key = compute_cache_key(channel_visuals, scenes)
        print("      Falling back to passthrough payload.", flush=True)
        return _build_passthrough_payload(channel_id, model, cache_key, scenes)


def run_visuals(project_name: str) -> dict:
    _check_inputs(project_name)

    print(f"\n[1/4] Scene plan for '{project_name}'...")
    print("[[STAGE:scene_plan:started]]", flush=True)
    scene_plan = generate_scene_plan(project_name)
    save_scene_plan(project_name, scene_plan)
    print(f"      {len(scene_plan.get('scene_intent', []))} scenes planned")
    print("[[STAGE:scene_plan:completed]]", flush=True)

    print("\n[2/4] Computing scene windows...")
    print("[[STAGE:scene_windows:started]]", flush=True)
    scene_windows = compute_scene_windows(project_name)
    save_scene_windows(project_name, scene_windows)
    print(f"      {len(scene_windows)} scene windows")
    print("[[STAGE:scene_windows:completed]]", flush=True)

    print("\n[3/4] Enhancing visual prompts...")
    print("[[STAGE:visual_prompts:started]]", flush=True)
    prompt_payload = _safe_visual_prompts(project_name)
    save_visual_prompts(project_name, prompt_payload)
    print(
        f"      {len(prompt_payload.get('scenes', []))} prompts "
        f"({prompt_payload.get('source', '?')}, model={prompt_payload.get('model', '?')})"
    )
    print("[[STAGE:visual_prompts:completed]]", flush=True)

    print("\n[4/4] Fetching footage (per-segment providers)...")
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
    run_visuals(sys.argv[1])
