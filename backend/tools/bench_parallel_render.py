#!/usr/bin/env python3
"""Benchmark: how much wall-clock does PARALLELIZING the per-scene render phase save?

WHY
    ``render_all_scene_clips`` (services/assembly_service.py) renders every scene
    clip strictly SEQUENTIALLY. Each KB-still clip is a per-frame cv2 subpixel warp
    piped to libx264 (~5s/clip here), so a 90-scene / ~54k-frame video spends many
    minutes in this one phase. Scene clips are INDEPENDENT (each reads its own
    footage + camera track + chip and writes its own scene_NNN.mp4), so the phase is
    embarrassingly parallel. This script measures the real speedup from a process
    pool BEFORE anyone touches the pipeline — and, critically, proves the parallel
    output is PIXEL-IDENTICAL to the sequential output (and to the real pipeline's
    already-rendered clips), so parallelizing would be a pure wall-clock win with no
    render-correctness change.

HOW
    It imports the EXISTING pipeline functions from services.* (it does NOT modify or
    re-implement any of them) and reproduces ``render_all_scene_clips`` /
    ``assemble`` setup EXACTLY: it loads the scene windows + the (already current)
    EDL, resolves the channel editing style, rebuilds the section-card map + per-card
    hold seconds, resolves footage paths (mp4-then-png like run_render.py), and
    computes the ONE shared continuous Ken-Burns camera track set — all once. For the
    benchmarked subset it then:
      1. Renders each scene SEQUENTIALLY (the baseline + the pixel-identity reference)
         into /tmp/bench_seq/ via the real ``render_scene_clip``.
      2. SWEEPS a list of worker counts; for each N it renders the SAME subset with a
         ProcessPoolExecutor(max_workers=N) into a fresh /tmp/bench_par_N/, timing the
         wall clock from submit to all-done. speedup(N) = seq_total / par_total(N).
    Validation uses ffmpeg ``framemd5`` (per-frame MD5s) as the authoritative
    pixel-identity check, plus a whole-file sha256 (byte identity, which libx264 does
    not always guarantee across runs). Every parallel clip is checked frame-identical
    to its sequential twin, and each sequential clip is cross-checked frame-identical
    to the project's EXISTING clips/scene_NNN.mp4 (proving this bench reproduces the
    real pipeline, so the numbers are trustworthy).

SUBSET
    12 scenes (all PNG + Ken-Burns stills, section cards excluded), spread across the
    video so the shared camera runs and a few fact-chip scenes are represented:
        [11, 0, 3, 1, 21, 12, 33, 30, 49, 34, 45, 53]
    Scenes 34/45/53 carry a fact CHIP; their chip.mov is SEEDED from the project's
    already-rendered clips/ (copied into /tmp/bench_chips/) so ``_ensure_callout_chip``
    is a guaranteed cache HIT — no Remotion/node, no API, no project mutation.

OUTPUTS (all left on disk for inspection; paths printed at the end)
    /tmp/bench_seq/            sequential clips (the pixel-identity reference)
    /tmp/bench_par_<N>/        one dir per swept worker count
    /tmp/bench_chips/          seeded fact-chip .mov(+.json) cache
    Plus a printed report: per-scene sequential times + identity results, an
    N -> par_total -> speedup table (best N highlighted), and a full-video
    extrapolation with the explicit Amdahl caveat.

FREE / NO API / NO MUTATION
    Local ffmpeg + cv2 only. No script/scene/TTS/image generation, no paid calls. The
    EDL is already at the current schema version so ``_load_or_create_edl`` only reads
    it (no regenerate/save). Chips are cache hits. Nothing is written under the
    project; every output goes to /tmp.

RUN (from the backend/ directory, so the relative prompts/ lookups resolve):
    ./venv/bin/python tools/bench_parallel_render.py                     # full 12/sweep
    ./venv/bin/python tools/bench_parallel_render.py --scenes 3 --workers 2   # smoke
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

# The script lives in backend/tools/; put backend/ on sys.path so ``services.*``
# imports resolve regardless of how python is invoked.
BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from services.assembly_service import (  # noqa: E402
    SECTION_CARD_SECONDS,
    _card_seconds_by_scene,
    _cards_from_edl,
    _ensure_callout_chip,
    _load_or_create_edl,
    _project_channel_id,
    compute_camera_tracks,
    render_scene_clip,
)
from services.channel_registry import resolve_channel_editing  # noqa: E402
from services.paths import PROJECTS_ROOT  # noqa: E402
from services.scene_timing_service import load_scene_windows  # noqa: E402

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

# The 90-scene / 53,928-frame reference project. All subset scenes are PNG + KB
# stills with cut lead-ins (no section cards), and its clips/ are already rendered
# so we can cross-check pixel identity against the real pipeline output.
PROJECT = "6-vegetables-you-plant-once-and-harvest-for-20-years"

# 12 scenes, all PNG + Ken Burns, cards excluded. 34/45/53 carry a fact chip.
SUBSET = [11, 0, 3, 1, 21, 12, 33, 30, 49, 34, 45, 53]

DEFAULT_WORKERS = "2,4,6,8"

SEQ_DIR = Path("/tmp/bench_seq")
CHIP_DIR = Path("/tmp/bench_chips")


def _par_dir(n: int) -> Path:
    return Path(f"/tmp/bench_par_{n}")


# ---------------------------------------------------------------------------
# Hashing / identity helpers
# ---------------------------------------------------------------------------

def _byte_hash(path: str | Path) -> str:
    """sha256 of the raw file bytes (whole-container identity). Stricter than
    frame identity — libx264 does not guarantee byte-identical output across runs,
    so a NO here with a frame-match YES is expected, not a failure."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _frame_hash(path: str | Path) -> str:
    """Authoritative PIXEL-identity check: sha256 over ffmpeg's per-frame MD5s.

    ``ffmpeg -f framemd5`` emits one MD5 line per decoded video frame (plus ``#``
    comment lines we strip). Two files with the same frame-MD5 sequence are
    pixel-for-pixel identical regardless of container/encoder byte differences."""
    r = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:v:0", "-f", "framemd5", "-"],
        capture_output=True, text=True, check=True,
    )
    lines = [ln for ln in r.stdout.splitlines() if ln and not ln.startswith("#")]
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()


