#!/usr/bin/env python3
"""kenburns_stutter.py -- diagnose+fix the Ken Burns pan STUTTER (PNG stills only).

Companion to kenburns_compare.py. That tool's VARIED clip stutters worst on the
LATERAL pans. Measured root cause (phase-correlation on varied.mp4's pan-right
scene): at SUPER=2 the per-frame focal crop x is rounded to an INTEGER
SUPERSAMPLED pixel = a 0.5 OUTPUT-px grid, so a smooth ~1.19 px/frame pan can only
be rendered as an alternating 1.0 / 1.5 px cadence -- quantization JITTER, not
missing motion blur. The shipping 2-frame tblend (temporal=2) barely dithers it.

This harness re-renders ONLY the pan-right scene (scene id 2, the exact eased move
from kenburns_compare.VARIED_MOVES[2]) under a set of labeled fixes, apples-to-
apples, and records render time per clip (the cost axis). Two levers:
  * SUPER  -- finer supersample => finer crop grid => less quantization.
  * K-frame BOX MOTION BLUR -- average K sub-frames per output frame, a proper
    generalization of the weak shipping 2-frame tblend.

K-frame box motion blur (generalizes kb_chain's temporal stage)
---------------------------------------------------------------
Render the per-frame zoom/crop chain at K*FPS, then ``tmix=frames=K`` (equal
weights) to mean each window of K sub-frames, then ``framestep=K`` to keep
NON-OVERLAPPING windows, landing back at FPS. Each output frame is thus the mean
of its OWN K sub-frames -- vs tblend, which only averages ADJACENT pairs. With K
distinct sub-frame crop positions per output frame, the residual crop
quantization is dithered across K steps -> smoother cadence.

Variants (all on the same scene/move; render time is the cost we're trading):
  A  SUPER=2  TEMPORAL=2   (current -- the reference; == varied.mp4's pan scene)
  B  SUPER=4  TEMPORAL=2
  C  SUPER=4  K=8  box motion blur
  D  SUPER=8  K=12 box motion blur   (the "max"; --variants to skip if too slow)
  E  SUPER=4  TEMPORAL=2  HALF pan magnitude (does slowing the move alone fix it?)

Imports the shared motion model / chain / render helpers from kenburns_compare so
the reference variant A reproduces that tool's pan scene exactly. No generation /
API / paid calls: pure local ffmpeg on one existing PNG still.

    python backend/tools/kenburns_stutter.py                 # all variants
    python backend/tools/kenburns_stutter.py --variants A,B,C,E   # skip the slow D
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kenburns_compare import (  # noqa: E402  (shared harness pieces)
    FPS,
    OUT_H,
    OUT_W,
    DEFAULT_PROJECT,
    VARIED_MOVES,
    affine_exprs,
    kb_chain,
    render_scene_clip,
    render_filmstrip,
    probe_duration,
    _drawtext_label,
    _scene_frames,
)

PAN_ID = 2  # scene id whose eased move is the pan-right (VARIED_MOVES[2])
PAN_MOVE = VARIED_MOVES[2]  # (1.15,1.15, 0.20,0.50, 0.80,0.50) -- eased pan right
# HALF pan: same 0.50 center, half the amplitude (0.30 -> 0.15 each side).
_cx0, _cx1 = PAN_MOVE[2], PAN_MOVE[4]
_cxm = 0.5 * (_cx0 + _cx1)
HALF_MOVE = (
    PAN_MOVE[0], PAN_MOVE[1],
    _cxm + 0.5 * (_cx0 - _cxm), PAN_MOVE[3],
    _cxm + 0.5 * (_cx1 - _cxm), PAN_MOVE[5],
)


def kb_chain_mblur(
    z_expr: str, cx_expr: str, cy_expr: str, super_s: int, K: int
) -> str:
    """kb_chain's temporal stage generalized to K-frame BOX motion blur.

    Identical spatial pipeline to kb_chain (supersample -> per-frame subpixel zoom
    -> integer focal crop), but the hi-rate is K*FPS and the temporal collapse is
    ``tmix=frames=K`` (equal weights, the tmix default) followed by ``framestep=K``
    so each kept frame is the mean of its own K NON-OVERLAPPING sub-frames. The
    move expressions must be built with denom = K*frames - 1 so the eased move
    spans the full hi-frame set. Downscale stays LAST (as in kb_chain) to keep the
    fine crop grid intact through the blend -- apples-to-apples with A/B."""
    sw, sh = OUT_W * super_s, OUT_H * super_s
    fps_hi = FPS * K
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
        f"tmix=frames={K}",
        f"framestep={K}",
        f"scale={OUT_W}:{OUT_H}:flags=lanczos",
    ]
    return ",".join(parts)


def build_chain(variant: str, frames: int) -> tuple[str, str]:
    """(label, filterchain incl. burned-in settings label) for a variant."""
    if variant == "A":
        denom = max(1, frames * 2 - 1)
        z, cx, cy = affine_exprs(PAN_MOVE, denom, "eased")
        chain = kb_chain(z, cx, cy, super_s=2, temporal=2)
        label = "A  SUPER=2  TEMPORAL=2  (current)"
    elif variant == "B":
        denom = max(1, frames * 2 - 1)
        z, cx, cy = affine_exprs(PAN_MOVE, denom, "eased")
        chain = kb_chain(z, cx, cy, super_s=4, temporal=2)
        label = "B  SUPER=4  TEMPORAL=2"
    elif variant == "C":
        K = 8
        denom = max(1, frames * K - 1)
        z, cx, cy = affine_exprs(PAN_MOVE, denom, "eased")
        chain = kb_chain_mblur(z, cx, cy, super_s=4, K=K)
        label = "C  SUPER=4  K=8 box blur"
    elif variant == "D":
        K = 12
        denom = max(1, frames * K - 1)
        z, cx, cy = affine_exprs(PAN_MOVE, denom, "eased")
        chain = kb_chain_mblur(z, cx, cy, super_s=8, K=K)
        label = "D  SUPER=8  K=12 box blur"
    elif variant == "E":
        denom = max(1, frames * 2 - 1)
        z, cx, cy = affine_exprs(HALF_MOVE, denom, "eased")
        chain = kb_chain(z, cx, cy, super_s=4, temporal=2)
        label = "E  SUPER=4  TEMPORAL=2  HALF pan"
    else:
        raise SystemExit(f"unknown variant {variant!r}")
    return label, chain + "," + _drawtext_label(label)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project", default=str(DEFAULT_PROJECT))
    ap.add_argument("--out-dir", default="/tmp/kb/stutter")
    ap.add_argument("--variants", default="A,B,C,D,E",
                    help="comma list of A,B,C,D,E to render")
    args = ap.parse_args()

    project = Path(args.project).expanduser()
    png = project / "footage" / f"scene_{PAN_ID:03d}.png"
    if not png.exists():
        raise SystemExit(f"missing still: {png}")
    windows = json.loads((project / "scene_windows.json").read_text())
    scene = next(s for s in windows if s["id"] == PAN_ID)
    frames = _scene_frames(scene["duration"])

    out_dir = Path(args.out_dir)
    work = out_dir / "_work"
    out_dir.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)

    wanted = [v.strip().upper() for v in args.variants.split(",") if v.strip()]
    print(f"project : {project}")
    print(f"still   : {png}")
    print(f"scene   : id {PAN_ID}, {scene['duration']:.3f}s = {frames} frames "
          f"@ {FPS}fps  (eased pan-right {PAN_MOVE})")
    print(f"out dir : {out_dir}")
    print(f"variants: {wanted}\n")

    for v in wanted:
        label, chain = build_chain(v, frames)
        clip = out_dir / f"{v}.mp4"
        t0 = time.perf_counter()
        render_scene_clip(png, frames, chain, clip, f"stutter {v}")
        dt = time.perf_counter() - t0
        strip = out_dir / f"frames_{v}.png"
        render_filmstrip(clip, strip, work)
        dur = probe_duration(clip)
        print(f"[{v}] {label}")
        print(f"    clip : {clip}  ({dur:.3f}s, {frames} frames)")
        print(f"    strip: {strip}")
        print(f"    render time: {dt:.1f}s\n")

    for p in sorted(work.glob("*")):
        p.unlink(missing_ok=True)
    if work.exists():
        work.rmdir()
    print("no generation / API / paid calls -- ffmpeg on one existing PNG still")


if __name__ == "__main__":
    main()
