#!/usr/bin/env python3
"""kb_camera_targeted.py -- A/B the global Ken Burns camera's REVERSAL EASING.

Why this exists
---------------
Earlier rounds tuned the shared ping-pong ZOOM (period + amplitude) and then the
per-scene ANCHOR (centre vs. the U2-Netp subject target). This round tests how the
ping-pong REVERSES: the current profile eases the velocity in/out of each reversal
but CRUISES at a constant rate between (a trapezoidal velocity), which can feel like
it "drags" at a fixed speed. It renders THREE clips over the SAME contiguous run at
the SAME zoom setting and the SAME (targeted) anchors -- ONLY the reversal easing
differs:

  * ``A_trap25_current.mp4`` -- interp=smoothstep, ease_frac=0.25 (the current
                                "draggy" reference: long cruise, short eases).
  * ``B_trap10_lighter.mp4`` -- interp=smoothstep, ease_frac=0.10 (lighter/quicker
                                reversals -> more cruise, less drag at the turns).
  * ``C_sine_flowy.mp4``     -- interp=sine: a raised-cosine wave whose velocity
                                varies CONTINUOUSLY (no constant-speed cruise at all).

There is NO centre-baseline this round -- every clip uses the targeted anchors from
``services/kb_shot_analysis`` (the subject when the gate says ``target``, centre when
it says ``center``), so the only visible variable is the flow of the reversals.

Target-X debug marker
---------------------
With the marker on (default; ``--no-marker`` disables) every output frame gets a
thin, semi-transparent magenta X where the scene's SOURCE anchor lands in the OUTPUT
frame -- the anchor point ``(ax*SW, ay*SH)`` mapped through that frame's warp affine
``M`` (``out = M @ [ax*SW, ay*SH, 1]``). For an anchored push the anchor is the
zoom's FIXED POINT, so this X pins to the subject for the whole scene (it jumps only
at the hard cuts) -- which is exactly the aim it lets you eyeball; the general
M-mapping would also track a moving focal centre if one were ever animated.

Setting: P8_A12 (reversal_period=8s, amplitude=0.12) with the QUICK envelope ease
(``kb_camera.ease_seconds``), so even this ~60s run shows the real cadence.

It is a standalone, UNWIRED harness: it imports the pure-math camera + the detector
module + the committed subpixel warp / filmstrip helpers, but touches NOTHING in the
pipeline and writes only into ``--out-dir``. No script/scene/TTS/image generation, no
API, no paid calls -- pure local ffmpeg + OpenCV + the one-time-downloaded U2-Netp
model on PNG stills already on disk.

How to run
----------
    python backend/tools/kb_camera_targeted.py
    python backend/tools/kb_camera_targeted.py --start-scene 5 --max-seconds 66
    python backend/tools/kb_camera_targeted.py --no-marker
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

# --- The pure-math camera + the semantic shot-analysis detector (services modules;
# imported by path exactly the way the sibling tools import kenburns_compare). ------
if str(_TOOLS.parents[0] / "services") not in sys.path:
    sys.path.insert(0, str(_TOOLS.parents[0] / "services"))
import kb_camera  # noqa: E402
import kb_shot_analysis  # noqa: E402

# --- The single ZOOM setting under test (name, reversal_period_s P, amplitude A);
# only the reversal EASING varies across the three clips below. --------------------
SETTING_NAME, SETTING_P, SETTING_A = "P8_A12", 8.0, 0.12

# --- The three easing profiles: (out-name, interp, ease_frac, label tag). ``sine``
# ignores ease_frac (None here), so compute_run keeps its default and the guard
# there sets the triangle-ease to 0. Anchors + zoom are IDENTICAL across all three;
# only the reversal easing differs. -----------------------------------------------
EASE_VARIANTS: list[tuple[str, str, float | None, str]] = [
    ("A_trap25_current", "smoothstep", 0.25, "TRAP ease=0.25"),
    ("B_trap10_lighter", "smoothstep", 0.10, "TRAP ease=0.10"),
    ("C_sine_flowy", "sine", None, "SINE"),
]

# --- Run selection: a CONTIGUOUS run summing to ~60s. The default start (scene 5)
# gives ids 5..11 (~59.5s), which deliberately spans the variety we want to SEE: a
# person shot (the detector aims off-centre at the scientist) and several center-
# gated scenes alongside clean single-subject targets. ----------------------------
DEFAULT_START_SCENE = 5
DEFAULT_MAX_SCENES = 10
DEFAULT_MAX_SECONDS = 66.0

N_PEAK_SCENES = 2  # most off-centre target scenes pulled per clip for the aim check

# --- Target-X debug marker (drawn per frame at the anchor's output location) -------
MARKER_COLOR = (255, 0, 255)  # BGR magenta -- a clear, non-photographic colour
MARKER_SIZE = 40              # full span of the X in output px (~40px, thin)
MARKER_THICK = 2              # thin strokes
MARKER_ALPHA = 0.6            # semi-transparent so the subject stays visible under it


# --- Scene selection -----------------------------------------------------------
def select_run(
    windows: list[dict], footage_dir: Path, start_scene: int,
    max_scenes: int, max_seconds: float,
) -> tuple[list[dict], float]:
    """A CONTIGUOUS run beginning at the first present still with id >= start_scene:
    add scenes in order until ``max_scenes`` or the next scene would push the total
    past ``max_seconds`` (the first scene is always taken). Stops at the first
    missing still to keep the run contiguous. Returns (scenes, total_seconds)."""
    chosen: list[dict] = []
    total = 0.0
    for scene in windows:
        if scene["id"] < start_scene:
            continue
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
def _warp_frame(
    src: np.ndarray, z: float, anchor: tuple[float, float]
) -> tuple[np.ndarray, np.ndarray]:
    """One subpixel frame at explicit zoom ``z`` and ``anchor``, plus the 2x3 warp
    affine ``M`` used to produce it (so the caller can map the source anchor into
    output coords for the debug marker). Reuses kenburns_subpixel._warp_matrix by
    expressing "hold zoom z at this anchor" as a constant move evaluated at progress
    0 -- identical geometry to the committed path (base 16:9 fill, subpixel window,
    no supersample)."""
    ax, ay = anchor
    M = _warp_matrix(src.shape[1], src.shape[0], (z, z, ax, ay, ax, ay), 0.0, "linear")
    frame = cv2.warpAffine(
        src, M, (OUT_W, OUT_H),
        flags=cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_REFLECT_101,
    )
    return frame, M


def _draw_target_x(
    frame: np.ndarray, M: np.ndarray, anchor: tuple[float, float],
    src_w: int, src_h: int,
) -> None:
    """Draw the thin, semi-transparent magenta target-X where this scene's SOURCE
    anchor lands in the OUTPUT frame: map the anchor point (ax*SW, ay*SH) through the
    per-frame warp ``out = M @ [ax*SW, ay*SH, 1]`` and stamp an X there. For the
    fixed-anchor push the anchor is the zoom's fixed point, so the X pins to the
    subject across the scene; using the full M-mapping keeps it correct even if the
    focal centre were ever animated. Debug overlay only -- never in the pipeline."""
    ax, ay = anchor
    pt = M @ np.array([ax * src_w, ay * src_h, 1.0], dtype=np.float64)
    ox, oy = int(round(float(pt[0]))), int(round(float(pt[1])))
    half = MARKER_SIZE // 2
    overlay = frame.copy()  # X drawn on a copy, then alpha-blended -> translucent
    cv2.line(overlay, (ox - half, oy - half), (ox + half, oy + half),
             MARKER_COLOR, MARKER_THICK, cv2.LINE_AA)
    cv2.line(overlay, (ox - half, oy + half), (ox + half, oy - half),
             MARKER_COLOR, MARKER_THICK, cv2.LINE_AA)
    cv2.addWeighted(overlay, MARKER_ALPHA, frame, 1.0 - MARKER_ALPHA, 0.0, dst=frame)


def render_scene(
    src: np.ndarray, zs: list[float], anchor: tuple[float, float],
    label: str, out_path: Path, draw_marker: bool,
) -> int:
    """Warp a scene's per-frame ``zs`` at a FIXED ``anchor`` to a silent
    OUT_W x OUT_H clip, optionally stamping the target-X at the anchor and burning
    ``label`` per frame, streamed to libx264. The three clips share ``anchor`` and
    differ only in ``zs`` (the reversal easing)."""
    src_h, src_w = src.shape[:2]
    proc = _open_encoder(out_path)
    assert proc.stdin is not None
    try:
        for z in zs:
            frame, M = _warp_frame(src, z, anchor)
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
    return len(zs)


def render_variant(
    name: str, label: str, scenes: list[dict], run: "kb_camera.RunCamera",
    srcs: dict[int, np.ndarray], anchors: list[tuple[float, float]],
    out_dir: Path, work_root: Path, draw_marker: bool,
) -> Path:
    """Render one easing variant: every scene warped with THIS run's camera z at the
    shared per-scene ``anchors``, hard-cut into ``<name>.mp4``."""
    work = work_root / name
    work.mkdir(parents=True, exist_ok=True)
    clips: list[Path] = []
    for scene, cam, anchor in zip(scenes, run.scenes, anchors):
        clip = work / f"scene_{scene['id']:03d}.mp4"
        render_scene(srcs[scene["id"]], cam.z, anchor, label, clip, draw_marker)
        clips.append(clip)
    out_clip = out_dir / f"{name}.mp4"
    _concat_copy(clips, out_clip, work)
    return out_clip


# --- Peak-zoom frame extraction (aim sanity check) ------------------------------
def extract_frames(clip: Path, indices: list[int], out_paths: dict[int, Path]) -> None:
    """Pull exact global frame ``indices`` out of an encoded clip by sequential
    decode (exact, unlike keyframe seeking) and write each to ``out_paths[idx]``."""
    want = set(indices)
    cap = cv2.VideoCapture(str(clip))
    idx = 0
    while want:
        ok, frame = cap.read()
        if not ok:
            break
        if idx in want:
            cv2.imwrite(str(out_paths[idx]), frame)
            want.discard(idx)
        idx += 1
    cap.release()
    if want:
        raise RuntimeError(f"could not extract frames {sorted(want)} from {clip}")


# --- Main ----------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project", default=str(DEFAULT_PROJECT))
    ap.add_argument("--out-dir", default="/tmp/kb_ease")
    ap.add_argument("--model", default=str(kb_shot_analysis.DEFAULT_MODEL))
    ap.add_argument("--start-scene", type=int, default=DEFAULT_START_SCENE)
    ap.add_argument("--max-scenes", type=int, default=DEFAULT_MAX_SCENES)
    ap.add_argument("--max-seconds", type=float, default=DEFAULT_MAX_SECONDS)
    ap.add_argument("--marker", dest="marker", action="store_true", default=True,
                    help="draw the target-X debug marker on each frame (default on)")
    ap.add_argument("--no-marker", dest="marker", action="store_false",
                    help="disable the target-X debug marker")
    args = ap.parse_args()

    project = Path(args.project).expanduser()
    footage_dir = project / "footage"
    windows = json.loads((project / "scene_windows.json").read_text())
    out_dir = Path(args.out_dir)
    work_root = out_dir / "_work"
    out_dir.mkdir(parents=True, exist_ok=True)
    work_root.mkdir(parents=True, exist_ok=True)

    scenes, total_s = select_run(
        windows, footage_dir, args.start_scene, args.max_scenes, args.max_seconds
    )
    if not scenes:
        raise SystemExit(f"no scenes with stills at/after {args.start_scene} under {footage_dir}")
    ids = [s["id"] for s in scenes]
    durations = [s["duration"] for s in scenes]
    specs = kb_camera.specs_from_durations(durations)

    print(f"project : {project}")
    print(f"out dir : {out_dir}")
    print(f"run     : {len(scenes)} contiguous scenes (ids {ids[0]}..{ids[-1]}), {total_s:.1f}s")
    print(f"camera  : {SETTING_NAME}  P={SETTING_P:g}s  A={SETTING_A:g}  "
          f"ease={kb_camera.DEFAULT_EASE_SECONDS:g}s (quick envelope), {FPS}fps")
    print(f"marker  : {'ON' if args.marker else 'off'} (target-X debug crosshair)")
    print(f"easings : {', '.join(tag for _n, _i, _e, tag in EASE_VARIANTS)}\n")

    # Cache each still once (reused across all three variants).
    srcs: dict[int, np.ndarray] = {}
    for s in scenes:
        img = cv2.imread(str(footage_dir / f"scene_{s['id']:03d}.png"), cv2.IMREAD_COLOR)
        if img is None:
            raise SystemExit(f"unreadable still: scene_{s['id']:03d}.png")
        srcs[s["id"]] = img

    # --- Semantic targeting: gate + anchor per scene (cached sidecar per still),
    # computed ONCE and shared by all three easing variants. ------------------------
    print("=== per-scene targeting (services/kb_shot_analysis, U2-Netp) ===")
    print(f"  {'scene':>7} {'gate':>7} {'anchor(x,y)':>13} {'conf':>5} {'cov':>6} {'dom':>5}")
    targeted_anchors: list[tuple[float, float]] = []
    gates: list[str] = []
    for s in scenes:
        r = kb_shot_analysis.analyze_still(
            footage_dir / f"scene_{s['id']:03d}.png", model_path=args.model
        )
        gates.append(r["gate"])
        targeted_anchors.append(r["anchor"])  # already centre when gate == center
        ax, ay = r["anchor"]
        print(f"  s{s['id']:03d} {r['gate']:>10} ({ax:.2f},{ay:.2f}) "
              f"{r['confidence']:>5.2f} {r['coverage']:>6.3f} {r['dominance']:>5.2f}")
    n_target = sum(1 for g in gates if g == "target")
    print(f"  -> {n_target} target / {len(gates) - n_target} center\n")

    # --- Render the three easing variants (same run + zoom + anchors; ONLY the
    # reversal easing differs). -----------------------------------------------------
    label_base = f"{SETTING_NAME}  P={SETTING_P:g}s A={SETTING_A:g}  TARGETED"
    print("=== render (3 easing profiles, targeted anchors) ===")
    results: list[dict] = []
    for name, interp, ease_frac, tag in EASE_VARIANTS:
        kwargs = {} if ease_frac is None else {"ease_frac": ease_frac}
        run = kb_camera.compute_run(
            specs, reversal_period_s=SETTING_P, amplitude=SETTING_A,
            interp=interp, ease_seconds=kb_camera.DEFAULT_EASE_SECONDS, **kwargs,
        )
        label = f"{label_base}  {tag}"
        t0 = time.perf_counter()
        out_clip = render_variant(
            name, label, scenes, run, srcs, targeted_anchors, out_dir, work_root, args.marker
        )
        strip = out_dir / f"frames_{name}.png"
        render_filmstrip(out_clip, strip, work_root / name)
        dur = probe_duration(str(out_clip))
        z_lo = min(min(c.z) for c in run.scenes)
        z_hi = max(max(c.z) for c in run.scenes)
        v_peak = max((abs(v) for v in run.velocity), default=0.0) + 1e-12
        results.append({
            "name": name, "tag": tag, "interp": interp, "run": run,
            "clip": out_clip, "strip": strip, "dur": dur,
            "z_lo": z_lo, "z_hi": z_hi,
            "v_first": run.velocity[0], "v_last": run.velocity[-1], "v_peak": v_peak,
        })
        print(f"[{name}] {out_clip}  ({dur:.1f}s, {time.perf_counter() - t0:.1f}s render)  {tag}")
        print(f"  {'':16s} filmstrip: {strip}")

    # --- Bounds + rest confirmation (from the pure-math camera, for all three) ------
    hi_bound = 1.0 + SETTING_A
    print("\n=== bounds + rest at ends (per easing) ===")
    print(f"  {'variant':18s} {'z-range':>17s}   {'v_first':>16s}   {'v_last':>16s}")
    for r in results:
        assert r["z_lo"] >= 1.0 - 1e-9 and r["z_hi"] <= hi_bound + 1e-9, (
            r["name"], r["z_lo"], r["z_hi"])
        vf, vl, vp = r["v_first"], r["v_last"], r["v_peak"]
        print(f"  {r['name']:18s} [{r['z_lo']:.4f},{r['z_hi']:.4f}]   "
              f"{vf:+.2e} ({abs(vf) / vp * 100:4.1f}%)   {vl:+.2e} ({abs(vl) / vp * 100:4.1f}%)")
    print(f"  all z within [1.0000, {hi_bound:.4f}]; v_first == 0 (exact rest at the start);")
    print(f"  v_last is the tiny backward-difference residual of the envelope ramp-down")
    print(f"  (< 1e-3 log-zoom/frame, ~0.1% zoom/frame -> at rest at both ends).")

    # --- Aim check: peak-zoom marker frames pulled from EACH clip -------------------
    # The aim check bites hardest where the anchor is FURTHEST off-centre: pull the
    # peak-zoom (max-z) frame of the N_PEAK_SCENES most off-centre TARGET scenes from
    # every clip, so the burned-in X can be eyeballed on the subject at full zoom for
    # each easing (the anchor -- hence the marker's output position -- is identical
    # across easings; only the framing/zoom differs).
    def _offset(i: int) -> float:
        ax, ay = targeted_anchors[i]
        return ((ax - 0.5) ** 2 + (ay - 0.5) ** 2) ** 0.5

    target_idxs = [i for i, g in enumerate(gates) if g == "target"]
    picks = sorted(target_idxs, key=_offset, reverse=True)[:N_PEAK_SCENES]

    print("\n=== peak-zoom aim check (marker frames pulled from each clip) ===")
    if not picks:
        print("  (no target-gated scenes in this run -- centre-gated anchors only)")
    for r in results:
        run = r["run"]
        frame_indices: list[int] = []
        out_paths: dict[int, Path] = {}
        rows: list[tuple] = []
        for i in picks:
            cam = run.scenes[i]
            local_peak = int(np.argmax(cam.z))
            gidx = cam.start + local_peak
            sid = scenes[i]["id"]
            ax, ay = targeted_anchors[i]
            p = out_dir / f"peak_{r['name']}_s{sid:03d}_f{gidx}_z{cam.z[local_peak]:.3f}.png"
            frame_indices.append(gidx)
            out_paths[gidx] = p
            rows.append((sid, gidx, cam.z[local_peak], ax, ay, p))
        if frame_indices:
            extract_frames(r["clip"], frame_indices, out_paths)
        for sid, gidx, z, ax, ay, p in rows:
            print(f"  {r['name']:18s} s{sid:03d} frame {gidx:>4}  z={z:.3f}  "
                  f"anchor=({ax:.2f},{ay:.2f}) -> X@=({ax * OUT_W:.0f},{ay * OUT_H:.0f})px")
            print(f"    {p}")

    # --- Teardown of per-scene intermediates (keep clips + filmstrips + peaks) ------
    for name, *_rest in EASE_VARIANTS:
        work = work_root / name
        if work.exists():
            for f in sorted(work.glob("*")):
                f.unlink(missing_ok=True)
            work.rmdir()
    if work_root.exists():
        work_root.rmdir()

    # --- Summary -------------------------------------------------------------------
    print("\n=== clips (WATCH these -- flow/aim can only be judged in the mp4) ===")
    for r in results:
        print(f"  {r['name']:18s} {r['clip']}  ({r['dur']:.1f}s)  [{r['tag']}]")
        print(f"  {'':18s} filmstrip: {r['strip']}")
    print(f"\nrun: {len(scenes)} contiguous scenes (ids {ids[0]}..{ids[-1]}), {total_s:.1f}s each "
          f"clip; hard cuts only; {FPS}fps; targeted anchors")
    print("all three share the SAME run + zoom setting + anchors; ONLY the reversal easing differs")
    print("no generation / API / paid calls -- ffmpeg + OpenCV + local U2-Netp on existing "
          "PNG stills; pipeline untouched")


if __name__ == "__main__":
    main()
