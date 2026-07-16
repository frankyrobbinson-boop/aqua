#!/usr/bin/env python3
"""kenburns_subpixel.py -- SUBPIXEL Ken Burns via OpenCV warpAffine (NO supersample).

Why this exists
---------------
The prototype/shipping Ken Burns chain (``kenburns_compare.kb_chain``, mirrored
from ``assembly_service``) zooms by SUPERSAMPLING the still, doing a per-frame
``scale=eval=frame``, then an INTEGER ``crop`` to place the focal window. The crop
snaps the window's top-left to whole (supersampled) pixels EVERY frame, so a smooth
sub-pixel-per-frame move can only be rendered on an integer grid -> an irregular
"jump / hold" cadence = STUTTER. It's worst on a straight center zoom (the shipping
default); ``kenburns_stutter.py`` measured the same integer-grid jitter on slow
lateral pans. The fix tried before was MORE supersample (a finer grid) -- but that
is slow, and the user has ruled it out.

This tool takes the other road: resample the SOURCE at FRACTIONAL coordinates once
per output frame with an affine warp (``cv2.warpAffine``, INTER_LANCZOS4). The
focal window's top-left ``x0/y0`` and the scale ``s`` are FLOATS fed straight into
the transform matrix, so sampling is genuinely sub-pixel -- there is NO supersample
canvas anywhere in the subpixel path. One warp per output frame; the raw BGR frames
are piped to a single libx264 encode at a clean 25fps CFR.

Motion model (per output frame n in [0, N-1], N = round(scene_dur*FPS))
-----------------------------------------------------------------------
    p  = n/(N-1)                       (0 if N==1)
    pe = smoothstep(p) = p*p*(3-2*p)   -- eased moves; pe = p (linear) for a
                                          constant-velocity A/B interior
    Z  = z0 * (z1/z0)**pe              -- EXPONENTIAL zoom (constant perceptual rate)
    cx = cx0+(cx1-cx0)*pe ; cy = cy0+(cy1-cy0)*pe   -- normalized focal center
    base   = max(OUT_W/SW, OUT_H/SH)   -- fill 16:9 from the (square) source
    s      = base * Z
    win_w  = OUT_W/s ; win_h = OUT_H/s -- visible source window (px)
    x0     = cx*(SW-win_w) ; y0 = cy*(SH-win_h)     -- in-bounds for cx,cy in [0,1]
    M      = [[s,0,-x0*s],[0,s,-y0*s]]
    frame  = warpAffine(src, M, (OUT_W,OUT_H), INTER_LANCZOS4, BORDER_REFLECT_101)
``x0``/``s`` are floats -> the window corners land at fractional source coords ->
true sub-pixel sampling, no supersample.

What it renders (into --out-dir, default /tmp/kb/subpixel)
---------------------------------------------------------
  centerzoom_old.mp4  -- a slow center zoom 1.0->1.10 on ONE still (scene_002),
                         via the CURRENT integer-crop chain (kenburns_compare
                         kb_chain, SUPER=2). The stutter reference.
  centerzoom_new.mp4  -- the SAME still, same length, same zoom, via the SUBPIXEL
                         warp. Direct A/B (both constant-velocity so only the
                         sampling method differs).
  moves_new.mp4       -- a showcase across the first mosquito scenes (real
                         durations), each a different GENTLE move, all SUBPIXEL +
                         smoothstep + exponential zoom.
  placebo_test.mp4    -- a 2s libplacebo/Vulkan smoke test (future GPU path).

Then a phase-correlation per-frame-displacement read on OLD vs NEW (mean/std/cv).

No script/scene/TTS/image generation, no API, no paid calls: pure local ffmpeg +
OpenCV on PNG stills that already exist on disk.

    python backend/tools/kenburns_subpixel.py
    python backend/tools/kenburns_subpixel.py --seconds 40   # longer showcase
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

# --- Isolated third-party libs. opencv-python-headless + numpy were pip-installed
# with --target into /tmp/kb/pylibs (the same isolation the earlier numpy diag used)
# so this harness never touches either project venv's site-packages. -------------
PYLIBS = "/tmp/kb/pylibs"
if PYLIBS not in sys.path:
    sys.path.insert(0, PYLIBS)
import numpy as np  # noqa: E402
import cv2  # noqa: E402

# --- Reuse the committed motion/chain/render helpers for the OLD (integer-crop)
# reference plus the shared filmstrip / probe / scene-selection utilities. --------
sys.path.insert(0, str(Path(__file__).resolve().parent))
from kenburns_compare import (  # noqa: E402
    FPS,
    OUT_H,
    OUT_W,
    DEFAULT_PROJECT,
    affine_exprs,
    kb_chain,
    render_scene_clip,
    render_filmstrip,
    probe_duration,
    select_scenes,
    _drawtext_label,
)

# --- A/B (clips 1 & 2): same still, same length, same zoom AMOUNT; only the
# sampling method differs (integer crop vs subpixel warp). Constant velocity
# (linear pe) so per-frame displacement is steady -- the cleanest A/B. ------------
AB_STILL_ID = 2  # footage/scene_002.png
AB_SECONDS = 8.0
AB_ZOOM = (1.00, 1.10)
# OLD = "the current KB chain" as the task defines it: supersample -> per-frame
# scale=eval=frame -> INTEGER crop (kb_chain at SUPER=2, no temporal blur, so the
# integer-crop stutter is neither masked by tblend nor confounded in the metric --
# and it matches the subpixel path's one-sample-per-output-frame).
OLD_SUPER = 2
OLD_TEMPORAL = 1

# --- Showcase (clip 3): (name, easing, (z0,z1,cx0,cy0,cx1,cy1)). Gentle, restrained
# magnitudes to match the reference footage's slow feel. All rendered SUBPIXEL. ---
SHOWCASE_MOVES: list[tuple[str, str, tuple[float, float, float, float, float, float]]] = [
    ("center zoom-in", "smoothstep", (1.00, 1.10, 0.50, 0.50, 0.50, 0.50)),
    ("center zoom-out", "smoothstep", (1.10, 1.00, 0.50, 0.50, 0.50, 0.50)),
    ("pan right", "smoothstep", (1.06, 1.06, 0.32, 0.50, 0.68, 0.50)),
    ("zoom-in drift down-right", "smoothstep", (1.00, 1.10, 0.44, 0.44, 0.58, 0.58)),
    ("pan up", "smoothstep", (1.06, 1.06, 0.50, 0.62, 0.50, 0.38)),
]


# --- Motion model --------------------------------------------------------------
def _smoothstep(p: float) -> float:
    return p * p * (3.0 - 2.0 * p)


def _pe(p: float, easing: str) -> float:
    """Eased progress. 'smoothstep' for restrained moves; 'linear' (pe=p) for the
    constant-velocity A/B interior so per-frame displacement stays steady."""
    return _smoothstep(p) if easing == "smoothstep" else p


def _warp_matrix(
    src_w: int, src_h: int,
    move: tuple[float, float, float, float, float, float], p: float, easing: str,
) -> np.ndarray:
    """The 2x3 affine that maps the eased focal source window onto the full
    OUT_W x OUT_H frame at progress p. Scale s and offsets x0/y0 are floats ->
    warpAffine samples the source at fractional coords (subpixel, no supersample)."""
    z0, z1, cx0, cy0, cx1, cy1 = move
    pe = _pe(p, easing)
    Z = z0 * (z1 / z0) ** pe  # exponential zoom
    cx = cx0 + (cx1 - cx0) * pe
    cy = cy0 + (cy1 - cy0) * pe
    base = max(OUT_W / src_w, OUT_H / src_h)  # fill 16:9 from the source
    s = base * Z
    win_w = OUT_W / s
    win_h = OUT_H / s
    x0 = cx * (src_w - win_w)  # in-bounds for cx,cy in [0,1]
    y0 = cy * (src_h - win_h)
    return np.array([[s, 0.0, -x0 * s], [0.0, s, -y0 * s]], dtype=np.float64)


def _put_label(frame: np.ndarray, text: str) -> None:
    """Burn a small top-left label in a translucent black box (cv2.putText),
    matching the drawtext label the sibling ffmpeg tools use."""
    font, scale, thick, pad = cv2.FONT_HERSHEY_SIMPLEX, 1.05, 2, 14
    (tw, th), _ = cv2.getTextSize(text, font, scale, thick)
    x1, y1 = 24, 24
    x2, y2 = x1 + tw + 2 * pad, y1 + th + 2 * pad
    roi = frame[y1:y2, x1:x2].astype(np.float32) * 0.45  # translucent (55%) black
    frame[y1:y2, x1:x2] = roi.astype(np.uint8)
    cv2.putText(frame, text, (x1 + pad, y1 + pad + th), font, scale,
                (255, 255, 255), thick, cv2.LINE_AA)


# --- Encoding ------------------------------------------------------------------
def _open_encoder(out_path: Path) -> subprocess.Popen:
    """A libx264 CFR-25 encoder reading raw bgr24 frames from stdin. bgr24 matches
    OpenCV's native channel order, so no color swap is needed on the way in."""
    return subprocess.Popen(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "rawvideo", "-pixel_format", "bgr24",
            "-video_size", f"{OUT_W}x{OUT_H}", "-framerate", str(FPS),
            "-i", "-",
            "-an", "-r", str(FPS),
            "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p",
            str(out_path),
        ],
        stdin=subprocess.PIPE, stderr=subprocess.PIPE,
    )


