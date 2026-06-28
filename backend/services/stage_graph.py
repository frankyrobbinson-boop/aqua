"""Pipeline stage graph: declares input/output/cache relationships between
stages so freshness checks and cascade-invalidation aren't hand-maintained in
three different places (run_full_pipeline.py, run_*.py REQUIRED_FILES,
api/routes/projects.py).

A stage is "fresh" iff all of its outputs exist AND every output mtime is at
least as new as every input mtime. A stage is "complete enough to feed the
next stage" iff its outputs exist (no mtime constraint).

Caches are content-keyed artifacts (ElevenLabs MP3s, Pexels clips, ffmpeg
scene clips) that survive cascade-invalidation because their own sidecar logic
detects staleness per item. Deleting them on every script edit would force a
full re-bill on ElevenLabs and a full re-download from Pexels.
"""

import os
import shutil
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class Stage:
    name: str
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    # Content-keyed cache artifacts owned by this stage. Preserved on cascade
    # invalidate; per-item validity is enforced by the cache's own sidecar.
    caches: tuple[str, ...] = ()


# Order is informational only — actual dependency order is derived from
# input/output edges. Paths are relative to a project directory.
STAGES: tuple[Stage, ...] = (
    # script_config.json is API-managed config, not a pipeline artifact, so it's
    # not modeled here — the /scripts and /voiceover routes handle config-driven
    # regeneration explicitly. Modeling it as an input would cause /pipeline to
    # always re-run the script stage because the route freshly writes the file.
    Stage(
        name="script",
        inputs=(),
        outputs=("research.json", "outline.json", "script_draft.json"),
    ),
    Stage(
        name="voiceover",
        inputs=("script_draft.json",),
        outputs=("tts_script.json", "voice_units.json", "audio_timeline.json"),
        # ElevenLabs MP3s + .json metadata, content-keyed by tts_source/seed/voice_speed
        caches=("audio",),
    ),
    Stage(
        name="visuals",
        inputs=("script_draft.json", "audio_timeline.json"),
        outputs=("scene_plan.json", "scene_windows.json"),
        # Pexels clips, content-keyed by visual_description sidecar (.cache.json)
        caches=("footage",),
    ),
    Stage(
        # Per-scene render decisions (transition, ken_burns, text overlays).
        # Sits between visuals and render so the cascade properly invalidates
        # edl.json when scene_plan or script_draft changes — deleting
        # scene_plan invalidates edl which then invalidates final.mp4.
        # Overlay text now keys off script_draft.segments[i].title (not the
        # outline) so outline-only edits no longer needlessly invalidate the EDL.
        name="edit",
        inputs=("scene_windows.json", "scene_plan.json", "script_draft.json"),
        outputs=("edl.json",),
    ),
    Stage(
        name="render",
        inputs=("audio_timeline.json", "scene_windows.json", "footage", "edl.json"),
        outputs=("video/final.mp4",),
        # Per-scene rendered clips, content-keyed by footage_mtime+duration sidecar
        caches=("clips",),
    ),
)

_STAGES_BY_NAME: dict[str, Stage] = {s.name: s for s in STAGES}


def get_stage(name: str) -> Stage:
    try:
        return _STAGES_BY_NAME[name]
    except KeyError as exc:
        raise KeyError(f"Unknown stage: {name!r}") from exc


# ---------------------------------------------------------------------------
# Freshness
# ---------------------------------------------------------------------------

def _present(path: str) -> bool:
    """A file is present if size > 0; a directory is present if non-empty.
    Empty leftovers from a failed run shouldn't count as 'output exists'."""
    if not os.path.exists(path):
        return False
    if os.path.isdir(path):
        try:
            return any(os.scandir(path))
        except OSError:
            return False
    try:
        return os.path.getsize(path) > 0
    except OSError:
        return False


def _mtime(path: str) -> float:
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def is_stage_fresh(project_dir: str, stage_name: str) -> bool:
    """True iff all outputs exist AND every output mtime ≥ every input mtime.

    A False result means either (a) the stage hasn't run, or (b) an input was
    edited after the last run (e.g. a direct disk edit that bypassed the API
    cascade) and the outputs are stale.
    """
    stage = get_stage(stage_name)
    outs = [os.path.join(project_dir, p) for p in stage.outputs]
    if not all(_present(p) for p in outs):
        return False
    ins = [os.path.join(project_dir, p) for p in stage.inputs]
    max_in = max((_mtime(p) for p in ins), default=0.0)
    min_out = min(_mtime(p) for p in outs)
    return min_out >= max_in


def missing_inputs(project_dir: str, stage_name: str) -> list[str]:
    """Inputs that don't exist on disk. For pre-flight checks in run_*.py."""
    stage = get_stage(stage_name)
    return [
        rel for rel in stage.inputs
        if not os.path.exists(os.path.join(project_dir, rel))
    ]


# ---------------------------------------------------------------------------
# Cascade invalidate
# ---------------------------------------------------------------------------

def _consumer_map() -> dict[str, list[Stage]]:
    """{artifact_path: [stages_whose_inputs_include_it]}"""
    out: dict[str, list[Stage]] = {}
    for stage in STAGES:
        for rel in stage.inputs:
            out.setdefault(rel, []).append(stage)
    return out


def transitive_dependent_outputs(changed_artifact: str) -> list[str]:
    """Walk the DAG from `changed_artifact` and return every output of every
    transitively dependent stage. Caches are not included — they survive
    invalidation."""
    consumers = _consumer_map()
    seen_stages: set[str] = set()
    files: list[str] = []
    frontier: list[str] = [changed_artifact]
    while frontier:
        artifact = frontier.pop()
        for stage in consumers.get(artifact, []):
            if stage.name in seen_stages:
                continue
            seen_stages.add(stage.name)
            files.extend(stage.outputs)
            # An output of this stage is an input to further stages.
            frontier.extend(stage.outputs)
    return files


def invalidate_dependents(project_dir: str, changed_artifact: str) -> list[str]:
    """Delete every output of every transitively dependent stage. Caches owned
    by those stages are preserved (per-item staleness is enforced by sidecars).

    Returns the list of relative paths actually removed.
    """
    targets = transitive_dependent_outputs(changed_artifact)
    removed: list[str] = []
    for rel in targets:
        full = os.path.join(project_dir, rel)
        try:
            if os.path.isdir(full):
                shutil.rmtree(full)
                removed.append(rel)
            elif os.path.exists(full):
                os.remove(full)
                removed.append(rel)
        except OSError:
            pass
    return removed


def all_stage_names() -> Iterable[str]:
    return (s.name for s in STAGES)
