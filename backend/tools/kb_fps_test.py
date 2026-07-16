#!/usr/bin/env python3
"""kb_fps_test.py -- framerate A/B/C for the continuous Ken Burns zoom.

THROWAWAY comparison harness (render-polish Part 2): render the SAME ~8-second
continuous subpixel Ken Burns zoom (z 1.00 -> 1.12, centre, linear) on ONE real
still at 25, 50, and 60 fps, so the maintainer can eyeball whether a higher
framerate smooths the motion's judder BEFORE the pipeline FPS is committed.

This does NOT touch the pipeline. The module FPS constant
(assembly_service.FPS = 25) is left ALONE; each clip sets its own framerate on the
rawvideo pipe (-framerate) and on the encode (-r). The warp itself is the SHIPPING
subpixel path -- this imports assembly_service._kb_warp_matrix (+ OUT_W/OUT_H)
VERBATIM, so the ONLY variable across the three clips is the sample rate (frame
count) and the output framerate; the zoom start/end, duration, and easing are
identical.

No script/scene/TTS/image generation, no API, no paid calls: ffmpeg + OpenCV on a
PNG still already on disk.

    python backend/tools/kb_fps_test.py
    python backend/tools/kb_fps_test.py --still <path> --seconds 8 --out-dir /tmp/fps_test
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

# Import the SHIPPING subpixel warp so the comparison uses the exact production
# math -- only the framerate differs across clips. Add backend/ (this file's
# grandparent) to the path so the `services` package resolves regardless of cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from services.assembly_service import OUT_H, OUT_W, _kb_warp_matrix  # noqa: E402

import cv2  # noqa: E402
import numpy as np  # noqa: E402

# The continuous zoom under test: a slow centre push 1.00 -> 1.12 (matching the KB
# camera's amplitude), constant velocity (linear) so per-frame displacement is
# steady and only the SAMPLE RATE varies across the three clips.
MOVE = (1.00, 1.12, 0.50, 0.50, 0.50, 0.50)
EASING = "linear"
FPS_LADDER = (25, 50, 60)
DEFAULT_STILL = (
    Path(__file__).resolve().parent.parent.parent
    / "projects"
    / "6-vegetables-you-plant-once-and-harvest-for-20-years"
    / "footage"
    / "scene_054.png"
)


def render_fps_clip(
    src: np.ndarray, src_w: int, src_h: int, seconds: float, fps: int, out_path: Path
) -> int:
    """Render the MOVE zoom on the pre-read still at exactly ``fps`` fps over
    ``seconds`` seconds (N = round(seconds*fps) frames), warping each frame with
    the shipping _kb_warp_matrix and streaming raw bgr24 to a libx264 encode at
    the SAME fps. Returns N. bgr24 matches OpenCV's channel order (no swap)."""
    N = max(2, round(seconds * fps))
    denom = N - 1
    proc = subprocess.Popen(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "rawvideo", "-pixel_format", "bgr24",
            "-video_size", f"{OUT_W}x{OUT_H}", "-framerate", str(fps),
            "-i", "-",
            "-an", "-r", str(fps),
            "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p",
            str(out_path),
        ],
        stdin=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    assert proc.stdin is not None
    try:
        for n in range(N):
            p = n / denom
            M = _kb_warp_matrix(src_w, src_h, MOVE, p, EASING)
            frame = cv2.warpAffine(
                src, M, (OUT_W, OUT_H),
                flags=cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_REFLECT_101,
            )
            proc.stdin.write(np.ascontiguousarray(frame).tobytes())
    finally:
        proc.stdin.close()
    err = proc.stderr.read().decode("utf-8", "replace") if proc.stderr else ""
    if proc.wait() != 0:
        raise RuntimeError(f"ffmpeg encode failed ({out_path.name}):\n{err}")
    return N


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--still", default=str(DEFAULT_STILL))
    ap.add_argument("--seconds", type=float, default=8.0)
    ap.add_argument("--out-dir", default="/tmp/fps_test")
    args = ap.parse_args()

    still = Path(args.still).expanduser()
    if not still.exists():
        raise SystemExit(f"still not found: {still}")
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    src = cv2.imread(str(still), cv2.IMREAD_COLOR)
    if src is None:
        raise SystemExit(f"could not read still: {still}")
    src_h, src_w = src.shape[:2]

    print(f"still   : {still}  ({src_w}x{src_h})")
    print(f"zoom    : {MOVE[0]:.2f} -> {MOVE[1]:.2f}, {EASING}, {args.seconds:.1f}s")
    print(f"out dir : {out_dir}\n")

    for fps in FPS_LADDER:
        out_path = out_dir / f"kb_zoom_{fps}fps.mp4"
        n = render_fps_clip(src, src_w, src_h, args.seconds, fps, out_path)
        print(f"  {fps:>2d} fps -> {out_path}  ({n} frames)")

    print("\nsame continuous zoom, three sample rates -- compare judder side by side.")
    print("pipeline FPS constant UNCHANGED (throwaway comparison).")


if __name__ == "__main__":
    main()
