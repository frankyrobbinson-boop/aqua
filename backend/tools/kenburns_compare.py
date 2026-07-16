#!/usr/bin/env python3
"""kenburns_compare.py -- Ken Burns MOTION comparison harness (PNG stills only).

Why this exists
---------------
The committed pipeline Ken Burns (``assembly_service.render_scene_clip``, the
``ken_burns and is_png`` branch) is a single LINEAR center zoom-in 1.0 -> 1.08
on every still: supersample -> per-frame ``scale=eval=frame`` -> center-crop ->
tblend. Every shot moves identically, and every shot resets to a dead stop at
the cut. We're prototyping two directions past that:

  (1) VARIED moves -- a different pan/zoom per scene, EASED (inOutSine), so the
      camera has intent instead of one canned push.
  (2) CONTINUOUS cross-clip motion -- ONE camera move that flies across the
      whole run, velocity-matched across the interior cuts so the sequence reads
      as a single take rather than N little zooms.

This tool renders labeled COMPARISON clips only. It imports nothing from the
pipeline and writes nothing into any project -- it just reads a project's
existing PNG stills + scene durations and drives ffmpeg. No script/scene/TTS/
image generation, no API, no paid calls: pure local ffmpeg on stills that
already exist on disk.

Motion model (generalizes the shipping chain)
---------------------------------------------
A move = (z0, z1, cx0, cy0, cx1, cy1): zoom start/end (each >= 1.0) and
normalized focal center start/end (cx, cy in [0,1]; 0.5 = frame center). Per
hi-fps frame n in [0, denom] (denom = hi_frames - 1) the progress P(n) is either
LINEAR ``n/denom`` or EASED inOutSine ``0.5-0.5*cos(PI*n/denom)``, and
Z=z0+(z1-z0)P, CX=cx0+(cx1-cx0)P, CY=cy0+(cy1-cy0)P. The per-scene filter is the
shipping chain with those made general (see kb_chain). The SANITY CHECK below
proves the baseline params (z 1.0->1.08, c 0.5,0.5, LINEAR) reduce EXACTLY to the
shipping center-zoom: with CX=0.5, x = 0.5*(sw*Z - sw) = 0.5*sw*(Z-1), which is
the shipping ``x_max*n/denom`` with x_max = sw*(1.08-1)/2.

Canvas matches the pipeline (assembly_service OUT_W/OUT_H/FPS). Those are
hardcoded here with the same comment the sibling ``transition_compare.py`` uses,
rather than importing assembly_service (its module pulls the whole services
package -- channel/edl/graphics/timing/subtitle/voice -- which a standalone
ffmpeg tool has no business dragging in).

How to run
----------
Render the three comparison clips + filmstrips into /tmp/kb, fast-iteration
quality (spatial x2, temporal x2), from the default mosquito project::

    python backend/tools/kenburns_compare.py

Drop temporal supersample (skips tblend/framestep; ~2x faster, steppier pans)::

    python backend/tools/kenburns_compare.py --temporal 1

Point at another project / change how many seconds of scenes to use / out dir::

    python backend/tools/kenburns_compare.py \
        --project ~/Documents/Aqua/projects/<slug> --seconds 45 --out-dir /tmp/kb
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import time
from pathlib import Path

# --- Canvas: match the pipeline (assembly_service OUT_W/OUT_H/FPS). Hardcoded,
# like the sibling transition_compare.py, to avoid importing assembly_service and
# its whole services-package dependency chain into a standalone ffmpeg tool. -----
OUT_W, OUT_H, FPS = 1920, 1080, 25

DEFAULT_PROJECT = (
    Path.home()
    / "Documents/Aqua/projects/this-5-bucket-wiped-out-the-mosquitoes-in-my-yard"
)

# A real font so drawtext can render the clip label (fontconfig fallback if none).
FONTFILE = next(
    (
        p
        for p in (
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/Library/Fonts/Arial.ttf",
        )
        if os.path.exists(p)
    ),
    None,
)

# --- BASELINE: the shipping move, applied to every scene. Center zoom-in
# 1.0 -> 1.08, LINEAR (see assembly_service KB_END_ZOOM = 1.08). ----------------
KB_END_ZOOM = 1.08
BASELINE_MOVE = (1.0, KB_END_ZOOM, 0.5, 0.5, 0.5, 0.5)

# --- VARIED: one distinct EASED move per scene, cycled in order (no two adjacent
# identical). Each is (z0, z1, cx0, cy0, cx1, cy1). ------------------------------
VARIED_MOVES: list[tuple[float, float, float, float, float, float]] = [
    (1.00, 1.10, 0.50, 0.50, 0.50, 0.50),  # zoom-in center
    (1.10, 1.00, 0.50, 0.50, 0.50, 0.50),  # zoom-out center
    (1.15, 1.15, 0.20, 0.50, 0.80, 0.50),  # pan right
    (1.15, 1.15, 0.80, 0.50, 0.20, 0.50),  # pan left
    (1.00, 1.12, 0.50, 0.62, 0.50, 0.40),  # zoom-in drift up
    (1.14, 1.14, 0.32, 0.32, 0.68, 0.62),  # diagonal down-right
    (1.15, 1.15, 0.50, 0.25, 0.50, 0.75),  # pan down
    (1.02, 1.15, 0.40, 0.50, 0.64, 0.50),  # zoom-in + pan right
]

# --- CONTINUOUS: one global camera trajectory across the WHOLE run. Zoom and
# focal center are affine in a global progress Gp(s), s in [0,1] over the run's
# total hi-frames. Gp is a trapezoidal-velocity integral: it ramps up from rest
# over the first RAMP seconds, cruises at constant velocity (so all INTERIOR cuts
# are velocity-matched -- Gp is linear there), then ramps to rest over the last
# RAMP seconds. Because Z/CX/CY are affine in Gp and every scene evaluates the
# SAME global Gp at its own global-frame offset, adjacent scenes meet at one
# shared global frame with matching value AND slope -> seamless, ramps included.
CONT_Z0, CONT_Z1 = 1.00, 1.18
CONT_CX0, CONT_CX1 = 0.34, 0.66
CONT_CY0, CONT_CY1 = 0.53, 0.45
CONT_RAMP_SECONDS = 0.8


# --- ffmpeg helpers (mirror transition_compare / assembly_service) -------------
def _run(cmd: list[str], what: str) -> None:
    """Run ffmpeg, surfacing stderr on failure."""
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode("utf-8", errors="replace") if e.stderr else ""
        raise RuntimeError(f"ffmpeg failed ({what}):\n{stderr}") from e


def probe_duration(path: str) -> float:
    out = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(path),
        ],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    return float(out)


def _scene_frames(duration: float) -> int:
    """Output frame count for a scene -- identical to assembly_service.
    _scene_frame_count's fallback (these scene_windows have no ``frames`` field),
    so BASELINE renders to the exact same length the pipeline would."""
    return max(1, round(max(0.1, duration) * FPS))


# --- Motion-model expression builders ------------------------------------------
def _p_expr(mode: str, denom: int) -> str:
    """Progress P(n) as an ffmpeg expr. ``n`` is the post-fps hi-frame index."""
    if mode == "linear":
        return f"(n/{denom})"
    return f"(0.5-0.5*cos(PI*n/{denom}))"  # inOutSine


def affine_exprs(
    move: tuple[float, float, float, float, float, float], denom: int, mode: str
) -> tuple[str, str, str]:
    """(Z, CX, CY) exprs for a single (z0,z1,cx0,cy0,cx1,cy1) move under P(mode).
    Coefficients are parenthesized so a negative delta (zoom-out / leftward pan)
    stays valid ffmpeg syntax."""
    z0, z1, cx0, cy0, cx1, cy1 = move
    p = _p_expr(mode, denom)
    z = f"({z0:.6f}+({z1 - z0:.6f})*{p})"
    cx = f"({cx0:.6f}+({cx1 - cx0:.6f})*{p})"
    cy = f"({cy0:.6f}+({cy1 - cy0:.6f})*{p})"
    return z, cx, cy


def _gp_value(s: float, r: float) -> float:
    """Python twin of the ffmpeg global-progress Gp(s) (used only for the
    self-check). Trapezoidal-velocity integral, normalized to Gp(0)=0, Gp(1)=1."""
    a = 2.0 * r * (1.0 - r)
    if s < r:
        return s * s / a
    if s < 1.0 - r:
        return (s - r / 2.0) / (1.0 - r)
    return 1.0 - (1.0 - s) * (1.0 - s) / a


def _gp_expr(h_start: int, D: int, r: float) -> str:
    """Global progress Gp(s) as an ffmpeg expr, with s = (h_start + n)/D the
    run-global normalized position of this scene's local hi-frame n. Commas in
    if()/lt() are safe: every value this feeds is single-quoted in kb_chain."""
    a = 2.0 * r * (1.0 - r)
    s = f"(({h_start}+n)/{D})"
    r1 = 1.0 - r
    return (
        f"if(lt({s},{r:.9f}),"
        f"({s})*({s})/{a:.9f},"
        f"if(lt({s},{r1:.9f}),"
        f"(({s})-{r / 2.0:.9f})/{r1:.9f},"
        f"1-(1-({s}))*(1-({s}))/{a:.9f}))"
    )


def continuous_exprs(h_start: int, D: int, r: float) -> tuple[str, str, str]:
    """(Z, CX, CY) exprs for one scene sampled off the global trajectory."""
    gp = _gp_expr(h_start, D, r)
    z = f"({CONT_Z0:.6f}+({CONT_Z1 - CONT_Z0:.6f})*({gp}))"
    cx = f"({CONT_CX0:.6f}+({CONT_CX1 - CONT_CX0:.6f})*({gp}))"
    cy = f"({CONT_CY0:.6f}+({CONT_CY1 - CONT_CY0:.6f})*({gp}))"
    return z, cx, cy


def kb_chain(
    z_expr: str, cx_expr: str, cy_expr: str, super_s: int, temporal: int
) -> str:
    """The per-scene Ken Burns filter chain -- the shipping chain generalized to
    arbitrary Z/CX/CY exprs. sw/sh = supersampled canvas; the zoom scale + focal
    crop run per-frame (eval=frame / crop's n), then tblend+framestep (temporal
    supersample) and the down-scale to OUT_W x OUT_H. Z appears in the scale
    (w,h) AND both crop offsets; CX/CY once each. Every expr value is single-
    quoted so commas inside if()/lt() (continuous mode) don't split the graph."""
    sw, sh = OUT_W * super_s, OUT_H * super_s
    fps_hi = FPS * temporal
    z = z_expr
    parts = [
        f"scale={sw}:{sh}:force_original_aspect_ratio=increase:flags=lanczos",
        f"crop={sw}:{sh}",
        f"fps={fps_hi}",
        "format=yuv420p",
        f"scale=w='{sw}*({z})':h='{sh}*({z})':eval=frame:flags=lanczos",
        (
            f"crop={sw}:{sh}:"
            f"x='({cx_expr})*({sw}*({z})-{sw})':"
            f"y='({cy_expr})*({sh}*({z})-{sh})'"
        ),
    ]
    if temporal > 1:
        # Pair of hi-frames -> averaged blend -> drop every other, landing back at
        # FPS with motion blur. Only valid when fps_hi > FPS (temporal > 1).
        parts.append("tblend=all_mode=average")
        parts.append("framestep=2")
    parts.append(f"scale={OUT_W}:{OUT_H}:flags=lanczos")
    return ",".join(parts)