def render_subpixel_clip(
    png: Path, seconds: float,
    move: tuple[float, float, float, float, float, float], easing: str,
    label: str, out_path: Path,
) -> int:
    """Render one still to a silent OUT_W x OUT_H subpixel clip. Warp each of the
    N = round(seconds*FPS) output frames, burn the label, stream to libx264.
    Returns N."""
    src = cv2.imread(str(png), cv2.IMREAD_COLOR)
    if src is None:
        raise RuntimeError(f"could not read still: {png}")
    src_h, src_w = src.shape[:2]
    N = max(1, round(seconds * FPS))
    denom = N - 1 if N > 1 else 1
    proc = _open_encoder(out_path)
    assert proc.stdin is not None
    try:
        for n in range(N):
            p = (n / denom) if N > 1 else 0.0
            M = _warp_matrix(src_w, src_h, move, p, easing)
            frame = cv2.warpAffine(
                src, M, (OUT_W, OUT_H),
                flags=cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_REFLECT_101,
            )
            if label:
                _put_label(frame, label)
            proc.stdin.write(np.ascontiguousarray(frame).tobytes())
    finally:
        proc.stdin.close()
    err = proc.stderr.read().decode("utf-8", "replace") if proc.stderr else ""
    if proc.wait() != 0:
        raise RuntimeError(f"ffmpeg encode failed ({out_path.name}):\n{err}")
    return N


