#!/usr/bin/env python3
"""Stage-2 assembly restructure — standalone repro + correctness proofs (FREE/local).

WHY
    Production assembly (services/assembly_service.assemble) renders SUBTITLE-FREE
    scene clips, then does TWO whole-video re-encodes: concat_clips_crossfade blends
    every seam and re-encodes ALL ~54k frames through one concat FILTER graph, and
    mux_audio then re-encodes the whole thing AGAIN to burn the karaoke subtitles.
    That's a ~45-50 min phase and stacks 3 encode generations on the picture.

    The Stage-2 restructure burns the subtitles into each SEGMENT up front and joins
    the segments by STREAM COPY, so the finished video is ONE clean generation and
    the two giant whole-video re-encodes disappear:
      * RUN-CLIP  — a plain scene, rendered by render_scene_clip(subtitles=<burn>):
        the global .ass is burned onto the clip after an integer PTS shift to the
        scene's timeline offset (bottom-anchored subtitles never touch the
        top-anchored chip/overlays, so the composite is order-independent).
      * BRIDGE    — a non-cut seam (scenes i, i+1), rendered by render_seam_bridge:
        the two extended flanks are blended EXACTLY as concat_clips_crossfade does
        (xfade=fadeblack / gblur+xfade=custom), then the .ass is burned onto the
        blended result (subtitle AFTER the blend), all in one encode.
    A 90-scene video with 20 non-cut seams partitions into 50 run-clips + 20 bridges
    == 70 ordered segments; ``concat -c copy`` joins them and a plain ``-c:v copy``
    mux adds the audio.

WHAT THIS TOOL DOES
    Reproduces the render setup EXACTLY (windows, current EDL read-only, channel
    editing style, section cards + per-card hold seconds, footage mp4-then-png, ONE
    shared continuous Ken-Burns camera) and writes EVERYTHING under /tmp/stage2_test/
    — it NEVER touches the project's clips/, video/, or final.mp4. Modes:

      run [--limit N] [--baseline]
        Build the whole-video .ass (build_subtitles with the SAME blank_windows
        assemble() computes), render the 70 segments (or the first N for a smoke
        test), ``concat -c copy`` them, assert the frame total, plain ``-c:v copy``
        mux the project's full_audio.mp3, then VALIDATE against the project's
        EXISTING final.mp4 (frame-count/res/fps/duration + per-frame SSIM/PSNR) and
        time each phase. The full 70-segment run is the ~45-min job.

      prove-safety
        Render a few scenes with render_scene_clip(subtitles=None) and framemd5- +
        byte-compare to the project's already-rendered clips/scene_NNN.mp4 — proves
        the render_scene_clip modification is inert in production (subtitles=None is
        byte/frame-identical to before).

      prove-subtitles
        Burn the global .ass onto a BLACK source (a) over the whole 53928-frame
        timeline and (b) per-segment with each segment's setpts offset, then concat;
        framemd5-compare the two. Proves the per-segment PTS-shift burn is
        bit-identical to the legacy whole-video burn (the subtitle-placement gate).

FREE / NO API / NO MUTATION
    Local ffmpeg + cv2 only. The EDL is already current so it is READ, never
    regenerated/saved. Fact chips are SEEDED from the project's clips/ into
    /tmp/stage2_test/clips/ so _ensure_callout_chip is a guaranteed cache hit (no
    Remotion/node, no paid calls). ``--baseline`` is the ONE opt-in exception (see
    its help) and is OFF by default.

RUN (from backend/, so the relative prompts/ lookups resolve):
    ./venv/bin/python tools/stage2_assembly.py prove-safety
    ./venv/bin/python tools/stage2_assembly.py prove-subtitles
    ./venv/bin/python tools/stage2_assembly.py run --limit 8        # smoke
    ./venv/bin/python tools/stage2_assembly.py run                  # FULL ~45-min job
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

# backend/ on sys.path so ``services.*`` imports resolve however python is invoked.
BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from services.assembly_service import (  # noqa: E402
    FPS,
    OUT_H,
    OUT_W,
    SECTION_CARD_SECONDS,
    _card_seconds_by_scene,
    _cards_from_edl,
    _ensure_callout_chip,
    _escape_filter_arg,
    _lead_in_seams,
    _load_or_create_edl,
    _project_channel_id,
    _render_stage2_run_clip,
    _scene_frame_count,
    _stage2_segments,
    _subtitle_filter_chain,
    SubtitleBurn,
    assemble,
    compute_camera_tracks,
    render_scene_clip,
    render_seam_bridge,
)
from services.channel_registry import resolve_channel_editing  # noqa: E402
from services.paths import PROJECTS_ROOT  # noqa: E402
from services.scene_timing_service import load_scene_windows  # noqa: E402
from services.subtitle_service import build_subtitles  # noqa: E402

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

# The 90-scene / 53,928-frame reference project (same one bench_parallel_render
# uses): all stills + Ken Burns, section cards, 20 non-cut seams, and its
# clips/ + video/final.mp4 are already rendered so we have an SSIM baseline.
PROJECT = "6-vegetables-you-plant-once-and-harvest-for-20-years"

ROOT = Path("/tmp/stage2_test")
CLIPS_DIR = ROOT / "clips"
VIDEO_DIR = ROOT / "video"
SAFETY_DIR = ROOT / "safety"

# Scenes for prove-safety: a plain KB still + two fact-chip KB stills, so both the
# no-chip and the chip encode paths are checked byte/frame-identical.
SAFETY_SCENES = [0, 34, 45]


# ---------------------------------------------------------------------------
# ffmpeg helpers
# ---------------------------------------------------------------------------

def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, capture_output=True, text=True)


def _byte_hash(path: str | Path) -> str:
    """sha256 of the raw container bytes (whole-file identity)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