# --- Rendering -----------------------------------------------------------------
def render_scene_clip(
    png: Path, frames: int, chain: str, out_path: Path, what: str
) -> None:
    """Render one scene's still to a silent OUT_W x OUT_H clip via `chain`.
    Mirrors assembly_service's KB invocation: loop the still, cap at `frames`
    output frames so the move completes on the last rendered frame."""
    _run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-stream_loop", "-1", "-i", str(png),
            "-vf", chain,
            "-frames:v", str(frames),
            "-an",
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-pix_fmt", "yuv420p",
            str(out_path),
        ],
        what,
    )


def _drawtext_label(text: str) -> str:
    """drawtext for the clip label -- small, top-left, in a translucent box."""
    font = f"fontfile={FONTFILE}:" if FONTFILE else ""
    return (
        f"drawtext={font}text='{text}':x=28:y=28:"
        f"fontsize=40:fontcolor=white:box=1:boxcolor=black@0.55:boxborderw=14"
    )


def concat_and_label(
    scene_clips: list[Path], label: str, out_path: Path, work_dir: Path
) -> None:
    """Stitch the per-scene clips (concat demuxer -- they share codec/params) and
    burn the label over the stitched stream in one re-encode."""
    list_path = work_dir / "concat.txt"
    with open(list_path, "w") as f:
        for c in scene_clips:
            f.write(f"file '{c}'\n")
    _run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "concat", "-safe", "0", "-i", str(list_path),
            "-vf", _drawtext_label(label),
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-pix_fmt", "yuv420p",
            str(out_path),
        ],
        f"concat+label {out_path.name}",
    )