def render_old_clip(png: Path, out_path: Path) -> int:
    """Clip 1: the CURRENT integer-crop chain -- supersample -> per-frame
    scale=eval=frame -> INTEGER crop (kb_chain, SUPER=2, no temporal blur), a slow
    LINEAR center zoom over AB_ZOOM. The stutter reference for the A/B. Returns the
    output frame count."""
    frames = max(1, round(AB_SECONDS * FPS))
    denom = max(1, frames * OLD_TEMPORAL - 1)
    move = (AB_ZOOM[0], AB_ZOOM[1], 0.5, 0.5, 0.5, 0.5)
    z, cx, cy = affine_exprs(move, denom, "linear")
    chain = kb_chain(z, cx, cy, OLD_SUPER, OLD_TEMPORAL) + "," + _drawtext_label(
        "OLD (integer crop)"
    )
    render_scene_clip(png, frames, chain, out_path, "old integer-crop A/B")
    return frames


def _concat_copy(clips: list[Path], out_path: Path, work_dir: Path) -> None:
    """Stitch the per-scene showcase clips with the concat demuxer, no re-encode
    (they share codec/params -- each is the same libx264 CFR-25 encode)."""
    lst = work_dir / "concat.txt"
    lst.write_text("".join(f"file '{c}'\n" for c in clips))
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
         "-i", str(lst), "-c", "copy", str(out_path)],
        check=True, capture_output=True,
    )