_MD5_RE = re.compile(r"([0-9a-f]{32})\s*$")


def _framemd5_hashes(cmd: list[str]) -> list[str]:
    """Run an ffmpeg command that emits ``-f framemd5 -`` on stdout and return the
    ORDERED list of per-frame MD5 hashes ONLY (the trailing 32-hex field of each
    data line). Dropping the leading pts/dts/size fields makes the sequence
    PTS-independent — so a per-segment render (frames re-based to 0) compares equal
    to the same frames inside a whole-timeline render."""
    r = subprocess.run(cmd, check=True, capture_output=True, text=True)
    out: list[str] = []
    for ln in r.stdout.splitlines():
        if not ln or ln.startswith("#"):
            continue
        m = _MD5_RE.search(ln)
        if m:
            out.append(m.group(1))
    return out


def _clip_framemd5(path: str | Path) -> list[str]:
    return _framemd5_hashes([
        "ffmpeg", "-v", "error", "-i", str(path),
        "-map", "0:v:0", "-f", "framemd5", "-",
    ])


def _probe(path: str | Path) -> dict:
    r = _run([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=nb_frames,width,height,r_frame_rate,pix_fmt",
        "-show_entries", "format=duration",
        "-of", "json", str(path),
    ])
    j = json.loads(r.stdout)
    st = (j.get("streams") or [{}])[0]
    fmt = j.get("format") or {}
    return {
        "frames": int(st.get("nb_frames", 0)),
        "width": int(st.get("width", 0)),
        "height": int(st.get("height", 0)),
        "fps": st.get("r_frame_rate", "?"),
        "pix_fmt": st.get("pix_fmt", "?"),
        "duration": float(fmt.get("duration", 0.0)),
    }


