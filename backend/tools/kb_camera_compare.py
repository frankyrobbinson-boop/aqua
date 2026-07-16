#!/usr/bin/env python3
"""kb_camera_compare.py -- compare settings for the global Ken Burns "virtual camera".

Why this exists
---------------
``services/kb_camera`` computes ONE continuous ping-pong zoom shared across a run
of consecutive stills, so the motion flows through the hard cuts instead of
resetting to a dead stop at every scene (the shipping behaviour). This harness
drives that camera on REAL mosquito-project stills at three tunings and renders a
labelled comparison clip for each, so a human can watch and rate the cadence /
amplitude. It also runs the acceptance checks and prints NUMBERS:

  * from the camera MATH -- velocity continuity across every cut, z in [1, 1+A],
    rest at the run's ends;
  * from the RENDERED video (opt-in ``--measure``) -- per-frame zoom measured by
    optical flow on 1-2 scenes vs the intended z curve; skipped by default now the
    warp is validated, so a re-run is just "render + math bounds/rest".

It is a standalone, UNWIRED harness: it imports the pure-math camera and reuses
the committed subpixel warp + filmstrip/probe helpers, but touches NOTHING in the
pipeline and writes only into ``--out-dir``. No script/scene/TTS/image generation,
no API, no paid calls -- pure local ffmpeg + OpenCV on PNG stills already on disk.

Render model (per scene)
------------------------
Each scene is warped with the committed SUBPIXEL approach (``kenburns_subpixel``:
``cv2.warpAffine``, INTER_LANCZOS4, BORDER_REFLECT_101, NO supersample), fed the
camera's per-frame ``z`` and anchor directly (a constant-zoom "move" at progress 0
reuses ``_warp_matrix`` unchanged). Scenes are HARD-CUT together -- no transitions,
cards or subtitles -- so only the motion is on show. The settings label is burned
per frame.

How to run
----------
Render the three clips + filmstrips + math-acceptance report into /tmp/kb_cam2
from the default mosquito project (a short ~30s run, for zoom-only tuning)::

    python backend/tools/kb_camera_compare.py

Optically re-measure the render (heavy, opt-in) / point elsewhere / cap the run::

    python backend/tools/kb_camera_compare.py --measure \
        --project ~/Documents/Aqua/projects/<slug> --max-scenes 7 --max-seconds 32
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# --- Isolated third-party libs: the same headless opencv+numpy pip-installed with
# --target into /tmp/kb/pylibs that kenburns_subpixel uses, so this harness never
# touches either project venv's site-packages. -----------------------------------
PYLIBS = "/tmp/kb/pylibs"
if PYLIBS not in sys.path:
    sys.path.insert(0, PYLIBS)
import numpy as np  # noqa: E402
import cv2  # noqa: E402

# --- Committed helpers: canvas/probe/filmstrip from kenburns_compare, the subpixel
# warp matrix + encoder + per-frame label + gray decode + concat from
# kenburns_subpixel. Reused verbatim so the render path can't drift. --------------
_TOOLS = Path(__file__).resolve().parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))
from kenburns_compare import (  # noqa: E402
    FPS,
    OUT_H,
    OUT_W,
    DEFAULT_PROJECT,
    probe_duration,
    render_filmstrip,
)
from kenburns_subpixel import (  # noqa: E402
    _concat_copy,
    _decode_gray,
    _open_encoder,
    _put_label,
    _warp_matrix,
)

# --- The pure-math camera engine (services module; stdlib-only, imported by path
# exactly the way the sibling tools import kenburns_compare). ---------------------
if str(_TOOLS.parents[0] / "services") not in sys.path:
    sys.path.insert(0, str(_TOOLS.parents[0] / "services"))
import kb_camera  # noqa: E402

# --- The three settings to compare. (name, reversal_period_s P, amplitude A).
# Round 2 brackets "longer reversal + stronger, sustained zoom": a longer P pushes
# the zoom for longer before it reverses (it "lasts longer"), and a larger A pushes
# it deeper. The names double as the output-clip filenames. -------------------------
SETTINGS: list[tuple[str, float, float]] = [
    ("P8_A12", 8.0, 0.12),
    ("P10_A16", 10.0, 0.16),
    ("P12_A20", 12.0, 0.20),
]
# Optical-flow probe (opt-in via --measure; off by default now the warp is
# validated). Probes the strongest-zoom setting => best flow SNR.
MEASURE_SETTING = "P12_A20"
MEASURE_SCENES = 2  # how many scenes to optically verify
MEASURE_W, MEASURE_H = 640, 360  # decode size for the flow probe

# Run caps: round 2 wants a SHORT ~30s clip for zoom-only tuning -- a contiguous run
# of a handful of scenes, still with a few interior cuts to show flow-through-cuts.
DEFAULT_MAX_SCENES = 7
DEFAULT_MAX_SECONDS = 32.0


# --- Scene selection -----------------------------------------------------------
def select_run(
    windows: list[dict], footage_dir: Path, max_scenes: int, max_seconds: float
) -> tuple[list[dict], float]:
    """A CONTIGUOUS run from the first scene: add scenes in order until we hit
    ``max_scenes`` or the next scene would push the total past ``max_seconds``
    (the first scene is always taken). Stops at the first missing still to keep
    the run contiguous. Returns (scenes, total_seconds)."""
    chosen: list[dict] = []
    total = 0.0
    for scene in windows:
        png = footage_dir / f"scene_{scene['id']:03d}.png"
        if not png.exists():
            break
        if len(chosen) >= max_scenes:
            break
        if chosen and total + scene["duration"] > max_seconds:
            break
        chosen.append(scene)
        total += scene["duration"]
    return chosen, total


# --- Rendering -----------------------------------------------------------------
def _warp_frame(src: np.ndarray, z: float, anchor: tuple[float, float]) -> np.ndarray:
    """One subpixel frame at explicit zoom ``z`` and ``anchor``. Reuses
    kenburns_subpixel._warp_matrix by expressing "hold zoom z at this anchor" as a
    constant move (z0=z1=z, cx0=cx1=ax, cy0=cy1=ay) evaluated at progress 0 -- so
    the geometry (base 16:9 fill, subpixel window, no supersample) is identical to
    the committed path."""
    ax, ay = anchor
    M = _warp_matrix(src.shape[1], src.shape[0], (z, z, ax, ay, ax, ay), 0.0, "linear")
    return cv2.warpAffine(
        src, M, (OUT_W, OUT_H),
        flags=cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_REFLECT_101,
    )


def render_scene(
    src: np.ndarray, cam: "kb_camera.SceneCamera", label: str, out_path: Path
) -> int:
    """Warp a scene's per-frame ``z`` (at its anchor) to a silent OUT_W x OUT_H
    clip, burning ``label`` per frame, streamed to libx264. Returns frame count."""
    proc = _open_encoder(out_path)
    assert proc.stdin is not None
    try:
        for z in cam.z:
            frame = _warp_frame(src, z, cam.anchor)
            if label:
                _put_label(frame, label)
            proc.stdin.write(np.ascontiguousarray(frame).tobytes())
    finally:
        proc.stdin.close()
    err = proc.stderr.read().decode("utf-8", "replace") if proc.stderr else ""
    if proc.wait() != 0:
        raise RuntimeError(f"ffmpeg encode failed ({out_path.name}):\n{err}")
    return len(cam.z)


# --- Acceptance: from the camera math ------------------------------------------
def math_acceptance(run: "kb_camera.RunCamera") -> dict:
    """Continuity / bounds / rest checks straight off the computed camera.

    The continuity test compares the max per-frame velocity JUMP at a cut against
    the distribution of per-frame velocity CHANGES within scenes. The run is mostly
    steady-velocity cruise (change ~0 there), so the median change is near zero and
    is the wrong yardstick; the meaningful comparators are the p95 / max of the
    within-scene changes and the percentile rank of the max boundary jump inside
    that distribution -- a jump that ranks below the within-scene max is an ordinary
    per-frame change and does not stand out. Also returns z bounds and the run's
    end velocities scaled by peak velocity."""
    within = [
        abs(s.velocity[i] - s.velocity[i - 1])
        for s in run.scenes
        for i in range(1, len(s.velocity))
    ]
    boundary = [
        abs(run.scenes[k + 1].velocity[0] - run.scenes[k].velocity[-1])
        for k in range(len(run.scenes) - 1)
    ]
    zmin = min(min(s.z) for s in run.scenes)
    zmax = max(max(s.z) for s in run.scenes)
    w = np.asarray(within, dtype=np.float64)
    max_boundary = max(boundary) if boundary else 0.0
    pct_rank = 100.0 * float((w <= max_boundary).mean()) if w.size else 0.0
    v_peak = max((abs(v) for v in run.velocity), default=0.0)
    return {
        "n_boundaries": len(boundary),
        "max_boundary_jump": max_boundary,
        "within_p95": float(np.percentile(w, 95)),
        "within_max": float(w.max()),
        "boundary_pct_rank": pct_rank,
        "zmin": zmin,
        "zmax": zmax,
        "z_hi_bound": 1.0 + run.amplitude,
        "v_first": run.velocity[0] if run.velocity else 0.0,
        "v_last": run.velocity[-1] if run.velocity else 0.0,
        "v_peak": v_peak,
    }


# --- Acceptance: from the rendered video (optical flow) ------------------------
def _radial_scale(ref: np.ndarray, cur: np.ndarray, anchor: tuple[float, float]) -> float:
    """Scale of ``cur`` relative to ``ref`` about ``anchor``, from dense optical
    flow. For a zoom-by-s about the anchor the flow of a pixel at radius r is
    (s-1)*r, so a least-squares fit of flow onto the radial vector over a central
    crop (excludes the corner label + reflected borders) gives s directly."""
    flow = cv2.calcOpticalFlowFarneback(
        ref, cur, None,
        pyr_scale=0.5, levels=4, winsize=31, iterations=3,
        poly_n=5, poly_sigma=1.2, flags=0,
    )
    h, w = ref.shape
    ax, ay = anchor[0] * w, anchor[1] * h
    hw = int(0.30 * min(h, w))  # central window about the zoom anchor
    x0, x1 = int(max(0, ax - hw)), int(min(w, ax + hw))
    y0, y1 = int(max(0, ay - hw)), int(min(h, ay + hw))
    ys, xs = np.mgrid[y0:y1, x0:x1]
    rx = xs - ax
    ry = ys - ay
    u = flow[y0:y1, x0:x1, 0]
    v = flow[y0:y1, x0:x1, 1]
    den = float((rx * rx + ry * ry).sum())
    if den <= 0.0:
        return 1.0
    return 1.0 + float((u * rx + v * ry).sum()) / den


def measure_rendered_zoom(
    clip: Path, cam: "kb_camera.SceneCamera", n_samples: int = 28
) -> dict:
    """Optically measure a rendered scene's zoom vs the intended curve. Decodes to
    grayscale, then for ~n_samples frames measures the scale relative to frame 0
    (larger baseline than frame-to-frame => better SNR) and compares to the
    intended relative zoom z[i]/z[0]. Returns Pearson r, the best-fit slope
    (measured vs intended, ideally ~1), and the RMS log error."""
    frames = _decode_gray(clip, MEASURE_W, MEASURE_H)
    n = len(frames)
    if n < 3:
        return {"n_frames": n, "ok": False}
    ref = frames[0].astype(np.uint8)
    idx = sorted(set(int(round(i)) for i in np.linspace(0, n - 1, n_samples)))
    s_meas = np.array([_radial_scale(ref, frames[i].astype(np.uint8), cam.anchor) for i in idx])
    z0 = cam.z[0]
    r_int = np.array([cam.z[i] / z0 for i in idx])
    # Correlate + fit in relative-zoom space; RMS in log space (perceptual).
    corr = float(np.corrcoef(s_meas, r_int)[0, 1])
    slope, intercept = np.polyfit(r_int, s_meas, 1)
    rms_log = float(np.sqrt(np.mean((np.log(s_meas) - np.log(r_int)) ** 2)))
    return {
        "n_frames": n,
        "ok": True,
        "z0": z0,
        "intended_min": min(cam.z),
        "intended_max": max(cam.z),
        "pearson_r": corr,
        "slope": float(slope),
        "rms_log": rms_log,
    }


def pick_measure_scenes(run: "kb_camera.RunCamera", k: int) -> list[int]:
    """Choose up to ``k`` scene indices to optically verify: prefer scenes whose
    intended zoom is MONOTONIC (a clean single-direction push, easiest to read),
    then largest zoom range (best flow SNR)."""
    scored = []
    for si, s in enumerate(run.scenes):
        dz = np.diff(np.asarray(s.z))
        rng = float(max(s.z) - min(s.z))
        pos = int((dz > 1e-6).sum())
        neg = int((dz < -1e-6).sum())
        monotonic = pos == 0 or neg == 0
        scored.append((monotonic, rng, si))
    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return [si for _, _, si in scored[:k]]


# --- Main ----------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project", default=str(DEFAULT_PROJECT))
    ap.add_argument("--out-dir", default="/tmp/kb_cam2")
    ap.add_argument("--max-scenes", type=int, default=DEFAULT_MAX_SCENES)
    ap.add_argument("--max-seconds", type=float, default=DEFAULT_MAX_SECONDS)
    ap.add_argument("--measure", action="store_true",
                    help="also run the heavy optical-flow re-measure (off by "
                         "default; the warp was validated in round 1)")
    args = ap.parse_args()

    project = Path(args.project).expanduser()
    footage_dir = project / "footage"
    windows = json.loads((project / "scene_windows.json").read_text())
    out_dir = Path(args.out_dir)
    work_root = out_dir / "_work"
    out_dir.mkdir(parents=True, exist_ok=True)
    work_root.mkdir(parents=True, exist_ok=True)

    scenes, total_s = select_run(windows, footage_dir, args.max_scenes, args.max_seconds)
    if not scenes:
        raise SystemExit(f"no scenes with stills under {footage_dir}")
    ids = [s["id"] for s in scenes]
    durations = [s["duration"] for s in scenes]
    specs = kb_camera.specs_from_durations(durations)

    print(f"project : {project}")
    print(f"out dir : {out_dir}")
    print(f"run     : {len(scenes)} contiguous scenes (ids {ids[0]}..{ids[-1]}), "
          f"{total_s:.1f}s")
    print(f"          (cap {args.max_scenes} scenes / {args.max_seconds:.0f}s; "
          f"one 25fps clip per setting)\n")

    # Cache each still once (reused across all three settings).
    srcs: dict[int, np.ndarray] = {}
    for s in scenes:
        img = cv2.imread(str(footage_dir / f"scene_{s['id']:03d}.png"), cv2.IMREAD_COLOR)
        if img is None:
            raise SystemExit(f"unreadable still: scene_{s['id']:03d}.png")
        srcs[s["id"]] = img

    results: list[dict] = []
    runs: dict[str, "kb_camera.RunCamera"] = {}
    scene_clips: dict[str, list[Path]] = {}

    for name, P, A in SETTINGS:
        t0 = time.perf_counter()
        run = kb_camera.compute_run(specs, reversal_period_s=P, amplitude=A)
        runs[name] = run
        label = f"{name.replace('_', ' ')}   P={P:g}s  A={A:g}"
        work = work_root / name
        work.mkdir(parents=True, exist_ok=True)
        clips: list[Path] = []
        for scene, cam in zip(scenes, run.scenes):
            clip = work / f"scene_{scene['id']:03d}.mp4"
            render_scene(srcs[scene["id"]], cam, label, clip)
            clips.append(clip)
        scene_clips[name] = clips
        out_clip = out_dir / f"{name}.mp4"
        _concat_copy(clips, out_clip, work)
        strip = out_dir / f"frames_{name}.png"
        render_filmstrip(out_clip, strip, work)
        dur = probe_duration(str(out_clip))
        dt = time.perf_counter() - t0
        results.append({"name": name, "P": P, "A": A, "clip": out_clip,
                        "strip": strip, "dur": dur})
        print(f"[{name}] {out_clip}  ({dur:.1f}s, {dt:.1f}s render)  "
              f"filmstrip: {strip}")

    # --- Acceptance: camera math (all three settings) ----------------------------
    print("\n=== acceptance A) camera math -- boundary continuity / bounds / rest ===")
    for name, _P, _A in SETTINGS:
        m = math_acceptance(runs[name])
        stands_out = m["max_boundary_jump"] > m["within_max"] + 1e-9
        verdict = "STANDS OUT" if stands_out else "within the within-scene spread (does not stand out)"
        bounds_ok = m["zmin"] >= 1 - 1e-9 and m["zmax"] <= m["z_hi_bound"] + 1e-9
        peak = m["v_peak"] + 1e-12
        print(f"  [{name}]")
        print(f"    boundaries={m['n_boundaries']}  max boundary |dv|={m['max_boundary_jump']:.3e}")
        print(f"    within-scene |dv|: p95={m['within_p95']:.3e}  max={m['within_max']:.3e}  "
              f"(peak |v|={m['v_peak']:.3e})")
        print(f"    -> max boundary jump ranks at the {m['boundary_pct_rank']:.0f}th pct of "
              f"within-scene changes; {verdict}")
        print(f"    z range=[{m['zmin']:.4f}, {m['zmax']:.4f}]  bound=[1.0, {m['z_hi_bound']:.2f}]  "
              f"-> {'OK' if bounds_ok else 'OUT OF BOUNDS'}")
        print(f"    rest at ends: v_first={m['v_first']:.2e} ({abs(m['v_first']) / peak * 100:.1f}% of peak)  "
              f"v_last={m['v_last']:.2e} ({abs(m['v_last']) / peak * 100:.1f}% of peak)")

    # --- Acceptance: rendered video vs intended zoom (optical flow; opt-in) -------
    if args.measure:
        print(f"\n=== acceptance B) rendered vs intended zoom -- optical flow on "
              f"'{MEASURE_SETTING}' ===")
        run = runs[MEASURE_SETTING]
        pick = pick_measure_scenes(run, MEASURE_SCENES)
        for si in pick:
            scene_id = scenes[si]["id"]
            clip = scene_clips[MEASURE_SETTING][si]
            stats = measure_rendered_zoom(clip, run.scenes[si])
            if not stats.get("ok"):
                print(f"  scene_{scene_id:03d}: too short to measure ({stats['n_frames']} frames)")
                continue
            print(f"  scene_{scene_id:03d} ({stats['n_frames']} frames)  "
                  f"intended z {stats['intended_min']:.3f}->{stats['intended_max']:.3f}")
            print(f"    measured-vs-intended  pearson_r={stats['pearson_r']:.3f}  "
                  f"slope={stats['slope']:.3f}  rms_log={stats['rms_log']:.4f}  "
                  f"-> {'MATCH' if stats['pearson_r'] > 0.9 else 'WEAK -- inspect'}")
        print("  (pearson_r = curve-shape match, the validation; slope < 1 is the known "
              "dense-flow\n   magnitude under-read, not a render error; rms_log is log-zoom "
              "error.)")
    else:
        print("\n=== acceptance B) optical-flow re-measure: SKIPPED "
              "(pass --measure to run; the warp was validated in round 1) ===")

    # --- Teardown of per-scene intermediates (keep clips + filmstrips) -----------
    for name in scene_clips:
        work = work_root / name
        for p in sorted(work.glob("*")):
            p.unlink(missing_ok=True)
        if work.exists():
            work.rmdir()
    if work_root.exists():
        work_root.rmdir()

    # --- Summary -----------------------------------------------------------------
    print("\n=== clips (WATCH these -- motion can only be judged in the mp4) ===")
    for r in results:
        print(f"  {r['name']:16s} {r['clip']}  ({r['dur']:.1f}s)  P={r['P']:g}s A={r['A']:g}")
        print(f"  {'':16s} filmstrip: {r['strip']}")
    print(f"\nrun: {len(scenes)} scenes (ids {ids[0]}..{ids[-1]}), {total_s:.1f}s each clip")
    print("hard cuts only -- no transitions / cards / subtitles (motion isolated)")
    print("no generation / API / paid calls -- ffmpeg + OpenCV on existing PNG stills; "
          "pipeline untouched")


if __name__ == "__main__":
    main()
