"""End-to-end pipeline: script → voiceover → visuals → render. Chains the
individual stage scripts in process so all output streams as one log.

Stages already completed for the project are skipped — so the same entrypoint
serves both a fresh "run everything" and a "finish what was started" flow.

    python run_full_pipeline.py "Your topic here" [target_minutes]
"""

import sys

from services.research_service import slugify
from services.stage_graph import is_stage_fresh

from run_script_only import run_script_only
from run_audio import run_audio
from run_visuals import run_visuals
from run_edit import run_edit
from run_render import run_render


def _stage_banner(n: int, total: int, label: str) -> None:
    bar = "=" * 60
    print(f"\n{bar}\nSTAGE {n}/{total}: {label}\n{bar}", flush=True)


def run_full_pipeline(
    topic: str,
    target_minutes: int = 10,
    project_name: str | None = None,
) -> str:
    if project_name is None:
        project_name = slugify(topic)
    project_dir = f"../projects/{project_name}"

    # Each stage's "skip if done" is the same predicate: declared outputs exist
    # AND aren't older than any declared input. See services/stage_graph.py for
    # the actual edges. A direct disk edit of script_draft.json after the last
    # voiceover run, for example, lands here as is_stage_fresh("voiceover")=False
    # — without anyone having to remember to add an mtime check.
    _stage_banner(1, 5, "Script")
    if is_stage_fresh(project_dir, "script"):
        print("Script artifacts already present and current — skipping.", flush=True)
    else:
        run_script_only(topic, target_minutes, project_name=project_name)

    _stage_banner(2, 5, "Voiceover (ElevenLabs)")
    if is_stage_fresh(project_dir, "voiceover"):
        print("Voiceover already present and current — skipping.", flush=True)
    else:
        run_audio(project_name)

    _stage_banner(3, 5, "Visuals (scene plan + Pexels fetch + LLM rerank)")
    if is_stage_fresh(project_dir, "visuals"):
        print("Visuals already present and current — skipping.", flush=True)
    else:
        run_visuals(project_name)

    _stage_banner(4, 5, "Edit (per-scene EDL + text overlays)")
    if is_stage_fresh(project_dir, "edit"):
        print("EDL already present and current — skipping.", flush=True)
    else:
        run_edit(project_name)

    _stage_banner(5, 5, "Render (assemble + subtitles + mux)")
    if is_stage_fresh(project_dir, "render"):
        print("Render already present and current — skipping.", flush=True)
        final_video = f"{project_dir}/video/final.mp4"
    else:
        final_video = run_render(project_name)

    print(f"\nDONE. Final video: {final_video}")
    return final_video


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    topic = sys.argv[1]
    target_minutes = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    project_name = sys.argv[3] if len(sys.argv) > 3 else None
    run_full_pipeline(topic, target_minutes, project_name=project_name)