def _ssim_psnr(seg_paths: list[str], ref: str | Path) -> dict:
    """Per-frame SSIM + PSNR of the assembled TEST video vs ``ref`` (the reference).

    The test side is fed to the metrics by DECODING the ordered segment files
    through the ``concat`` FILTER — NOT by reading the ``concat -c copy`` container.
    The segments carry the exact deliverable pixels (final.mp4's video IS their
    stream copy), but a two-input ssim/psnr framesync on the copied container stalls
    partway on these B-frame streams (it stalls the same way on the project's OWN
    pristine final.mp4 — an ssim quirk, not an output defect). The concat filter
    decodes each segment standalone with clean sequential PTS, sidestepping that
    entirely and covering every frame. No re-encode: the concat-filter output goes
    straight to the metric, so the compared pixels are the segments' own.

    ``shortest=1`` stops at the shorter side, so a partial (--limit smoke) test is
    compared ONLY against the matching LEADING span of ``ref``; on the full run both
    sides are 53928 frames. Two passes (ssim, psnr). Returns mean/min SSIM, the
    lowest-SSIM frame timestamps, and mean PSNR."""
    ssim_log = str(VIDEO_DIR / "ssim.log")
    psnr_log = str(VIDEO_DIR / "psnr.log")
    n = len(seg_paths)
    in_args: list[str] = []
    concat_in = ""
    for k, p in enumerate(seg_paths):
        in_args += ["-i", os.path.abspath(p)]
        concat_in += f"[{k}:v]"
    in_args += ["-i", str(ref)]
    for metric, log in (("ssim", ssim_log), ("psnr", psnr_log)):
        graph = (
            f"{concat_in}concat=n={n}:v=1:a=0[t];"
            f"[t][{n}:v]{metric}=stats_file={log}:shortest=1"
        )
        _run([
            "ffmpeg", "-v", "error", *in_args,
            "-filter_complex", graph, "-f", "null", "-",
        ])
    per_frame: list[tuple[int, float]] = []
    with open(ssim_log) as f:
        for ln in f:
            m_n = re.search(r"\bn:(\d+)", ln)
            m_all = re.search(r"\bAll:([0-9.]+)", ln)
            if m_n and m_all:
                per_frame.append((int(m_n.group(1)), float(m_all.group(1))))
    psnrs: list[float] = []
    with open(psnr_log) as f:
        for ln in f:
            m = re.search(r"\bpsnr_avg:([0-9.a-zA-Z]+)", ln)
            if m and m.group(1) not in ("inf", "nan"):
                try:
                    psnrs.append(float(m.group(1)))
                except ValueError:
                    pass
    ssim_vals = [v for _, v in per_frame]
    mean_ssim = sum(ssim_vals) / len(ssim_vals) if ssim_vals else 0.0
    lowest = sorted(per_frame, key=lambda t: t[1])[:8]
    return {
        "n": len(per_frame),
        "mean_ssim": mean_ssim,
        "min_ssim": min(ssim_vals) if ssim_vals else 0.0,
        "lowest": [(round((n - 1) / FPS, 2), v) for n, v in lowest],
        "mean_psnr": (sum(psnrs) / len(psnrs)) if psnrs else 0.0,
    }


# ---------------------------------------------------------------------------
# Input setup — reproduces render_all_scene_clips / assemble EXACTLY
# ---------------------------------------------------------------------------

def _build_footage_paths(windows: list[dict]) -> dict[int, str]:
    """{scene_id: absolute footage path}, mp4-then-png precedence (like run_render)."""
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


def _seed_chips(dest: Path) -> int:
    """Copy every already-rendered fact chip (``*.chip.mov`` + its ``.json``
    sidecar) from the project's clips/ into ``dest`` so _ensure_callout_chip is a
    guaranteed cache HIT — keeps the tool FREE (no Remotion/node, no API)."""
    src_clips = PROJECTS_ROOT / PROJECT / "clips"
    n = 0
    for mov in sorted(src_clips.glob("*.chip.mov")):
        shutil.copy2(mov, dest / mov.name)
        sidecar = Path(str(mov) + ".json")
        if sidecar.exists():
            shutil.copy2(sidecar, dest / sidecar.name)
        n += 1
    return n