# --- Quantify: phase-correlation per-frame displacement ------------------------
def _decode_gray(clip_path: Path, w: int = 960, h: int = 540) -> np.ndarray:
    """Decode a clip to an (n, h, w) float32 grayscale stack via ffmpeg (avoids
    any dependency on cv2's video backend). Downscaled for speed + gross-motion."""
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(clip_path),
         "-vf", f"scale={w}:{h}", "-pix_fmt", "gray", "-f", "rawvideo", "-"],
        check=True, capture_output=True,
    )
    buf = np.frombuffer(proc.stdout, dtype=np.uint8)
    n = buf.size // (w * h)
    return buf[: n * w * h].reshape(n, h, w).astype(np.float32)


def phasecorr_stats(clip_path: Path) -> tuple[float, float, float, int]:
    """Per-frame content displacement between consecutive frames via
    ``cv2.phaseCorrelate`` (Hanning-windowed). Returns (cv, mean_px, std_px,
    n_pairs) where cv = std/mean -- the metric kenburns_stutter used on pans.

    NB: phaseCorrelate measures global TRANSLATION. On a straight center zoom the
    intended translation is ~0, so the MEAN displacement (the residual per-frame
    jitter) is the number that separates smooth-vs-stutter; cv=std/mean is well-
    behaved for pans (steady translation signal) but degenerate here (~0 signal)."""
    frames = _decode_gray(clip_path)
    if len(frames) < 2:
        return float("nan"), 0.0, 0.0, 0
    h, w = frames[0].shape
    win = cv2.createHanningWindow((w, h), cv2.CV_32F)
    disp = []
    for a, b in zip(frames[:-1], frames[1:]):
        (dx, dy), _ = cv2.phaseCorrelate(
            np.ascontiguousarray(a), np.ascontiguousarray(b), win
        )
        disp.append((dx * dx + dy * dy) ** 0.5)
    d = np.asarray(disp, dtype=np.float64)
    mean, std = float(d.mean()), float(d.std())
    cv = std / mean if mean > 1e-9 else float("nan")
    return cv, mean, std, len(d)


# --- libplacebo / Vulkan smoke test (future GPU-accelerated pure-ffmpeg path) ---
def placebo_smoke(png: Path, out_path: Path) -> tuple[int, str]:
    """Try a 2s GPU zoom via libplacebo on a Vulkan device. Returns (rc, stderr).
    Never raises -- this is an informational probe, not part of the deliverable."""
    cmd = [
        "ffmpeg", "-y", "-v", "warning",
        "-init_hw_device", "vulkan",
        "-loop", "1", "-framerate", "25", "-t", "2", "-i", str(png),
        "-vf",
        (
            "libplacebo=w=1920:h=1080:"
            "crop_w='iw/(1.0+0.10*(t/2))':crop_h='ih/(1.0+0.10*(t/2))':"
            "crop_x='(iw-cw)/2':crop_y='(ih-ch)/2'"
        ),
        "-frames:v", "50", str(out_path),
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True)
        return r.returncode, (r.stderr or "").strip()
    except Exception as e:  # noqa: BLE001 -- probe must never break the run
        return -1, str(e)


