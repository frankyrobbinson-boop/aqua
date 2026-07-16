#!/usr/bin/env python3
"""kb_fps_test2.py -- framerate A/B/C for the continuous Ken Burns camera, exercising
the moments that actually read as choppy: zoom REVERSALS (the ping-pong turning
around) and CROSSFADES -- not just the one-way push kb_fps_test.py rendered.

THROWAWAY comparison harness (render-polish). Renders ONE combined clip per framerate
(25 / 50 / 60 fps) -- reversal -> crossfade -> reversal -- so the maintainer can
A/B/C smoothness at the SAME nominal duration, only the sample rate (frame count)
differing.

What it drives:
  * REVERSAL -- the SHIPPING continuous camera (services.kb_camera.compute_run) at the
    LOCKED feel (assembly_service.KB_CAMERA_* -- period 8s, amplitude 0.12, smoothstep
    reversals eased 0.10, ~1s envelope), over ONE long still so the ping-pong clearly
    reverses direction on screen (a peak at the 8s period, then back out). Rendered via
    the shipping subpixel warp path (assembly_service._kb_warp_matrix + cv2.warpAffine,
    pivoting on a centre anchor exactly like _render_kenburns_png's default PIVOT
    branch).
  * CROSSFADE -- a seam between TWO KB-moving stills that belong to ONE continuous
    camera run, defocus-dissolved on the pipeline's OWN blur-dissolve mechanic
    (extend-and-overlap + a per-side ramped Gaussian defocus + an eased cross-dissolve,
    the same inOutQuint curve concat_clips_crossfade uses). The camera motion continues
    THROUGH the seam: each flanking clip is extended past its natural window with
    SceneCameraTrack.zs_for's velocity extrapolation (the freeze-fix), so the incoming
    side glides instead of velocity-freezing on a pad-hold.

Everything is defined in SECONDS and the frame count is derived per-fps, so all three
clips are the SAME duration and only the sample rate differs -- the whole point of the
A/B/C. The pipeline FPS constant (assembly_service.FPS = 25) is NOT touched: each clip
sets its own -framerate / -r and passes its fps to compute_run + the blur sendcmd.

No script/scene/TTS/image generation, no API, no paid calls: ffmpeg + OpenCV on PNG
stills already on disk.

    python3 backend/tools/kb_fps_test2.py
    python3 backend/tools/kb_fps_test2.py --out-dir /tmp/kb_fps_test2
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

# Add backend/ (this file's grandparent) to the path so `services` resolves
# regardless of cwd, then import the SHIPPING camera + warp + blur-dissolve pieces so
# the comparison uses the exact production math -- only the framerate differs.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from services import kb_camera  # noqa: E402
from services.assembly_service import (  # noqa: E402
    BLUR_DISSOLVE_MAX_BLUR,
    KB_CAMERA_AMPLITUDE,
    KB_CAMERA_EASE_FRAC,
    KB_CAMERA_EASE_SECONDS,
    KB_CAMERA_INTERP,
    KB_CAMERA_PERIOD_S,
    OUT_H,
    OUT_W,
    SceneCameraTrack,
    _blur_dissolve_inoutquint,
    _kb_warp_matrix,
)

import cv2  # noqa: E402
import numpy as np  # noqa: E402

FPS_LADDER = (25, 50, 60)

# Reversal-segment length: > the 8s reversal period so the ping-pong clearly turns
# around on screen (zoom in to the peak at 8s, then back out for the remainder).
REVERSAL_SECONDS = 13.0

# Crossfade segment: two stills of this length each, in ONE continuous run, so the
# seam falls mid-zoom (the camera is visibly moving through it).
XFADE_SCENE_SECONDS = 5.0

# Defocus-dissolve total overlap, in SECONDS, so the transition is the SAME ~0.8s
# window at every fps (the pipeline uses BLUR_DISSOLVE_FRAMES=10 => 2*10/25 = 0.8s
# @25fps). The per-fps half-overlap frame count is round(this/2 * fps).
XFADE_OVERLAP_SECONDS = 0.8

FOOTAGE = (
    Path(__file__).resolve().parent.parent.parent
    / "projects"
    / "6-vegetables-you-plant-once-and-harvest-for-20-years"
    / "footage"
)
STILL_REV1 = FOOTAGE / "scene_054.png"  # sunflowers -- fine foliage/fence detail
STILL_XA = FOOTAGE / "scene_030.png"    # rhubarb crown close-up -- dense texture
STILL_XB = FOOTAGE / "scene_072.png"    # patio + raised bed -- hard paving edges
STILL_REV2 = STILL_XB                   # reuse the hard-edged patio for reversal 2
CENTER = (0.5, 0.5)

# xfade custom-transition expression: P runs 1->0 across the transition; ease (1-P)
# via inOutQuint into a 0->1 progress PE and blend A*(1-PE)+B*PE -- the SAME curve the
# per-side defocus ramp uses, so the softest, most-blended instant lands on the seam.
# Copied VERBATIM from assembly_service.concat_clips_crossfade's blur_expr.
_BLUR_EXPR = (
    "st(1, 1-P); "
    "st(0, if(lt(ld(1),0.5), 16*pow(ld(1),5), 1-pow(-2*ld(1)+2,5)/2)); "
    "A*(1-ld(0))+B*ld(0)"
)


def _read_still(path: Path) -> np.ndarray:
    src = cv2.imread(str(path), cv2.IMREAD_COLOR)  # BGR (piped as bgr24, no swap)
    if src is None:
        raise SystemExit(f"could not read still: {path}")
    return src


def _open_encoder(out_path: Path, fps: int) -> subprocess.Popen:
    """A libx264 CFR encoder at ``fps`` reading raw bgr24 frames from stdin. bgr24
    matches OpenCV's native channel order, so no colour swap is needed on the way in.
    The ONLY per-clip variable is this fps (the pipeline FPS constant is untouched)."""
    return subprocess.Popen(
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


def _warp_zoom_clip(src: np.ndarray, zs: list[float], out_path: Path, fps: int) -> int:
    """Warp ``src`` to a silent OUT_W x OUT_H clip at ``fps`` -- one output frame per
    entry in ``zs``, PIVOTING on the centre anchor (exactly _render_kenburns_png's
    default PIVOT branch: M = _kb_warp_matrix((z,z,0.5,0.5,0.5,0.5), 0.0, "linear")).
    Returns the frame count written (== len(zs))."""
    src_h, src_w = src.shape[:2]
    cx, cy = CENTER
    proc = _open_encoder(out_path, fps)
    assert proc.stdin is not None
    try:
        for z in zs:
            M = _kb_warp_matrix(src_w, src_h, (z, z, cx, cy, cx, cy), 0.0, "linear")
            frame = cv2.warpAffine(
                src, M, (OUT_W, OUT_H),
                flags=cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_REFLECT_101,
            )
            proc.stdin.write(np.ascontiguousarray(frame).tobytes())
    except BrokenPipeError:
        pass  # ffmpeg exited early; its stderr (read below) carries the reason
    finally:
        proc.stdin.close()
    err = proc.stderr.read().decode("utf-8", "replace") if proc.stderr else ""
    if proc.wait() != 0:
        raise RuntimeError(f"ffmpeg encode failed ({out_path.name}):\n{err}")
    return len(zs)


def _run_tracks(durations: list[float], fps: int) -> list[SceneCameraTrack]:
    """Drive the shipping continuous camera over a run of stills with these per-scene
    ``durations`` at ``fps``, at the LOCKED feel (KB_CAMERA_*), and wrap each scene's
    per-frame zoom in a SceneCameraTrack. The track lets callers extend a scene past
    its natural window with zs_for's velocity extrapolation -- the freeze-fix that
    keeps the incoming side of a seam gliding instead of pad-holding."""
    specs = kb_camera.specs_from_durations(durations, fps=fps)
    run = kb_camera.compute_run(
        specs,
        reversal_period_s=KB_CAMERA_PERIOD_S,
        amplitude=KB_CAMERA_AMPLITUDE,
        interp=KB_CAMERA_INTERP,
        ease_frac=KB_CAMERA_EASE_FRAC,
        ease_seconds=KB_CAMERA_EASE_SECONDS,
        fps=fps,
    )
    tracks: list[SceneCameraTrack] = []
    for cam in run.scenes:
        z = cam.z
        tracks.append(
            SceneCameraTrack(
                gate="center", anchor=CENTER,
                z_range=(min(z), max(z)), _zs=tuple(z),
            )
        )
    return tracks


def _blur_sendcmd(
    to_peak: bool, start_frame: int, count: int, fps: int, peak: float, target: str
) -> str:
    """Per-frame ``<target> sigma`` commands ramping a blur-dissolve's defocus across
    its ``count``-frame (2N) overlap, timed on the clip's own timeline at ``fps`` --
    the fps-parameterized twin of assembly_service._blur_dissolve_sendcmd (which is
    pinned to the pipeline FPS=25 and so can't be reused here). ``to_peak`` -> the
    covered A side (sharp->soft, sigma 0->peak); else the resolving B side
    (soft->sharp, peak->0). Both ramp on the SAME inOutQuint easing as the opacity
    cross-dissolve so the softest, most-blended instant lands mid-overlap; a "sharp"
    frame floors at a no-op 0.01 (gblur sigma must be > 0), the same value gblur holds
    outside the overlap so neither edge shows a blur on/off seam.

    ``target`` is the sendcmd command target -- the UNIQUE gblur INSTANCE name for this
    side (e.g. "bda"/"bdb"), NOT the bare filter type "gblur". A bare "gblur" target
    matches ffmpeg's filter-TYPE name, so it is broadcast to EVERY gblur in the graph
    (avfilter matches target against filter->filter->name). With both the A-side and
    B-side gblur in one graph, each side's ramp then leaks into the other filter and
    the two fight -- yielding the streaked, sharp-center defocus-mess this harness was
    reported broken on. Naming each gblur (``gblur@bda`` / ``gblur@bdb``) and targeting
    its instance name confines each ramp to its own side, giving a clean symmetric
    defocus. (assembly_service.concat_clips_crossfade still uses the bare "gblur"
    target and so carries the SAME latent collision -- out of scope here.)"""
    denom = max(1, count - 1)
    cmds = []
    for j in range(count):
        e = _blur_dissolve_inoutquint(j / denom)
        sigma = peak * e if to_peak else peak * (1 - e)
        t = (start_frame + j) / fps
        cmds.append(f"{t:.4f} {target} sigma {max(0.01, sigma):.4f}")
    return ";".join(cmds)


def render_reversal(src: np.ndarray, out_path: Path, fps: int) -> int:
    """One long single-still scene whose continuous-camera zoom REVERSES on screen (a
    peak at the 8s reversal period, then back out). Returns the frame count."""
    track = _run_tracks([REVERSAL_SECONDS], fps)[0]
    n = round(REVERSAL_SECONDS * fps)
    zs = track.zs_for(n)  # n == natural window length -> no extrapolation here
    return _warp_zoom_clip(src, zs, out_path, fps)


def render_crossfade(
    src_a: np.ndarray, src_b: np.ndarray, out_path: Path, work_dir: Path, fps: int
) -> int:
    """Two KB stills in ONE continuous camera run, defocus-dissolved at their seam on
    the pipeline's blur-dissolve mechanic. Each flanking clip is extended by N frames
    with zs_for's velocity extrapolation (the freeze-fix), then the pair is
    eased-cross-dissolved over a centred 2N overlap with a per-side ramped Gaussian
    defocus. The motion continues THROUGH the seam. Returns the frame count (Fp+Fq)."""
    track_a, track_b = _run_tracks(
        [XFADE_SCENE_SECONDS, XFADE_SCENE_SECONDS], fps
    )
    fp = round(XFADE_SCENE_SECONDS * fps)
    fq = round(XFADE_SCENE_SECONDS * fps)
    n = max(1, round(XFADE_OVERLAP_SECONDS / 2 * fps))  # half-overlap frames

    # Extend each flanking clip +N frames past its natural window (velocity
    # extrapolation), so the 2N overlap centred on the seam still nets Fp+Fq frames.
    zs_a = track_a.zs_for(fp + n)
    zs_b = track_b.zs_for(fq + n)
    clip_a = work_dir / f"xf_a_{fps}.mp4"
    clip_b = work_dir / f"xf_b_{fps}.mp4"
    _warp_zoom_clip(src_a, zs_a, clip_a, fps)
    _warp_zoom_clip(src_b, zs_b, clip_b, fps)

    # A's overlap is its last 2N frames [Fp-N, Fp+N); B's is its first 2N [0, 2N). The
    # eased xfade offset (Fp-N)/fps centres the 2N overlap on the seam at frame Fp, so
    # the pair emits exactly Fp+Fq frames -- the pipeline's arithmetic, per-fps.
    a_start = fp - n
    overlap = 2 * n
    offset = a_start / fps
    dur = overlap / fps
    peak = float(BLUR_DISSOLVE_MAX_BLUR)
    # Each gblur gets a UNIQUE instance name (gblur@bda / gblur@bdb) and each side's
    # sendcmd targets that instance -- NOT the bare filter type "gblur", which ffmpeg
    # would broadcast to BOTH gblurs (see _blur_sendcmd), cross-contaminating the two
    # ramps into the streaked, sharp-center mess. Per-instance targeting confines each
    # ramp to its own side, so the overlap is a clean symmetric defocus dissolve.
    a_ramp = _blur_sendcmd(True, a_start, overlap, fps, peak, "bda")
    b_ramp = _blur_sendcmd(False, 0, overlap, fps, peak, "bdb")
    graph = (
        f"[0:v]sendcmd=c='{a_ramp}',gblur@bda=sigma=0.01:steps=3[ba];"
        f"[1:v]sendcmd=c='{b_ramp}',gblur@bdb=sigma=0.01:steps=3[bb];"
        f"[ba][bb]xfade=transition=custom:duration={dur:.4f}:offset={offset:.4f}:"
        f"expr='{_BLUR_EXPR}'[outv]"
    )
    # -frames:v Fp+Fq pins the output to the duration-neutral count (guards any xfade
    # off-by-one so all three fps clips stay the SAME duration).
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-i", str(clip_a), "-i", str(clip_b),
            "-filter_complex", graph, "-map", "[outv]",
            "-frames:v", str(fp + fq),
            "-r", str(fps), "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-pix_fmt", "yuv420p", str(out_path),
        ],
        check=True, capture_output=True,
    )
    return fp + fq


def _probe_frames(path: Path) -> int:
    out = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
            "-show_entries", "stream=nb_read_frames",
            "-of", "default=noprint_wrappers=1:nokey=1", str(path),
        ],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    return int(out)


def _probe_duration(path: Path) -> float:
    out = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(path),
        ],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    return float(out)


def _concat_segments(
    segs: list[Path], out_path: Path, work_dir: Path, expected_frames: int, fps: int
) -> None:
    """Join the reversal / crossfade / reversal segments. Prefer the concat demuxer
    (lossless stream copy -- all three are the same libx264 CFR encode at this fps);
    if it drops frames, fall back to a concat-filter re-encode of these segments."""
    lst = work_dir / "concat.txt"
    lst.write_text("".join(f"file '{s}'\n" for s in segs))
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
         "-i", str(lst), "-c", "copy", str(out_path)],
        check=True, capture_output=True,
    )
    if _probe_frames(out_path) == expected_frames:
        return
    print(f"    note: demuxer copy dropped frames; re-encoding concat at {fps}fps")
    inputs: list[str] = []
    for s in segs:
        inputs += ["-i", str(s)]
    labels = "".join(f"[{i}:v]" for i in range(len(segs)))
    graph = f"{labels}concat=n={len(segs)}:v=1:a=0[outv]"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", *inputs,
         "-filter_complex", graph, "-map", "[outv]",
         "-r", str(fps), "-c:v", "libx264", "-preset", "fast", "-crf", "18",
         "-pix_fmt", "yuv420p", str(out_path)],
        check=True, capture_output=True,
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-dir", default="/tmp/kb_fps_test2")
    args = ap.parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    for p in (STILL_REV1, STILL_XA, STILL_XB, STILL_REV2):
        if not p.exists():
            raise SystemExit(f"still not found: {p}")

    src_rev1 = _read_still(STILL_REV1)
    src_xa = _read_still(STILL_XA)
    src_xb = _read_still(STILL_XB)
    src_rev2 = _read_still(STILL_REV2)

    print(f"stills : rev1={STILL_REV1.name}  xfade={STILL_XA.name}->{STILL_XB.name}"
          f"  rev2={STILL_REV2.name}")
    print(f"feel   : period={KB_CAMERA_PERIOD_S:g}s amp={KB_CAMERA_AMPLITUDE:g} "
          f"interp={KB_CAMERA_INTERP} ease_frac={KB_CAMERA_EASE_FRAC:g} "
          f"env_ease={KB_CAMERA_EASE_SECONDS:g}s")
    print(f"layout : reversal {REVERSAL_SECONDS:g}s -> crossfade "
          f"{2 * XFADE_SCENE_SECONDS:g}s (~{XFADE_OVERLAP_SECONDS:g}s dissolve) -> "
          f"reversal {REVERSAL_SECONDS:g}s")
    print(f"out dir: {out_dir}\n")

    results: list[tuple[int, Path, int, int, int, int, float]] = []
    for fps in FPS_LADDER:
        work = out_dir / f"work_{fps}fps"
        work.mkdir(parents=True, exist_ok=True)
        seg1 = work / "seg1_reversal.mp4"
        seg2 = work / "seg2_crossfade.mp4"
        seg3 = work / "seg3_reversal.mp4"
        f1 = render_reversal(src_rev1, seg1, fps)
        f2 = render_crossfade(src_xa, src_xb, seg2, work, fps)
        f3 = render_reversal(src_rev2, seg3, fps)
        total = f1 + f2 + f3
        out_path = out_dir / f"kb_rev_xfade_{fps}fps.mp4"
        _concat_segments([seg1, seg2, seg3], out_path, work, total, fps)
        frames = _probe_frames(out_path)
        dur = _probe_duration(out_path)
        results.append((fps, out_path, f1, f2, f3, frames, dur))
        print(f"  {fps:>2d} fps -> {out_path}")
        print(f"        seg frames: reversal={f1}  crossfade={f2}  reversal={f3}  "
              f"total={total}  (probed {frames} frames, {dur:.3f}s)")

    print("\nsummary (SAME duration, only the fps/frame-count differs):")
    for fps, path, _f1, _f2, _f3, frames, dur in results:
        print(f"  {fps:>2d} fps : {frames:>4d} frames  {frames / fps:7.3f}s  "
              f"(container {dur:.3f}s)  {path}")
    durs = {round(f / fps, 3) for fps, _p, _a, _b, _c, f, _d in results}
    print(f"\n  duration match: {'YES' if len(durs) == 1 else 'NO'} "
          f"({sorted(durs)})")
    print("pipeline FPS constant UNCHANGED (throwaway comparison).")


if __name__ == "__main__":
    main()