def _load_inputs() -> dict:
    """Windows, current EDL (read-only), editing style, section-card map (+ per-card
    hold seconds), footage paths, and the ONE shared continuous Ken-Burns camera —
    the same objects render_all_scene_clips / assemble build."""
    windows = load_scene_windows(PROJECT)
    # ken_burns=True mirrors the render that produced this project; the EDL is
    # already current so this only READS it (no regenerate/save → no mutation).
    edl = _load_or_create_edl(PROJECT, transition="cut", ken_burns=True)
    edl_by_id = {e["id"]: e for e in edl.get("scenes", [])}

    channel_id = _project_channel_id(PROJECT)
    edit_style = resolve_channel_editing(channel_id)

    cards = _cards_from_edl(edl, channel_id)
    if cards:
        secs = _card_seconds_by_scene(PROJECT, cards, SECTION_CARD_SECONDS)
        for sid, c in cards.items():
            c["card_seconds"] = secs.get(sid, SECTION_CARD_SECONDS)

    footage_paths = _build_footage_paths(windows)

    camera_tracks = compute_camera_tracks(
        windows, edl_by_id, footage_paths,
        default_ken_burns=True,
        section_cards=cards or None,
        card_seconds=SECTION_CARD_SECONDS,
        ring_style=edit_style.get("ring"),
    )
    return {
        "windows": windows,
        "edl_by_id": edl_by_id,
        "edit_style": edit_style,
        "cards": cards,
        "footage_paths": footage_paths,
        "camera_tracks": camera_tracks,
    }


def _build_ass(inputs: dict) -> str:
    """Build the whole-video karaoke .ass with the SAME blank_windows assemble()
    computes (each section card's [start, start+card_frames/FPS] span suppresses the
    cue it carries), written under /tmp — never the project."""
    windows = inputs["windows"]
    cards = inputs["cards"]
    blank_windows = None
    if cards:
        windows_by_id = {s["id"]: s for s in windows}
        blank_windows = []
        for sid in cards:
            s = windows_by_id[sid]
            scene_frames = _scene_frame_count(s)
            cs = cards[sid].get("card_seconds", SECTION_CARD_SECONDS)
            card_frames = min(round(cs * FPS), scene_frames)
            start = s["start_time"]
            blank_windows.append((start, round(start + card_frames / FPS, 3)))
    ass_path = str(VIDEO_DIR / "subtitles.ass")
    build_subtitles(PROJECT, ass_path, blank_windows=blank_windows)
    return ass_path


# ---------------------------------------------------------------------------
# Segment rendering
# ---------------------------------------------------------------------------

def _render_run_clip(inputs: dict, seg: dict, ass_path: str) -> str:
    """Render one run-clip scene through the PRODUCTION Stage-2 renderer
    (_render_stage2_run_clip) — the exact production params (per-scene transition /
    ken_burns / overlays / edit_style / camera / chip) plus the subtitle burn at the
    scene's global frame offset — writing only under /tmp (CLIPS_DIR). Delegating to
    the production function is the point: the tool proves the SAME code the pipeline
    ships, not a reimplementation."""
    scene = inputs["windows"][seg["i"]]
    sid = scene["id"]
    src = inputs["footage_paths"].get(sid)
    if not src or not os.path.exists(src):
        raise FileNotFoundError(f"No footage for scene {sid}")
    return _render_stage2_run_clip(
        scene, src, str(CLIPS_DIR / f"scene_{sid:03d}.sub.mp4"),
        edl_by_id=inputs["edl_by_id"],
        cards=inputs["cards"] or None,
        edit_style=inputs["edit_style"],
        camera_tracks=inputs["camera_tracks"],
        clips_dir=str(CLIPS_DIR),
        ass_path=ass_path,
        global_offset=seg["offset"],
        transition="cut",
        ken_burns=True,
    )


def _render_bridge(inputs: dict, seg: dict, ass_path: str) -> str:
    """Render one seam bridge via render_seam_bridge (blend + subtitle-after-blend)."""
    i = seg["i"]
    out = str(CLIPS_DIR / f"bridge_{i:03d}.mp4")
    render_seam_bridge(
        PROJECT,
        inputs["windows"],
        inputs["edl_by_id"],
        i,
        inputs["footage_paths"],
        inputs["cards"] or None,
        inputs["edit_style"],
        inputs["camera_tracks"],
        ass_path,
        out,
        transition="cut",
        ken_burns=True,
    )
    return out


# ---------------------------------------------------------------------------
# Mode: run  (full assembly, or the first --limit segments for a smoke test)
# ---------------------------------------------------------------------------