def _fresh_dir(d: Path) -> Path:
    """Empty (or create) a dir so a run never cache-hits a previous run's clips —
    render_scene_clip caches on the output path's sidecar, so a stale dir would make
    the render return instantly and poison the timing."""
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# Input setup — reproduces render_all_scene_clips / assemble EXACTLY
# ---------------------------------------------------------------------------

def _build_footage_paths(windows: list[dict]) -> dict[int, str]:
    """{scene_id: absolute footage path}, mp4-then-png precedence, exactly like
    run_render.py. Built for ALL scenes because compute_camera_tracks partitions
    still-runs over the whole timeline. A scene whose footage is missing is skipped
    (compute_camera_tracks treats a missing source as a non-KB scene)."""
    footage_dir = PROJECTS_ROOT / PROJECT / "footage"
    paths: dict[int, str] = {}
    for scene in windows:
        sid = scene["id"]
        for ext in ("mp4", "png"):
            cand = footage_dir / f"scene_{sid:03d}.{ext}"
            if cand.exists():
                paths[sid] = str(cand)
                break
    return paths


def _seed_chip(sid: int, callout: dict | None, scene: dict):
    """Copy the project's already-rendered chip.mov(+.json) into CHIP_DIR so
    ``_ensure_callout_chip`` is a guaranteed cache HIT (no Remotion/node, no API).

    If a callout scene's chip.mov is somehow absent we return None (render the scene
    without the chip) rather than let _ensure_callout_chip fall through to a live
    Remotion render — this script must stay FREE. A None chip on such a scene simply
    shows up as matches-real-pipeline=NO in the report."""
    if not callout:
        return None
    src = PROJECTS_ROOT / PROJECT / "clips" / f"scene_{sid:03d}.chip.mov"
    if not src.exists():
        print(f"  WARN: scene {sid} has a callout but no seeded chip.mov "
              f"({src}); rendering without chip (FREE-safety guard).")
        return None
    shutil.copy2(src, CHIP_DIR / src.name)
    sidecar = Path(str(src) + ".json")
    if sidecar.exists():
        shutil.copy2(sidecar, CHIP_DIR / sidecar.name)
    return _ensure_callout_chip(scene, callout, str(CHIP_DIR))