# --- Self-check ----------------------------------------------------------------
def _sanity_subpixel() -> None:
    """Prove the subpixel geometry: for cx,cy in [0,1] the source window stays in
    bounds, and the window's corners map exactly onto (0,0)..(OUT_W,OUT_H)."""
    SW = SH = 1024
    cases = [
        ((1.00, 1.10, 0.5, 0.5, 0.5, 0.5), "linear"),
        ((1.06, 1.06, 0.32, 0.5, 0.68, 0.5), "smoothstep"),
        ((1.00, 1.10, 0.44, 0.44, 0.58, 0.58), "smoothstep"),
    ]
    for move, easing in cases:
        for p in (0.0, 0.37, 1.0):
            M = _warp_matrix(SW, SH, move, p, easing)
            s = M[0, 0]
            win_w, win_h = OUT_W / s, OUT_H / s
            x0, y0 = -M[0, 2] / s, -M[1, 2] / s
            assert -1e-6 <= x0 <= SW - win_w + 1e-6, (move, p, x0)
            assert -1e-6 <= y0 <= SH - win_h + 1e-6, (move, p, y0)
            tl = M @ np.array([x0, y0, 1.0])
            br = M @ np.array([x0 + win_w, y0 + win_h, 1.0])
            assert abs(tl[0]) < 1e-6 and abs(tl[1]) < 1e-6, (move, p, tl)
            assert abs(br[0] - OUT_W) < 1e-6 and abs(br[1] - OUT_H) < 1e-6, (move, p, br)