def cmd_run(args: argparse.Namespace) -> None:
    VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    CLIPS_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Stage-2 assembly repro — {PROJECT}")
    t0 = time.perf_counter()
    inputs = _load_inputs()
    windows = inputs["windows"]
    seam_lefts = set(_lead_in_seams(windows, inputs["edl_by_id"]))
    segs = _stage2_segments(windows, seam_lefts)
    n_run = sum(1 for s in segs if s["kind"] == "run")
    n_bridge = sum(1 for s in segs if s["kind"] == "bridge")
    total_frames = sum(s["count"] for s in segs)
    t_load = time.perf_counter() - t0
    print(f"  scenes={len(windows)}  segments={len(segs)} "
          f"({n_run} run + {n_bridge} bridge)  frames={total_frames}")

    n_chips = _seed_chips(CLIPS_DIR)
    ass_path = _build_ass(inputs)
    print(f"  seeded {n_chips} fact chip(s); built .ass -> {ass_path}")

    limit = args.limit if args.limit else len(segs)
    run_segs = segs[:limit]
    smoke = limit < len(segs)
    if smoke:
        print(f"  SMOKE: rendering the first {limit} of {len(segs)} segments "
              f"({[s['kind'] for s in run_segs]})")

    # Render each segment; time run-clips and bridges separately.
    t_run = t_bridge = 0.0
    ordered: list[str] = []
    for k, seg in enumerate(run_segs):
        tag = f"{seg['kind']}[{seg['i']}] ids={seg['ids']} off={seg['offset']}"
        s0 = time.perf_counter()
        if seg["kind"] == "run":
            path = _render_run_clip(inputs, seg, ass_path)
            t_run += time.perf_counter() - s0
        else:
            path = _render_bridge(inputs, seg, ass_path)
            t_bridge += time.perf_counter() - s0
        ordered.append(path)
        print(f"    [{k + 1:>2}/{len(run_segs)}] {tag}  {time.perf_counter() - s0:5.1f}s")

    # concat -c copy the ordered segments.
    concat_txt = str(VIDEO_DIR / "concat.txt")
    with open(concat_txt, "w") as f:
        for p in ordered:
            f.write(f"file '{os.path.abspath(p)}'\n")
    silent = str(VIDEO_DIR / "video_no_audio.mp4")
    s0 = time.perf_counter()
    _run([
        "ffmpeg", "-y", "-v", "error",
        "-f", "concat", "-safe", "0", "-i", concat_txt,
        "-c", "copy", silent,
    ])
    t_concat = time.perf_counter() - s0

    expected = sum(s["count"] for s in run_segs)
    got = _probe(silent)["frames"]
    print(f"\n  concat -c copy -> {silent}")
    print(f"  frames: got={got}  expected={expected}  "
          f"{'OK' if got == expected else 'MISMATCH'}")
    if got != expected:
        raise SystemExit(
            f"Frame-count assert FAILED: concat has {got}, expected {expected}."
        )
    if not smoke and got != 53928:
        raise SystemExit(f"Full run frame total {got} != 53928.")

    # Plain -c:v copy mux of the project's narration (subtitles already burned in).
    audio = str(PROJECTS_ROOT / PROJECT / "video" / "full_audio.mp3")
    final = str(ROOT / "final.mp4")
    s0 = time.perf_counter()
    _run([
        "ffmpeg", "-y", "-v", "error",
        "-i", silent, "-i", audio,
        "-map", "0:v", "-map", "1:a", "-af", "apad",
        "-c:v", "copy", "-c:a", "aac", "-shortest", final,
    ])
    t_mux = time.perf_counter() - s0
    print(f"  mux -c:v copy -> {final}")

    # ---- Validation vs the project's EXISTING final.mp4 --------------------
    ref = str(PROJECTS_ROOT / PROJECT / "video" / "final.mp4")
    if args.baseline:
        ref = _render_baseline(inputs)
    tp, rp = _probe(final), _probe(ref)
    print("\n  Container check (test vs baseline)")
    for key in ("frames", "width", "height", "fps", "pix_fmt", "duration"):
        tv, rv = tp[key], rp[key]
        same = (abs(tv - rv) < 0.05) if key == "duration" else (tv == rv)
        print(f"    {key:>9}: {tv!s:>12}  vs  {rv!s:>12}  {'OK' if same else 'DIFF'}")

    s0 = time.perf_counter()
    sv = _ssim_psnr(ordered, ref)
    t_val = time.perf_counter() - s0
    print("\n  Per-frame SSIM / PSNR (test vs baseline)")
    print(f"    frames compared : {sv['n']}")
    print(f"    mean SSIM       : {sv['mean_ssim']:.6f}")
    print(f"    min  SSIM       : {sv['min_ssim']:.6f}")
    print(f"    mean PSNR       : {sv['mean_psnr']:.2f} dB")
    print(f"    lowest-SSIM @ (t_sec, ssim): {sv['lowest']}")

    print("\n  Phase timings")
    print(f"    load inputs     : {t_load:6.1f}s")
    print(f"    run-clips ({n_run:>2}) : {t_run:6.1f}s")
    print(f"    bridges  ({n_bridge:>2}) : {t_bridge:6.1f}s")
    print(f"    concat copy     : {t_concat:6.1f}s")
    print(f"    mux copy        : {t_mux:6.1f}s")
    print(f"    validation      : {t_val:6.1f}s")
    print("    NOTE: the current production assemble() for this project costs "
          "~50 min (two whole-video re-encodes: concat-filter + subtitle mux).")