def render_filmstrip(
    clip_path: Path, out_path: Path, work_dir: Path, n: int = 8, tile_w: int = 320
) -> None:
    """A horizontal strip of `n` frames sampled evenly across the whole clip, for
    a quick at-a-glance read of the move. Frame-accurate output seek, then tile."""
    dur = probe_duration(clip_path)
    frames_dir = work_dir / "_frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    frame_paths = []
    for i in range(n):
        t = dur * (i + 0.5) / n  # bin centers: avoids the EOF edge at t==dur
        fp = frames_dir / f"f_{i:02d}.png"
        _run(
            [
                "ffmpeg", "-y", "-v", "error",
                "-i", str(clip_path), "-ss", f"{t:.3f}", "-frames:v", "1",
                "-vf", f"scale={tile_w}:-1", str(fp),
            ],
            f"filmstrip frame {i} of {out_path.name}",
        )
        frame_paths.append(fp)
    _run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-i", str(frames_dir / "f_%02d.png"), "-frames:v", "1",
            "-vf", f"tile={n}x1", str(out_path),
        ],
        f"tile filmstrip {out_path.name}",
    )
    for fp in frame_paths:
        fp.unlink(missing_ok=True)
    frames_dir.rmdir()


# --- Self-checks ---------------------------------------------------------------
def sanity_check_baseline(super_s: int) -> None:
    """Prove the generalized chain, fed the BASELINE move, reproduces the shipping
    center-zoom math (assembly_service:672-684) frame-for-frame. With CX=0.5 the
    focal crop x = 0.5*(sw*Z - sw) = 0.5*sw*(Z-1), which equals the shipping
    x_max*n/denom (x_max = sw*(KB_END_ZOOM-1)/2); the zoom scale sw*Z equals the
    shipping sw*(1+(KB_END_ZOOM-1)*n/denom). Raises if the equivalence breaks."""
    sw = OUT_W * super_s
    x_max = sw * (KB_END_ZOOM - 1.0) / 2.0
    for denom in (1, 100, 249):
        for n in (0, denom // 2, denom):
            p = n / denom
            z = 1.0 + (KB_END_ZOOM - 1.0) * p       # baseline Z, LINEAR
            harness_x = 0.5 * (sw * z - sw)          # generalized crop x (CX=0.5)
            shipping_x = x_max * n / denom           # shipping crop x
            assert abs(harness_x - shipping_x) < 1e-6, (n, denom, harness_x)
            harness_w = sw * z                       # generalized zoom scale
            shipping_w = sw * (1.0 + (KB_END_ZOOM - 1.0) * n / denom)
            assert abs(harness_w - shipping_w) < 1e-6, (n, denom, harness_w)


def sanity_check_continuous(r: float) -> None:
    """Guard the global-progress curve: Gp(0)=0, Gp(1)=1, monotone, and C0 at
    both trapezoid knots (velocity continuity is what keeps interior cuts seamless
    and makes the start/end ramps join the cruise without a jerk)."""
    assert abs(_gp_value(0.0, r) - 0.0) < 1e-9
    assert abs(_gp_value(1.0, r) - 1.0) < 1e-9
    assert abs(_gp_value(r - 1e-7, r) - _gp_value(r + 1e-7, r)) < 1e-4
    assert abs(_gp_value(1 - r - 1e-7, r) - _gp_value(1 - r + 1e-7, r)) < 1e-4
    prev = -1.0
    for i in range(101):
        cur = _gp_value(i / 100.0, r)
        assert cur >= prev - 1e-9, "Gp must be monotone non-decreasing"
        prev = cur


# --- Scene selection -----------------------------------------------------------
def select_scenes(
    windows: list[dict], footage_dir: Path, target_seconds: float
) -> list[dict]:
    """Scenes in order until accumulated duration first reaches ~target_seconds,
    skipping any scene whose still is missing. Uses the real per-scene durations."""
    chosen: list[dict] = []
    total = 0.0
    for scene in windows:
        png = footage_dir / f"scene_{scene['id']:03d}.png"
        if not png.exists():
            continue
        chosen.append(scene)
        total += scene["duration"]
        if total >= target_seconds:
            break
    return chosen


# --- Main ----------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(
        description="Render Ken Burns motion comparison clips from PNG stills."
    )
    ap.add_argument("--project", default=str(DEFAULT_PROJECT))
    ap.add_argument("--out-dir", default="/tmp/kb")
    ap.add_argument("--seconds", type=float, default=45.0,
                    help="accumulate scenes until ~this many seconds")
    ap.add_argument("--super", type=int, default=2, dest="super_s",
                    help="spatial supersample (2 = fast iteration, 4 = final)")
    ap.add_argument("--temporal", type=int, default=2,
                    help="temporal supersample (2 = motion blur, 1 = skip/faster)")
    args = ap.parse_args()

    project = Path(args.project).expanduser()
    footage_dir = project / "footage"
    windows = json.loads((project / "scene_windows.json").read_text())
    out_dir = Path(args.out_dir)
    work_root = out_dir / "_work"
    out_dir.mkdir(parents=True, exist_ok=True)

    scenes = select_scenes(windows, footage_dir, args.seconds)
    if not scenes:
        raise SystemExit(f"no scenes with stills under {footage_dir}")

    # Per-scene output-frame + hi-frame accounting (shared by all three modes).
    frames = [_scene_frames(s["duration"]) for s in scenes]
    hi_frames = [f * args.temporal for f in frames]
    denoms = [max(1, hf - 1) for hf in hi_frames]
    total_frames = sum(frames)
    H = sum(hi_frames)                 # run-global hi-frame count
    D = max(1, H - 1)                  # global denom
    h_starts = [sum(hi_frames[:k]) for k in range(len(scenes))]
    # Ramp as a fraction of the global [0,1] progress axis (clamped so the cruise
    # region stays non-empty on very short runs).
    cont_r = min(0.49, (CONT_RAMP_SECONDS * FPS * args.temporal) / D)

    # Self-checks BEFORE spending any render time.
    sanity_check_baseline(args.super_s)
    sanity_check_continuous(cont_r)

    ids = [s["id"] for s in scenes]
    print(f"project : {project}")
    print(f"out dir : {out_dir}")
    print(f"scenes  : {len(scenes)} (ids {ids})")
    print(f"length  : {total_frames} frames = {total_frames / FPS:.3f}s "
          f"(super x{args.super_s}, temporal x{args.temporal})")
    print("baseline sanity: PASS (generalized chain reproduces shipping "
          "center-zoom 1.0->1.08 LINEAR)\n")

    modes = ("baseline", "varied", "continuous")
    labels = {
        "baseline": "BASELINE (current)",
        "varied": "VARIED",
        "continuous": "CONTINUOUS",
    }
    results: list[tuple[str, Path, Path, float]] = []

    for mode in modes:
        t0 = time.perf_counter()
        work = work_root / mode
        work.mkdir(parents=True, exist_ok=True)
        scene_clips: list[Path] = []
        for i, scene in enumerate(scenes):
            png = footage_dir / f"scene_{scene['id']:03d}.png"
            if mode == "baseline":
                z, cx, cy = affine_exprs(BASELINE_MOVE, denoms[i], "linear")
            elif mode == "varied":
                move = VARIED_MOVES[i % len(VARIED_MOVES)]
                z, cx, cy = affine_exprs(move, denoms[i], "eased")
            else:  # continuous
                z, cx, cy = continuous_exprs(h_starts[i], D, cont_r)
            chain = kb_chain(z, cx, cy, args.super_s, args.temporal)
            clip = work / f"scene_{scene['id']:03d}.mp4"
            render_scene_clip(png, frames[i], chain, clip,
                              f"{mode} scene {scene['id']}")
            scene_clips.append(clip)

        out_clip = out_dir / f"{mode}.mp4"
        concat_and_label(scene_clips, labels[mode], out_clip, work)
        strip = out_dir / f"frames_{mode}.png"
        render_filmstrip(out_clip, strip, work)
        dur = probe_duration(out_clip)
        results.append((mode, out_clip, strip, dur))
        print(f"[{mode}] {out_clip}  ({dur:.3f}s, "
              f"{time.perf_counter() - t0:.1f}s to render)")
        print(f"         filmstrip: {strip}")

    # Tear down per-scene intermediates; keep the three clips + filmstrips.
    for mode in modes:
        work = work_root / mode
        for p in sorted(work.glob("*")):
            p.unlink(missing_ok=True)
        if work.exists():
            work.rmdir()
    if work_root.exists():
        work_root.rmdir()

    print(f"\nscenes used: {len(scenes)}  ids {ids}")
    print(f"temporal supersample: x{args.temporal}"
          + ("" if args.temporal > 1 else " (tblend/framestep skipped)"))
    print("no generation / API / paid calls -- ffmpeg on existing PNG stills only")


if __name__ == "__main__":
    main()
