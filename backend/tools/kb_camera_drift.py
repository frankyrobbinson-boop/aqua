#!/usr/bin/env python3
"""kb_camera_drift.py -- A/B "drift-to-center" focal motion vs the current pivot.

Why this exists
---------------
Pans are SHELVED -- gliding the crop across a still broke the image-to-image zoom
smoothness the global ping-pong buys us. This round tests the replacement primary
variety, DRIFT-TO-CENTER, which must PRESERVE that smoothness: the shared ping-pong
ZOOM is left completely untouched (same ``services/kb_camera`` signal, same cross-cut
velocity continuity); only the framing's FOCAL POINT moves.

Two clips over the SAME curated run at the SAME LOCKED camera (P8_A12: reversal_period
8s, amplitude 0.12, interp=smoothstep, ease_frac=0.10, quick envelope ease) with the
SAME per-scene targeted anchors -- ONLY the focal behaviour differs:

  * ``pivot.mp4`` -- the CURRENT fixed-anchor push: the crop-centre is pinned at the
    subject anchor for the whole shot, so a source anchor maps to a CONSTANT output
    position (subject stays put on screen and grows). This is exactly the behaviour
    the sibling ``kb_camera_targeted`` renders; its ``_warp_frame`` is reused verbatim.
  * ``drift.mp4`` -- DRIFT-TO-CENTER: the crop-centre ANIMATES as a function of the
    per-frame zoom. At the shot's most-zoomed-OUT frame (z == the window minimum, ~1.0)
    the crop-centre is the frame centre (0.5, 0.5) -> the full re-based frame, subject
    at its natural position. As z rises toward the shot's peak the crop-centre lerps
    toward the subject anchor, so the subject drifts toward output-centre and enlarges;
    a zoom-OUT shot runs it in reverse (starts on the subject, pulls out, the subject
    settles into the scene = a reveal).

The drift mechanic (per output frame, TARGETED shots)
-----------------------------------------------------
    d(z)         = (z - z_min_window) / (z_peak_window - z_min_window)   in [0, 1]
    crop_centre  = lerp( (0.5, 0.5), subject_anchor, d(z) )              clamped to [0,1]

``d`` is a pure function of the per-frame zoom, so it is 0 at the window's most-
zoomed-out frame and 1 at its most-zoomed-in frame REGARDLESS of whether the shot is
pushing in or pulling out -- a zoom-in pushes the subject to centre, a zoom-out
reverses it. Because the crop-centre destination (the anchor) is already edge-margin
clamped by ``services/kb_shot_analysis`` and we only ever lerp BETWEEN it and centre,
the crop-centre stays in [0,1], which is precisely the in-bounds condition for the
subpixel warp (the window is fully inside the source -- no black / reflected edges).
The reachable centering is limited by the ~12% zoom headroom at A=0.12, and that
headroom is almost all VERTICAL (a square source fills 16:9 on width, so the whole
width shows and horizontal reframing room is tiny) -- partial centering is expected
and fine. CENTER-gated shots have anchor == (0.5, 0.5), so the lerp is a no-op and
they keep the plain centre zoom (no drift).

CRITICAL invariant: ``cam.z`` (the global ping-pong) is UNCHANGED. Both clips drive
the identical ``kb_camera.compute_run`` output; only the crop-centre fed to the warp
differs. The continuity / bounds numbers are therefore identical for both, which is
the smoothness guarantee this harness prints for each.

Target-X debug marker
---------------------
With the marker on (default; ``--no-marker`` disables) every frame gets a thin,
semi-transparent magenta X where the scene's SOURCE anchor lands in the OUTPUT frame,
mapped through that frame's warp affine ``M`` (``out = M @ [ax*SW, ay*SH, 1]``). On
``pivot.mp4`` the X pins to the subject (the anchor is the zoom's fixed point). On
``drift.mp4`` the X visibly MOVES toward centre as a zoom-in shot pushes in, and away
from centre as a zoom-out shot reveals -- the whole point the marker lets you eyeball.

It is a standalone, UNWIRED harness: it imports the pure-math camera + the detector
module + the committed subpixel warp / marker / filmstrip helpers, but touches NOTHING
in the pipeline and writes only into ``--out-dir``. No script/scene/TTS/image/outline
generation, no API, no paid calls -- pure local ffmpeg + OpenCV + the one-time-
downloaded U2-Netp model on PNG stills already on disk.

How to run
----------
    python backend/tools/kb_camera_drift.py
    python backend/tools/kb_camera_drift.py --no-marker
    python backend/tools/kb_camera_drift.py --ids 8,20,3,6,5,55,39,10
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# --- Isolated third-party libs: the same headless opencv+numpy pip-installed with
# --target into /tmp/kb/pylibs that the sibling KB tools use, so this harness never
# touches either project venv's site-packages. -----------------------------------
PYLIBS = "/tmp/kb/pylibs"
if PYLIBS not in sys.path:
    sys.path.insert(0, PYLIBS)
import numpy as np  # noqa: E402
import cv2  # noqa: E402

# --- Committed helpers, reused verbatim so the render path can't drift. -----------
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
    _open_encoder,
    _put_label,
    _warp_matrix,
)
# The fixed-anchor warp + the marker + the exact-frame extractor come straight from
# the sibling targeted harness, so ``pivot.mp4`` IS its current behaviour and the
# marker geometry is shared with ``drift.mp4``.
from kb_camera_targeted import (  # noqa: E402
    _draw_target_x,
    _warp_frame,
    extract_frames,
)

# --- The pure-math camera + the semantic shot-analysis detector (services modules;
# imported by path exactly the way the sibling tools import kenburns_compare). ------
if str(_TOOLS.parents[0] / "services") not in sys.path:
    sys.path.insert(0, str(_TOOLS.parents[0] / "services"))
import kb_camera  # noqa: E402
import kb_shot_analysis  # noqa: E402

# --- The single LOCKED camera under test (P8_A12 + the quick reversals): reversal
# period P, amplitude A, smoothstep reversals eased over ease_frac of each ramp, and
# the quick amplitude envelope. Both clips use this IDENTICAL zoom; only the focal
# behaviour differs. ---------------------------------------------------------------
SETTING_NAME, SETTING_P, SETTING_A = "P8_A12", 8.0, 0.12
SETTING_INTERP, SETTING_EASE_FRAC = "smoothstep", 0.10

# --- The two focal behaviours: (out-name, label tag). ``pivot`` = fixed anchor (the
# current push); ``drift`` = drift-to-centre. Anchors + zoom are IDENTICAL across the
# two; only the per-frame crop-centre differs. -------------------------------------
FOCAL_MODES: list[tuple[str, str]] = [
    ("pivot", "PIVOT (fixed anchor)"),
    ("drift", "DRIFT->centre"),
]

# --- Curated ORDERED ~1-min run. Deliberately spans several clearly OFF-CENTRE
# subjects so the drift is visible (s008 scientist ~0.68x; s020 plants ~0.26x/0.64y;
# s006 bucket ~0.69y; s055 patio ~0.58x/0.64y), a couple near-centre targets (s003,
# s039, s010) and one CENTER-gated still (s005). Overridable with --ids. -----------
CURATED_IDS: list[int] = [8, 20, 3, 6, 5, 55, 39, 10]

N_PEAK_SCENES = 3  # most off-centre target scenes spot-checked per clip (peak+trough)

EPS = 1e-9  # guard for a degenerate (flat-zoom) window in d(z)


# --- Scene selection -----------------------------------------------------------
def select_curated(windows: list[dict], footage_dir: Path, ids: list[int]) -> list[dict]:
    """Pick the requested scene ids IN ORDER (a curated set, not a contiguous run),
    skipping any whose still is missing. Laid out contiguously on the run's frame
    clock by ``specs_from_durations`` later, so cross-cut continuity still holds
    regardless of the source scene order."""
    by_id = {w["id"]: w for w in windows}
    chosen: list[dict] = []
    for sid in ids:
        scene = by_id.get(sid)
        if scene is None:
            continue
        if not (footage_dir / f"scene_{sid:03d}.png").exists():
            continue
        chosen.append(scene)
    return chosen


# --- Drift-to-centre geometry --------------------------------------------------
def _drift_crop_center(
    z: float, z_min: float, z_peak: float, anchor: tuple[float, float]
) -> tuple[float, float, float]:
    """The drift crop-centre for this frame: lerp( centre, anchor, d(z) ), clamped
    into [0,1] (the warp's in-bounds condition). ``d(z)`` is 0 at the window's most-
    zoomed-out frame and 1 at its peak; a degenerate window (no zoom) yields d=0 ->
    plain centre. Returns (cx, cy, d)."""
    ax, ay = anchor
    span = z_peak - z_min
    d = (z - z_min) / span if span > EPS else 0.0
    d = min(1.0, max(0.0, d))
    cx = min(1.0, max(0.0, 0.5 + (ax - 0.5) * d))
    cy = min(1.0, max(0.0, 0.5 + (ay - 0.5) * d))
    return cx, cy, d


def _warp_frame_drift(
    src: np.ndarray, z: float, z_min: float, z_peak: float, anchor: tuple[float, float]
) -> tuple[np.ndarray, np.ndarray, tuple[float, float]]:
    """One subpixel frame at zoom ``z`` whose CROP-CENTRE is the drift lerp, plus the
    2x3 warp affine ``M`` (for the marker) and the crop-centre used. Identical geometry
    to the sibling fixed-anchor ``_warp_frame`` except the crop-centre is (cx, cy)
    instead of the anchor -- at d=1 (peak) they coincide, so the peak frame matches
    pivot exactly; the drift lives entirely in the approach."""
    cx, cy, _d = _drift_crop_center(z, z_min, z_peak, anchor)
    M = _warp_matrix(src.shape[1], src.shape[0], (z, z, cx, cy, cx, cy), 0.0, "linear")
    frame = cv2.warpAffine(
        src, M, (OUT_W, OUT_H),
        flags=cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_REFLECT_101,
    )
    return frame, M, (cx, cy)


def _subject_out(M: np.ndarray, anchor: tuple[float, float], src_w: int, src_h: int
                 ) -> tuple[float, float]:
    """Where the SOURCE anchor lands in the OUTPUT frame, normalized to [0,1] (the
    marker's location). ``out = M @ [ax*SW, ay*SH, 1]`` / (OUT_W, OUT_H)."""
    ax, ay = anchor
    pt = M @ np.array([ax * src_w, ay * src_h, 1.0], dtype=np.float64)
    return float(pt[0]) / OUT_W, float(pt[1]) / OUT_H


# --- Rendering -----------------------------------------------------------------
def render_scene_focal(
    src: np.ndarray, zs: list[float], anchor: tuple[float, float],
    mode: str, label: str, out_path: Path, draw_marker: bool,
) -> tuple[list[float], list[float]]:
    """Warp a scene's per-frame ``zs`` to a silent OUT_W x OUT_H clip under one focal
    ``mode`` -- ``pivot`` pins the crop-centre at the anchor (reusing the committed
    ``_warp_frame``); ``drift`` animates it toward the anchor as z rises. Optionally
    stamps the target-X (at the SOURCE anchor, through each frame's actual ``M``) and
    burns ``label``. Returns the (min, max) crop-centre seen on each axis -- the in-
    bounds evidence for the drift clip."""
    src_h, src_w = src.shape[:2]
    z_min, z_peak = min(zs), max(zs)
    cc_lo = [1.0, 1.0]
    cc_hi = [0.0, 0.0]
    proc = _open_encoder(out_path)
    assert proc.stdin is not None
    try:
        for z in zs:
            if mode == "drift":
                frame, M, (cx, cy) = _warp_frame_drift(src, z, z_min, z_peak, anchor)
            else:  # pivot: crop-centre FIXED at the anchor (the current behaviour)
                frame, M = _warp_frame(src, z, anchor)
                cx, cy = anchor
            cc_lo[0] = min(cc_lo[0], cx); cc_hi[0] = max(cc_hi[0], cx)
            cc_lo[1] = min(cc_lo[1], cy); cc_hi[1] = max(cc_hi[1], cy)
            if draw_marker:
                _draw_target_x(frame, M, anchor, src_w, src_h)
            if label:
                _put_label(frame, label)  # label on top, never hidden by the marker
            proc.stdin.write(np.ascontiguousarray(frame).tobytes())
    finally:
        proc.stdin.close()
    err = proc.stderr.read().decode("utf-8", "replace") if proc.stderr else ""
    if proc.wait() != 0:
        raise RuntimeError(f"ffmpeg encode failed ({out_path.name}):\n{err}")
    return cc_lo, cc_hi


def render_mode(
    mode: str, label: str, scenes: list[dict], run: "kb_camera.RunCamera",
    srcs: dict[int, np.ndarray], anchors: list[tuple[float, float]],
    out_dir: Path, work_root: Path, draw_marker: bool,
) -> tuple[Path, list[float], list[float]]:
    """Render one focal mode: every scene warped with THIS run's camera z at the
    shared per-scene ``anchors``, hard-cut into ``<mode>.mp4``. Returns the clip path
    and the run-wide (min, max) crop-centre on each axis."""
    work = work_root / mode
    work.mkdir(parents=True, exist_ok=True)
    clips: list[Path] = []
    cc_lo = [1.0, 1.0]
    cc_hi = [0.0, 0.0]
    for scene, cam, anchor in zip(scenes, run.scenes, anchors):
        clip = work / f"scene_{scene['id']:03d}.mp4"
        s_lo, s_hi = render_scene_focal(
            srcs[scene["id"]], cam.z, anchor, mode, label, clip, draw_marker
        )
        cc_lo = [min(cc_lo[0], s_lo[0]), min(cc_lo[1], s_lo[1])]
        cc_hi = [max(cc_hi[0], s_hi[0]), max(cc_hi[1], s_hi[1])]
        clips.append(clip)
    out_clip = out_dir / f"{mode}.mp4"
    _concat_copy(clips, out_clip, work)
    return out_clip, cc_lo, cc_hi


# --- Camera continuity / bounds (from the pure-math run; identical for both) -----
def continuity(run: "kb_camera.RunCamera") -> dict:
    """The smoothness-guarantee numbers the sibling harness reports, read off the
    shared ``RunCamera``: z bounds, rest at both ends, and the cross-cut velocity
    continuity (max boundary |dv| vs the ordinary within-scene |dv|)."""
    within = [
        abs(s.velocity[i] - s.velocity[i - 1])
        for s in run.scenes for i in range(1, len(s.velocity))
    ]
    boundary = [
        abs(run.scenes[k + 1].velocity[0] - run.scenes[k].velocity[-1])
        for k in range(len(run.scenes) - 1)
    ]
    v_peak = max((abs(v) for v in run.velocity), default=0.0) + 1e-12
    return {
        "z_lo": min(min(s.z) for s in run.scenes),
        "z_hi": max(max(s.z) for s in run.scenes),
        "max_within": max(within) if within else 0.0,
        "max_boundary": max(boundary) if boundary else 0.0,
        "v_first": run.velocity[0], "v_last": run.velocity[-1], "v_peak": v_peak,
    }


# --- Self-check (free: pure math, no cv2/ffmpeg) -------------------------------
def _sanity_drift() -> None:
    """Prove the drift mechanic's boundary conditions: d=0 (most zoomed out) -> the
    crop-centre is the frame centre; d=1 (peak) -> it is the anchor (so the peak frame
    equals pivot); an off-centre anchor lerps monotonically between; a flat window ->
    d=0 (no drift); and the crop-centre never leaves [0,1] (in-bounds)."""
    anchor = (0.68, 0.69)
    cx0, cy0, d0 = _drift_crop_center(1.00, 1.00, 1.12, anchor)
    cx1, cy1, d1 = _drift_crop_center(1.12, 1.00, 1.12, anchor)
    assert (cx0, cy0, d0) == (0.5, 0.5, 0.0), (cx0, cy0, d0)
    assert abs(cx1 - anchor[0]) < 1e-12 and abs(cy1 - anchor[1]) < 1e-12 and d1 == 1.0
    cxh, cyh, dh = _drift_crop_center(1.06, 1.00, 1.12, anchor)
    assert 0.5 < cxh < anchor[0] and 0.5 < cyh < anchor[1] and abs(dh - 0.5) < 1e-9
    fx, fy, fd = _drift_crop_center(1.05, 1.05, 1.05, anchor)  # degenerate window
    assert (fx, fy, fd) == (0.5, 0.5, 0.0)
    for z in (1.0, 1.03, 1.07, 1.12):
        cx, cy, _ = _drift_crop_center(z, 1.0, 1.12, (0.14, 0.70))
        assert 0.0 <= cx <= 1.0 and 0.0 <= cy <= 1.0


# --- Main ----------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project", default=str(DEFAULT_PROJECT))
    ap.add_argument("--out-dir", default="/tmp/kb_drift")
    ap.add_argument("--model", default=str(kb_shot_analysis.DEFAULT_MODEL))
    ap.add_argument("--ids", default=None,
                    help="comma-separated scene ids for the curated run "
                         f"(default {','.join(map(str, CURATED_IDS))})")
    ap.add_argument("--marker", dest="marker", action="store_true", default=True,
                    help="draw the target-X debug marker on each frame (default on)")
    ap.add_argument("--no-marker", dest="marker", action="store_false",
                    help="disable the target-X debug marker")
    args = ap.parse_args()

    _sanity_drift()

    project = Path(args.project).expanduser()
    footage_dir = project / "footage"
    windows = json.loads((project / "scene_windows.json").read_text())
    out_dir = Path(args.out_dir)
    work_root = out_dir / "_work"
    out_dir.mkdir(parents=True, exist_ok=True)
    work_root.mkdir(parents=True, exist_ok=True)

    ids = ([int(x) for x in args.ids.split(",")] if args.ids else CURATED_IDS)
    scenes = select_curated(windows, footage_dir, ids)
    if not scenes:
        raise SystemExit(f"no curated scenes with stills under {footage_dir}")
    sids = [s["id"] for s in scenes]
    durations = [s["duration"] for s in scenes]
    total_s = sum(durations)
    specs = kb_camera.specs_from_durations(durations)

    print(f"project : {project}")
    print(f"out dir : {out_dir}")
    print(f"run     : {len(scenes)} curated scenes (ids {sids}), {total_s:.1f}s")
    print(f"camera  : {SETTING_NAME}  P={SETTING_P:g}s  A={SETTING_A:g}  "
          f"interp={SETTING_INTERP} ease_frac={SETTING_EASE_FRAC:g}  "
          f"ease={kb_camera.DEFAULT_EASE_SECONDS:g}s (quick envelope), {FPS}fps")
    print(f"marker  : {'ON' if args.marker else 'off'} (target-X debug crosshair)")
    print(f"modes   : {', '.join(tag for _n, tag in FOCAL_MODES)}\n")

    # Cache each still once (reused across both modes).
    srcs: dict[int, np.ndarray] = {}
    for s in scenes:
        img = cv2.imread(str(footage_dir / f"scene_{s['id']:03d}.png"), cv2.IMREAD_COLOR)
        if img is None:
            raise SystemExit(f"unreadable still: scene_{s['id']:03d}.png")
        srcs[s["id"]] = img

    # --- Semantic targeting: gate + anchor per scene (cached sidecar per still),
    # computed ONCE and shared by both focal modes. ---------------------------------
    print("=== per-scene targeting (services/kb_shot_analysis, U2-Netp) ===")
    print(f"  {'scene':>7} {'gate':>7} {'anchor(x,y)':>13} {'conf':>5} {'cov':>6} {'dom':>5}")
    anchors: list[tuple[float, float]] = []
    gates: list[str] = []
    for s in scenes:
        r = kb_shot_analysis.analyze_still(
            footage_dir / f"scene_{s['id']:03d}.png", model_path=args.model
        )
        gates.append(r["gate"])
        anchors.append(r["anchor"])  # already centre when gate == center
        ax, ay = r["anchor"]
        print(f"  s{s['id']:03d} {r['gate']:>10} ({ax:.2f},{ay:.2f}) "
              f"{r['confidence']:>5.2f} {r['coverage']:>6.3f} {r['dominance']:>5.2f}")
    n_target = sum(1 for g in gates if g == "target")
    print(f"  -> {n_target} target / {len(gates) - n_target} center\n")

    # --- Compute the shared camera ONCE. Both clips drive this identical cam.z; only
    # the crop-centre fed to the warp differs. --------------------------------------
    run = kb_camera.compute_run(
        specs, reversal_period_s=SETTING_P, amplitude=SETTING_A,
        interp=SETTING_INTERP, ease_frac=SETTING_EASE_FRAC,
        ease_seconds=kb_camera.DEFAULT_EASE_SECONDS,
    )

    # --- Render the two focal modes (same run + zoom + anchors; ONLY the focal
    # behaviour differs). -----------------------------------------------------------
    label_base = (f"{SETTING_NAME}  P={SETTING_P:g}s A={SETTING_A:g} "
                  f"ease={SETTING_EASE_FRAC:g}")
    print("=== render (2 focal modes, shared run + anchors) ===")
    results: list[dict] = []
    for mode, tag in FOCAL_MODES:
        label = f"{label_base}  {tag}"
        t0 = time.perf_counter()
        out_clip, cc_lo, cc_hi = render_mode(
            mode, label, scenes, run, srcs, anchors, out_dir, work_root, args.marker
        )
        strip = out_dir / f"frames_{mode}.png"
        render_filmstrip(out_clip, strip, work_root / mode)
        dur = probe_duration(str(out_clip))
        results.append({
            "mode": mode, "tag": tag, "clip": out_clip, "strip": strip,
            "dur": dur, "cc_lo": cc_lo, "cc_hi": cc_hi,
        })
        print(f"[{mode}] {out_clip}  ({dur:.1f}s, {time.perf_counter() - t0:.1f}s render)  {tag}")
        print(f"  {'':10s} filmstrip: {strip}")

    # --- Continuity + bounds: the SAME numbers for both (cam.z is untouched). --------
    c = continuity(run)
    hi_bound = 1.0 + SETTING_A
    assert c["z_lo"] >= 1.0 - 1e-9 and c["z_hi"] <= hi_bound + 1e-9, (c["z_lo"], c["z_hi"])
    assert c["max_boundary"] <= c["max_within"] + 1e-9, (c["max_boundary"], c["max_within"])
    print("\n=== zoom bounds + rest + cross-cut continuity (per clip; IDENTICAL "
          "-- cam.z is unchanged) ===")
    print(f"  {'clip':10s} {'z-range':>17s}   {'v_first':>15s}   {'v_last':>15s}   "
          f"{'maxbnd|dv|':>10s} {'maxwin|dv|':>10s}")
    for r in results:
        print(f"  {r['mode']:10s} [{c['z_lo']:.4f},{c['z_hi']:.4f}]   "
              f"{c['v_first']:+.2e} ({abs(c['v_first']) / c['v_peak'] * 100:4.1f}%)   "
              f"{c['v_last']:+.2e} ({abs(c['v_last']) / c['v_peak'] * 100:4.1f}%)   "
              f"{c['max_boundary']:.2e}   {c['max_within']:.2e}")
    print(f"  z within [1.0000, {hi_bound:.4f}]; v_first == 0 (exact rest at start); "
          f"v_last tiny envelope residual (rest at end);")
    print(f"  max boundary |dv| ({c['max_boundary']:.2e}) <= max within-scene |dv| "
          f"({c['max_within']:.2e}) -> cuts don't stand out (continuity holds).")

    # --- Drift in-bounds: crop-centre stayed inside [0,1] on every frame -> the warp
    # window is fully inside the source -> no black / reflected edges. ---------------
    dr = next(r for r in results if r["mode"] == "drift")
    pv = next(r for r in results if r["mode"] == "pivot")
    print("\n=== drift stays in-bounds (crop-centre over ALL frames) ===")
    print(f"  drift crop-centre: x in [{dr['cc_lo'][0]:.4f}, {dr['cc_hi'][0]:.4f}]  "
          f"y in [{dr['cc_lo'][1]:.4f}, {dr['cc_hi'][1]:.4f}]")
    in_bounds = (0.0 <= dr['cc_lo'][0] and dr['cc_hi'][0] <= 1.0
                 and 0.0 <= dr['cc_lo'][1] and dr['cc_hi'][1] <= 1.0)
    print(f"  all within [0,1]: {'YES' if in_bounds else 'NO'} -> window inside the "
          f"source, no black/reflected edges.")
    print(f"  (pivot crop-centre is the constant clamped anchor: "
          f"x in [{pv['cc_lo'][0]:.4f}, {pv['cc_hi'][0]:.4f}] "
          f"y in [{pv['cc_lo'][1]:.4f}, {pv['cc_hi'][1]:.4f}])")

    # --- Peak/trough spot-check: for the most off-centre TARGET scenes, report where
    # the subject sits at the window's most-zoomed-out frame vs its peak, on BOTH
    # clips, and pull those frames so the framing + in-bounds can be eyeballed. On
    # drift the subject travels toward centre as z rises; pivot holds it at the anchor.
    def _offset(i: int) -> float:
        ax, ay = anchors[i]
        return ((ax - 0.5) ** 2 + (ay - 0.5) ** 2) ** 0.5

    target_idxs = [i for i, g in enumerate(gates) if g == "target"]
    picks = sorted(target_idxs, key=_offset, reverse=True)[:N_PEAK_SCENES]

    print("\n=== subject drift-to-centre spot-check (most off-centre target scenes) ===")
    if not picks:
        print("  (no target-gated scenes in this run)")
    frame_jobs: dict[str, tuple[list[int], dict[int, Path]]] = {
        r["mode"]: ([], {}) for r in results
    }
    for i in picks:
        cam = run.scenes[i]
        sid = scenes[i]["id"]
        src = srcs[sid]
        src_h, src_w = src.shape[:2]
        ax, ay = anchors[i]
        z = cam.z
        ipk = int(np.argmax(z)); itr = int(np.argmin(z))
        zpk, ztr = z[ipk], z[itr]
        # zoom-IN dominant if the peak is late in the shot; zoom-OUT if early.
        where = ("push-in" if ipk > len(z) * 0.6 else
                 "pull-out(reveal)" if ipk < len(z) * 0.4 else "mid-reversal")
        # Drift subject output at trough (natural) vs peak (== anchor); pivot is the
        # constant anchor. Distances to centre show the toward-centre travel.
        M_tr = _warp_frame_drift(src, ztr, ztr, zpk, (ax, ay))[1]
        M_pk = _warp_frame_drift(src, zpk, ztr, zpk, (ax, ay))[1]
        d_tr = _subject_out(M_tr, (ax, ay), src_w, src_h)
        d_pk = _subject_out(M_pk, (ax, ay), src_w, src_h)
        off_tr = ((d_tr[0] - 0.5) ** 2 + (d_tr[1] - 0.5) ** 2) ** 0.5
        off_pk = ((d_pk[0] - 0.5) ** 2 + (d_pk[1] - 0.5) ** 2) ** 0.5
        print(f"  s{sid:03d} {where:>16}  anchor=({ax:.3f},{ay:.3f})  z {ztr:.3f}->{zpk:.3f}")
        print(f"    pivot subject: ({ax:.3f},{ay:.3f}) constant  (dist-to-centre {_offset(i):.3f})")
        print(f"    drift subject: ({d_tr[0]:.3f},{d_tr[1]:.3f}) at most-zoomed-out "
              f"-> ({d_pk[0]:.3f},{d_pk[1]:.3f}) at peak  "
              f"(dist-to-centre {off_tr:.3f} -> {off_pk:.3f})")
        # queue the peak frame (both clips) + the drift trough frame for extraction.
        for r in results:
            gidx = cam.start + ipk
            p = out_dir / f"peak_{r['mode']}_s{sid:03d}_f{gidx}_z{zpk:.3f}.png"
            frame_jobs[r["mode"]][0].append(gidx)
            frame_jobs[r["mode"]][1][gidx] = p
        gtr = cam.start + itr
        ptr = out_dir / f"trough_drift_s{sid:03d}_f{gtr}_z{ztr:.3f}.png"
        frame_jobs["drift"][0].append(gtr)
        frame_jobs["drift"][1][gtr] = ptr
    for r in results:
        idxs, paths = frame_jobs[r["mode"]]
        if idxs:
            extract_frames(r["clip"], idxs, paths)
    if picks:
        print("  frames written (peak = both clips; trough = drift only):")
        for r in results:
            for _idx, p in sorted(frame_jobs[r["mode"]][1].items()):
                print(f"    {p}")
        print("  on drift the subject is nearest centre at a push-in shot's PEAK; "
              "the peak frame equals pivot (d=1 -> crop-centre = anchor), the drift is "
              "in the approach. Horizontal-only off-centre subjects barely move -- the "
              "~12% headroom is almost all vertical.")

    # --- Teardown of per-scene intermediates (keep clips + filmstrips + spot frames).
    for mode, _tag in FOCAL_MODES:
        work = work_root / mode
        if work.exists():
            for f in sorted(work.glob("*")):
                f.unlink(missing_ok=True)
            work.rmdir()
    if work_root.exists():
        work_root.rmdir()

    # --- Summary -------------------------------------------------------------------
    print("\n=== clips (WATCH these -- the drift can only be judged in the mp4) ===")
    for r in results:
        print(f"  {r['mode']:10s} {r['clip']}  ({r['dur']:.1f}s)  [{r['tag']}]")
        print(f"  {'':10s} filmstrip: {r['strip']}")
    print(f"\nrun: {len(scenes)} curated scenes (ids {sids}), {total_s:.1f}s each clip; "
          f"hard cuts only; {FPS}fps; targeted anchors")
    print("both clips share the SAME run + zoom setting + anchors; ONLY the focal "
          "behaviour differs (pivot = fixed anchor, drift = drift-to-centre)")
    print("no generation / API / paid calls -- ffmpeg + OpenCV + local U2-Netp on "
          "existing PNG stills; pipeline untouched")


if __name__ == "__main__":
    main()