def _render_baseline(inputs: dict) -> str:
    """OPT-IN (--baseline, OFF by default): re-render a FULL baseline via the OLD
    production assemble() for a same-code SSIM reference. This runs the legacy
    ~50-min two-re-encode path and, unlike every other tool path, DOES write inside
    the project (its clips/ cache + video/), landing at video/final_stage2_base.mp4
    (final.mp4 is left intact). Only use it knowingly."""
    print("  --baseline: re-rendering the OLD assemble() path (~50 min; writes in "
          "the project dir). final.mp4 is preserved.")
    footage_paths = inputs["footage_paths"]
    return assemble(
        PROJECT, footage_paths,
        transition="cut", ken_burns=True,
        section_cards=True, section_transitions=True,
        output_name="final_stage2_base.mp4",
    )


# ---------------------------------------------------------------------------
# Mode: prove-safety
# ---------------------------------------------------------------------------

def cmd_prove_safety(args: argparse.Namespace) -> None:
    """Render each SAFETY_SCENES scene with render_scene_clip(subtitles=None) and
    compare to the project's already-rendered plain clips/scene_NNN.mp4 — proving
    the render_scene_clip change is inert when no subtitle is requested."""
    SAFETY_DIR.mkdir(parents=True, exist_ok=True)
    inputs = _load_inputs()
    _seed_chips(SAFETY_DIR)
    windows_by_id = {s["id"]: s for s in inputs["windows"]}

    print("prove-safety — render_scene_clip(subtitles=None) vs production clips")
    all_ok = True
    for sid in SAFETY_SCENES:
        scene = windows_by_id.get(sid)
        real = PROJECTS_ROOT / PROJECT / "clips" / f"scene_{sid:03d}.mp4"
        if scene is None or not real.exists():
            print(f"  scene {sid}: SKIP (no scene/clip)")
            continue
        src = inputs["footage_paths"].get(sid)
        entry = inputs["edl_by_id"].get(sid, {})
        overlays = entry.get("overlays", [])
        callout = next((o for o in overlays if o.get("kind") == "callout"), None)
        chip = _ensure_callout_chip(scene, callout, str(SAFETY_DIR))
        out = str(SAFETY_DIR / f"scene_{sid:03d}.mp4")
        render_scene_clip(
            scene, src, out,
            transition=entry.get("transition", "cut"),
            ken_burns=entry.get("ken_burns", True),
            overlays=overlays,
            edit_style=inputs["edit_style"],
            camera=inputs["camera_tracks"].get(sid),
            chip=chip,
            subtitles=None,
        )
        frame_ok = _clip_framemd5(out) == _clip_framemd5(real)
        byte_ok = _byte_hash(out) == _byte_hash(real)
        all_ok = all_ok and frame_ok
        has_chip = "chip" if chip is not None else "no-chip"
        print(f"  scene {sid:>2} ({has_chip}): framemd5={'YES' if frame_ok else 'NO'}  "
              f"byte={'YES' if byte_ok else 'NO'}")
    print(f"\n  PRODUCTION-SAFETY (framemd5 identical, all scenes): "
          f"{'YES' if all_ok else 'NO'}")
    if not all_ok:
        raise SystemExit("prove-safety FAILED — subtitles=None changed the output.")