# --- Main ----------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project", default=str(DEFAULT_PROJECT))
    ap.add_argument("--out-dir", default="/tmp/kb/subpixel")
    ap.add_argument("--seconds", type=float, default=30.0,
                    help="accumulate scenes until ~this many seconds for the showcase")
    args = ap.parse_args()

    project = Path(args.project).expanduser()
    footage_dir = project / "footage"
    windows = json.loads((project / "scene_windows.json").read_text())
    out_dir = Path(args.out_dir)
    work = out_dir / "_work"
    out_dir.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)

    _sanity_subpixel()

    ab_png = footage_dir / f"scene_{AB_STILL_ID:03d}.png"
    if not ab_png.exists():
        raise SystemExit(f"missing A/B still: {ab_png}")

    print(f"project : {project}")
    print(f"out dir : {out_dir}")
    print("subpixel sanity: PASS (window in-bounds; corners map to full frame)\n")

    timings: list[tuple[str, Path, float]] = []

    # --- Clip 1: OLD (current integer-crop chain) --------------------------------
    old_clip = out_dir / "centerzoom_old.mp4"
    t0 = time.perf_counter()
    n_old = render_old_clip(ab_png, old_clip)
    dt_old = time.perf_counter() - t0
    timings.append(("centerzoom_old", old_clip, dt_old))
    print(f"[old] {old_clip}  ({n_old} frames, {dt_old:.1f}s render) "
          f"-- integer crop, SUPER={OLD_SUPER}, temporal={OLD_TEMPORAL}")

    # --- Clip 2: NEW (subpixel warp), same still/length/zoom, constant velocity --
    new_clip = out_dir / "centerzoom_new.mp4"
    t0 = time.perf_counter()
    n_new = render_subpixel_clip(
        ab_png, AB_SECONDS, (AB_ZOOM[0], AB_ZOOM[1], 0.5, 0.5, 0.5, 0.5),
        "linear", "NEW (subpixel)", new_clip,
    )
    dt_new = time.perf_counter() - t0
    timings.append(("centerzoom_new", new_clip, dt_new))
    print(f"[new] {new_clip}  ({n_new} frames, {dt_new:.1f}s render) "
          f"-- subpixel warp, no supersample")

    # --- Clip 3: showcase of gentle subpixel moves across the first scenes -------
    scenes = select_scenes(windows, footage_dir, args.seconds)
    if not scenes:
        raise SystemExit(f"no scenes with stills under {footage_dir}")
    moves_clip = out_dir / "moves_new.mp4"
    t0 = time.perf_counter()
    scene_clips: list[Path] = []
    used: list[str] = []
    for i, scene in enumerate(scenes):
        png = footage_dir / f"scene_{scene['id']:03d}.png"
        name, easing, move = SHOWCASE_MOVES[i % len(SHOWCASE_MOVES)]
        clip = work / f"moves_{i:02d}.mp4"
        render_subpixel_clip(png, scene["duration"], move, easing,
                             f"subpixel -- {name}", clip)
        scene_clips.append(clip)
        used.append(f"scene {scene['id']} ({scene['duration']:.1f}s) {name}")
    _concat_copy(scene_clips, moves_clip, work)
    dt_moves = time.perf_counter() - t0
    timings.append(("moves_new", moves_clip, dt_moves))
    moves_dur = probe_duration(moves_clip)
    print(f"[moves] {moves_clip}  ({moves_dur:.1f}s, {dt_moves:.1f}s render) "
          f"-- {len(scenes)} scenes, subpixel + smoothstep + exp zoom")
    for u in used:
        print(f"          {u}")

    # --- Filmstrips (for the at-a-glance read; motion needs the mp4) -------------
    strips: list[Path] = []
    for clip in (old_clip, new_clip, moves_clip):
        strip = out_dir / f"frames_{clip.stem}.png"
        render_filmstrip(clip, strip, work)
        strips.append(strip)

    # --- Quantify OLD vs NEW smoothness ------------------------------------------
    cv_old, m_old, s_old, np_old = phasecorr_stats(old_clip)
    cv_new, m_new, s_new, np_new = phasecorr_stats(new_clip)

    # --- libplacebo / Vulkan smoke test ------------------------------------------
    placebo_clip = out_dir / "placebo_test.mp4"
    rc, placebo_err = placebo_smoke(ab_png, placebo_clip)
    placebo_ok = rc == 0 and placebo_clip.exists()

    # --- Clean up per-scene intermediates ----------------------------------------
    for p in sorted(work.glob("*")):
        p.unlink(missing_ok=True)
    if work.exists():
        work.rmdir()

    # --- Report ------------------------------------------------------------------
    print("\n=== clips ===")
    for name, path, dt in timings:
        print(f"  {name:14s} {path}  ({dt:.1f}s render)")
    for strip in strips:
        print(f"  filmstrip      {strip}")
    print(f"  placebo_test   {placebo_clip}"
          + ("" if placebo_ok else "  (NOT written -- see below)"))

    print("\n=== phase-correlation per-frame displacement (OLD vs NEW) ===")
    print(f"  OLD (integer crop): mean={m_old:.4f}px  std={s_old:.4f}px  "
          f"cv={cv_old:.3f}  ({np_old} pairs)")
    print(f"  NEW (subpixel)    : mean={m_new:.4f}px  std={s_new:.4f}px  "
          f"cv={cv_new:.3f}  ({np_new} pairs)")
    if m_new > 0:
        print(f"  mean per-frame jitter reduced {m_old / m_new:.1f}x "
              f"({m_old:.4f} -> {m_new:.4f} px)")
    print("  note: phaseCorrelate measures TRANSLATION; on a pure center zoom the "
          "mean\n  displacement (residual jitter) is the discriminating number -- "
          "cv=std/mean is\n  the pan metric and is degenerate when the translation "
          "signal is ~0.")

    print("\n=== libplacebo / Vulkan smoke test ===")
    if placebo_ok:
        print(f"  OK -- Vulkan initialized and libplacebo rendered {placebo_clip}")
    else:
        print(f"  FAILED (rc={rc}) -- Vulkan/libplacebo not usable here. stderr:")
        for line in (placebo_err or "(no stderr)").splitlines()[-12:]:
            print(f"    {line}")

    print("\nsubpixel path: warpAffine on the native 1024px source straight to "
          "1920x1080 -- NO supersample canvas.")
    print("no generation / API / paid calls -- ffmpeg + OpenCV on existing PNG "
          "stills only")


if __name__ == "__main__":
    main()