def _load_inputs() -> dict:
    """Reproduce the render setup once: windows, EDL, editing style, section-card
    map (+ per-card hold seconds), footage paths, and the ONE shared continuous
    Ken-Burns camera track set — the same objects render_all_scene_clips builds."""
    windows = load_scene_windows(PROJECT)
    windows_by_id = {s["id"]: s for s in windows}

    # ken_burns=True mirrors the render that produced this project's clips; the EDL
    # is already current so this only READS it (no regenerate/save → no mutation).
    edl = _load_or_create_edl(PROJECT, transition="cut", ken_burns=True)
    edl_by_id = {e["id"]: e for e in edl.get("scenes", [])}

    channel_id = _project_channel_id(PROJECT)
    edit_style = resolve_channel_editing(channel_id)

    # Section-card map + per-card hold seconds, exactly as assemble() builds them, so
    # the shared camera's per-scene footage-frame splits match the real render.
    cards = _cards_from_edl(edl, channel_id)
    if cards:
        secs = _card_seconds_by_scene(PROJECT, cards, SECTION_CARD_SECONDS)
        for sid, c in cards.items():
            c["card_seconds"] = secs.get(sid, SECTION_CARD_SECONDS)

    footage_paths = _build_footage_paths(windows)

    # The one shared continuous camera — computed ONCE and reused by every render
    # below (sequential and every parallel worker), just like render_all_scene_clips.
    camera_tracks = compute_camera_tracks(
        windows, edl_by_id, footage_paths,
        default_ken_burns=True,
        section_cards=cards or None,
        card_seconds=SECTION_CARD_SECONDS,
        ring_style=edit_style.get("ring"),
    )

    return {
        "windows": windows,
        "windows_by_id": windows_by_id,
        "edl_by_id": edl_by_id,
        "edit_style": edit_style,
        "footage_paths": footage_paths,
        "camera_tracks": camera_tracks,
        "cards": cards,
    }


def _build_tasks(inputs: dict, sids: list[int]) -> list[dict]:
    """One picklable task per benchmarked scene carrying the EXACT render_scene_clip
    arguments render_all_scene_clips would pass (motion is NOT passed — the continuous
    camera supersedes it)."""
    tasks: list[dict] = []
    for sid in sids:
        if sid not in inputs["windows_by_id"]:
            raise SystemExit(f"Scene {sid} not in {PROJECT} windows.")
        if sid not in inputs["footage_paths"]:
            raise SystemExit(f"No footage for scene {sid} in {PROJECT}.")
        scene = inputs["windows_by_id"][sid]
        entry = inputs["edl_by_id"].get(sid, {})
        overlays = entry.get("overlays", [])
        callout = next((o for o in overlays if o.get("kind") == "callout"), None)
        chip = _seed_chip(sid, callout, scene)
        tasks.append({
            "sid": sid,
            "scene": scene,
            "src": inputs["footage_paths"][sid],
            "transition": entry.get("transition", "cut"),
            "ken_burns": entry.get("ken_burns", True),
            "overlays": overlays,
            "edit_style": inputs["edit_style"],
            "camera": inputs["camera_tracks"].get(sid),
            "chip": chip,
        })
    return tasks


# ---------------------------------------------------------------------------
# The unit of work — module-level so ProcessPoolExecutor (spawn) can pickle it
# ---------------------------------------------------------------------------

def _worker(task: dict, out_dir: str) -> tuple[int, float]:
    """Render ONE scene via the real pipeline function and return (sid, seconds).
    Identical call to render_all_scene_clips'; ``motion`` is intentionally omitted."""
    sid = task["sid"]
    output_path = os.path.join(out_dir, f"scene_{sid:03d}.mp4")
    t0 = time.perf_counter()
    render_scene_clip(
        task["scene"], task["src"], output_path,
        transition=task["transition"],
        ken_burns=task["ken_burns"],
        overlays=task["overlays"],
        edit_style=task["edit_style"],
        camera=task["camera"],
        chip=task["chip"],
    )
    return sid, time.perf_counter() - t0


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------

def run_sequential(tasks: list[dict]) -> tuple[float, dict[int, float]]:
    """Baseline + pixel-identity reference: render every scene in order into
    /tmp/bench_seq/. Returns (wall_seconds, {sid: seconds})."""
    _fresh_dir(SEQ_DIR)
    per_scene: dict[int, float] = {}
    print(f"  Sequential baseline -> {SEQ_DIR}")
    t0 = time.perf_counter()
    for task in tasks:
        sid, el = _worker(task, str(SEQ_DIR))
        per_scene[sid] = el
        print(f"    scene {sid:3d}: {el:6.2f}s")
    total = time.perf_counter() - t0
    print(f"  Sequential total: {total:.2f}s")
    return total, per_scene