# ---------------------------------------------------------------------------
# Mode: prove-subtitles
# ---------------------------------------------------------------------------

def cmd_prove_subtitles(args: argparse.Namespace) -> None:
    """Burn the global .ass onto a BLACK source two ways and framemd5-compare:
      WHOLE      — one render over the full frame timeline (== the legacy mux burn).
      PER-SEGMENT — each of the 70 segments rendered with its setpts offset, then
                    the per-frame hashes concatenated in order.
    Identical hash sequences ⇒ the per-segment PTS-shift burn is bit-exact."""
    VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    inputs = _load_inputs()
    windows = inputs["windows"]
    seam_lefts = set(_lead_in_seams(windows, inputs["edl_by_id"]))
    segs = _stage2_segments(windows, seam_lefts)
    total = sum(s["count"] for s in segs)
    ass_path = _build_ass(inputs)
    esc = _escape_filter_arg(ass_path)

    print(f"prove-subtitles — {len(segs)} segments, {total} frames total")

    # WHOLE: black frames at global PTS, plain subtitles filter (the legacy burn).
    t0 = time.perf_counter()
    whole = _framemd5_hashes([
        "ffmpeg", "-v", "error",
        "-f", "lavfi", "-i", f"color=black:s={OUT_W}x{OUT_H}:r={FPS}",
        "-vf", f"format=yuv420p,subtitles='{esc}'",
        "-frames:v", str(total), "-f", "framemd5", "-",
    ])
    t_whole = time.perf_counter() - t0

    # PER-SEGMENT: each segment rendered with its own setpts offset, hashes joined.
    t0 = time.perf_counter()
    per: list[str] = []
    for seg in segs:
        burn = SubtitleBurn(ass_path=ass_path, frame_offset=seg["offset"], sig="")
        chain = _subtitle_filter_chain(burn)
        per.extend(_framemd5_hashes([
            "ffmpeg", "-v", "error",
            "-f", "lavfi", "-i", f"color=black:s={OUT_W}x{OUT_H}:r={FPS}",
            "-vf", f"format=yuv420p,{chain}",
            "-frames:v", str(seg["count"]), "-f", "framemd5", "-",
        ]))
    t_per = time.perf_counter() - t0

    same = whole == per
    print(f"  whole frames    : {len(whole)}  ({t_whole:.1f}s)")
    print(f"  per-seg frames  : {len(per)}   ({t_per:.1f}s)")
    if not same:
        # Report the first divergence for diagnosis.
        first = next(
            (k for k in range(min(len(whole), len(per))) if whole[k] != per[k]),
            None,
        )
        print(f"  first divergence at frame index: {first}")
    print(f"\n  SUBTITLE-PLACEMENT bit-exact (framemd5 whole == per-segment): "
          f"{'YES' if same else 'NO'}")
    if not same:
        raise SystemExit("prove-subtitles FAILED — per-segment burn diverges.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Stage-2 assembly repro + correctness proofs (FREE/local).",
    )
    sub = ap.add_subparsers(dest="mode", required=True)

    p_run = sub.add_parser("run", help="Stage-2 assembly + validation vs final.mp4.")
    p_run.add_argument(
        "--limit", type=int, default=0,
        help="Render only the first N of the 70 segments (smoke test). 0 = full.",
    )
    p_run.add_argument(
        "--baseline", action="store_true",
        help="OPT-IN: re-render a full OLD-path assemble() baseline (~50 min; "
             "writes in the project dir; final.mp4 preserved). Default OFF uses the "
             "project's EXISTING final.mp4 as the SSIM baseline.",
    )
    p_run.set_defaults(func=cmd_run)

    p_s = sub.add_parser("prove-safety", help="subtitles=None == production clip.")
    p_s.set_defaults(func=cmd_prove_safety)

    p_t = sub.add_parser(
        "prove-subtitles", help="per-segment subtitle burn == whole-video burn.",
    )
    p_t.set_defaults(func=cmd_prove_subtitles)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