def run_parallel(tasks: list[dict], n: int) -> tuple[float, Path]:
    """Render the subset with a ProcessPoolExecutor(max_workers=n) into a fresh
    /tmp/bench_par_n/. Times the wall clock from submit to all-done. Returns
    (wall_seconds, out_dir)."""
    d = _fresh_dir(_par_dir(n))
    print(f"  Parallel N={n} -> {d}")
    t0 = time.perf_counter()
    with concurrent.futures.ProcessPoolExecutor(max_workers=n) as ex:
        futures = [ex.submit(_worker, task, str(d)) for task in tasks]
        for fut in concurrent.futures.as_completed(futures):
            fut.result()  # surface any worker exception loudly
    total = time.perf_counter() - t0
    print(f"  Parallel N={n} total: {total:.2f}s")
    return total, d


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def _fmt_mmss(seconds: float) -> str:
    m, s = divmod(int(round(seconds)), 60)
    return f"{m:d}m{s:02d}s"


def _report(
    sids: list[int],
    windows_by_id: dict[int, dict],
    seq_total: float,
    seq_times: dict[int, float],
    workers: list[int],
    par_totals: dict[int, float],
    seq_frame: dict[int, str],
    seq_byte: dict[int, str],
    real_frame: dict[int, str | None],
    par_frame: dict[int, dict[int, str]],
    par_byte: dict[int, dict[int, str]],
    full_frames: int,
) -> None:
    yn = lambda b: "YES" if b else "NO "

    print("\n" + "=" * 78)
    print("BENCHMARK REPORT — parallel scene-render sweep")
    print("=" * 78)
    print(f"project     : {PROJECT}")
    print(f"scenes      : {len(sids)}  {sids}")
    print(f"worker sweep: {workers}")
    print(f"cpu_count   : {os.cpu_count()}")

    # ---- per-scene sequential + identity -----------------------------------
    # byte-match / frame-match compare the PARALLEL clips (all swept N) against the
    # sequential clip; matches-real compares the sequential clip against the project's
    # existing pipeline output. framemd5 (frame-match) is authoritative.
    print("\nPer-scene sequential timing + identity")
    print(f"  {'sid':>3}  {'frames':>6}  {'dur(s)':>6}  {'seq(s)':>6}  "
          f"{'byte-match':>10}  {'frame-match':>11}  {'matches-real':>12}")
    subset_frames = 0
    for sid in sids:
        frames = int(windows_by_id[sid].get("frames") or 0)
        subset_frames += frames
        dur = frames / 60.0
        byte_ok = all(par_byte[n].get(sid) == seq_byte[sid] for n in workers)
        frame_ok = all(par_frame[n].get(sid) == seq_frame[sid] for n in workers)
        real_ok = real_frame.get(sid) is not None and real_frame[sid] == seq_frame[sid]
        print(f"  {sid:>3}  {frames:>6}  {dur:>6.2f}  {seq_times[sid]:>6.2f}  "
              f"{yn(byte_ok):>10}  {yn(frame_ok):>11}  {yn(real_ok):>12}")

    all_frame_ok = all(
        par_frame[n].get(sid) == seq_frame[sid] for n in workers for sid in sids
    )
    all_real_ok = all(
        real_frame.get(sid) is not None and real_frame[sid] == seq_frame[sid]
        for sid in sids
    )
    print(f"  subset frames: {subset_frames}   seq total: {seq_total:.2f}s")
    print(f"  parallel == sequential (framemd5, all N): {yn(all_frame_ok)}")
    print(f"  sequential == real pipeline (framemd5)  : {yn(all_real_ok)}")

    # ---- N -> par_total -> speedup -----------------------------------------
    print("\nWorker-count sweep")
    print(f"  {'N':>3}  {'par_total(s)':>12}  {'speedup':>8}  {'identical/seq':>13}")
    best_n, best_speedup = None, 0.0
    for n in workers:
        speedup = seq_total / par_totals[n] if par_totals[n] > 0 else 0.0
        ident = sum(1 for sid in sids if par_frame[n].get(sid) == seq_frame[sid])
        marker = ""
        if speedup > best_speedup:
            best_speedup, best_n = speedup, n
        print(f"  {n:>3}  {par_totals[n]:>12.2f}  {speedup:>7.2f}x  "
              f"{ident:>6}/{len(sids):<6}{marker}")
    print(f"  BEST: N={best_n}  ->  {best_speedup:.2f}x")

    # ---- full-video extrapolation ------------------------------------------
    seq_rate = seq_total / subset_frames if subset_frames else 0.0
    seq_full_est = seq_rate * full_frames
    par_full_est = seq_full_est / best_speedup if best_speedup else 0.0
    print("\nFull-video extrapolation (scene-render phase only)")
    print(f"  full video frames         : {full_frames}")
    print(f"  seq rate                  : {seq_rate * 1000:.2f} ms/frame")
    print(f"  seq full-render est        : {seq_full_est:.1f}s  ({_fmt_mmss(seq_full_est)})")
    print(f"  par full-render est (N={best_n}): {par_full_est:.1f}s  "
          f"({_fmt_mmss(par_full_est)})  @ {best_speedup:.2f}x")
    print("  CAVEAT (Amdahl): this speedup applies ONLY to the scene-render phase. "
          "assemble()")
    print("  also does audio assembly, concat/crossfade, subtitles, and mux — all "
          "unchanged —")
    print("  so the end-to-end run_render wall-clock improves by LESS than the factor "
          "above.")

    # ---- output paths -------------------------------------------------------
    print("\nOutput dirs (left on disk for inspection)")
    print(f"  sequential : {SEQ_DIR}")
    for n in workers:
        print(f"  parallel N={n}: {_par_dir(n)}")
    print(f"  seeded chips: {CHIP_DIR}")
    print("=" * 78)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Benchmark parallelizing the scene-render phase (FREE/local).",
    )
    ap.add_argument(
        "--scenes", type=int, default=len(SUBSET),
        help=f"Use the first N of the {len(SUBSET)}-scene subset (default: all).",
    )
    ap.add_argument(
        "--workers", type=str, default=DEFAULT_WORKERS,
        help=f'Comma list of worker counts to sweep (default: "{DEFAULT_WORKERS}").',
    )
    args = ap.parse_args()

    n_scenes = max(1, min(args.scenes, len(SUBSET)))
    sids = SUBSET[:n_scenes]
    workers = [int(x) for x in args.workers.split(",") if x.strip()]
    if not workers:
        raise SystemExit("--workers produced an empty list.")

    print(f"Loading inputs for {PROJECT} ...")
    _fresh_dir(CHIP_DIR)
    inputs = _load_inputs()
    full_frames = sum(int(s.get("frames") or 0) for s in inputs["windows"])
    print(f"  windows={len(inputs['windows'])} full_frames={full_frames} "
          f"footage={len(inputs['footage_paths'])} "
          f"camera_tracks={len(inputs['camera_tracks'])} "
          f"cards={len(inputs['cards'])}")

    tasks = _build_tasks(inputs, sids)

    # 1) Sequential baseline (+ identity reference).
    seq_total, seq_times = run_sequential(tasks)
    seq_frame = {sid: _frame_hash(SEQ_DIR / f"scene_{sid:03d}.mp4") for sid in sids}
    seq_byte = {sid: _byte_hash(SEQ_DIR / f"scene_{sid:03d}.mp4") for sid in sids}
    real_frame: dict[int, str | None] = {}
    for sid in sids:
        rp = PROJECTS_ROOT / PROJECT / "clips" / f"scene_{sid:03d}.mp4"
        real_frame[sid] = _frame_hash(rp) if rp.exists() else None

    # 2) Parallel sweep.
    par_totals: dict[int, float] = {}
    par_frame: dict[int, dict[int, str]] = {}
    par_byte: dict[int, dict[int, str]] = {}
    for n in workers:
        total, d = run_parallel(tasks, n)
        par_totals[n] = total
        par_frame[n] = {sid: _frame_hash(d / f"scene_{sid:03d}.mp4") for sid in sids}
        par_byte[n] = {sid: _byte_hash(d / f"scene_{sid:03d}.mp4") for sid in sids}

    _report(
        sids, inputs["windows_by_id"], seq_total, seq_times, workers, par_totals,
        seq_frame, seq_byte, real_frame, par_frame, par_byte, full_frames,
    )


if __name__ == "__main__":
    main()
