#!/usr/bin/env python3
"""kb_move_variety.py -- Step 3 first test: DELIBERATE move variety (zoom/pan/center).

Why this exists
---------------
Earlier rounds locked the shared ping-pong ZOOM (``kb_camera``, P8_A12: reversal
period 8s, amplitude 0.12, smoothstep reversals eased over ease_frac=0.10, a quick
run-end envelope ease) and the per-scene ANCHOR (``services/kb_shot_analysis`` +
U2-Netp: the subject when the gate says ``target``, centre when it says
``center``). Every still still MOVES the same way, though -- a zoom. This harness
adds move VARIETY driven entirely by the mask: ``kb_shot_analysis`` now tags each
still ``zoom`` | ``pan`` | ``center``, and this tool renders each accordingly:

  * ``zoom``   -- the current fixed-anchor push: the global ping-pong ``kb_camera``
                  zoom held at the subject anchor (unchanged).
  * ``center`` -- the same global ping-pong zoom held at the (clamped) centre.
  * ``pan``    -- for THIS first test a clean, self-contained move: a gentle FIXED
                  zoom (``PAN_ZOOM`` ~1.12, for lateral headroom) with the focal
                  point ANIMATED ``pan_from`` -> ``pan_to`` via smoothstep easing,
                  so the camera glides ACROSS and eases to rest on the subject. The
                  ping-pong is deliberately NOT applied to pan shots this round.

The single extension the pan needed is a PER-FRAME anchor: the reused warp
(``kb_camera_targeted._warp_frame``) already takes an anchor per call, so this tool
just drives a per-frame ``(z, anchor)`` stream through it instead of one fixed
anchor. ``zoom``/``center`` pass a constant anchor; ``pan`` passes a gliding one.

Target-X debug marker (default on; ``--no-marker`` disables)
-----------------------------------------------------------
Every frame gets the same thin magenta X the sibling harness uses, stamped where
that frame's anchor lands in the OUTPUT frame (``M @ [ax*SW, ay*SH, 1]``). For a
zoom/center it pins to the fixed subject/centre; for a pan the anchor IS the moving
focal point, so the X glides ``pan_from`` -> ``pan_to`` and comes to rest on the
subject -- the aim check this test is for.

Showcase (curated, ORDERED -- NOT a contiguous run)
---------------------------------------------------
``ORDERED_SCENES`` is a hand-picked spread of mosquito stills chosen to make every
move flavor appear (it is curated for illustration, so the cuts are NOT continuous
the way a real run's would be). The per-scene move is DERIVED from the mask, never
assigned here.

Standalone + UNWIRED: imports the pure-math camera + the detector module + the
committed subpixel warp / marker / filmstrip helpers, but touches NOTHING in the
pipeline and writes only into ``--out-dir``. No script/scene/TTS/image generation,
no API, no paid calls -- pure local ffmpeg + OpenCV + the one-time-downloaded
U2-Netp model on PNG stills already on disk.

How to run
----------
    python backend/tools/kb_move_variety.py
    python backend/tools/kb_move_variety.py --no-marker
    python backend/tools/kb_move_variety.py --out-dir /tmp/kb_step3
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# --- Isolated third-party libs: the same headless opencv+numpy pip-installed with
# --target into /tmp/kb/pylibs the sibling KB tools use, so this harness never
# touches either project venv's site-packages. -----------------------------------
PYLIBS = "/tmp/kb/pylibs"
if PYLIBS not in sys.path:
    sys.path.insert(0, PYLIBS)
import numpy as np  # noqa: E402
import cv2  # noqa: E402  (kept for parity with the sibling tools' import surface)

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
    _smoothstep,
)

# --- The pure-math camera + the semantic shot-analysis detector (services), plus
# the per-frame warp + target-X marker + frame extractor from the targeted-anchor
# harness -- reused so the pan just drives a per-frame anchor through them. --------
if str(_TOOLS.parents[0] / "services") not in sys.path:
    sys.path.insert(0, str(_TOOLS.parents[0] / "services"))
import kb_camera  # noqa: E402
import kb_shot_analysis  # noqa: E402
from kb_camera_targeted import (  # noqa: E402
    _draw_target_x,
    _warp_frame,
    extract_frames,
)

# --- The LOCKED camera (P8_A12 with the lighter reversal ease chosen last round). -
SETTING_NAME = "P8_A12"
SETTING_P, SETTING_A = 8.0, 0.12
SETTING_INTERP, SETTING_EASE_FRAC = "smoothstep", 0.10

# --- Pan move: a gentle FIXED zoom for lateral headroom while the anchor glides
# pan_from -> pan_to. Matches A's ceiling (1+0.12) so the framing scale is familiar.
PAN_ZOOM = 1.12

# --- Curated ORDERED showcase: interleaved so zoom / pan / center all appear. The
# move is DERIVED from each still's mask (kb_shot_analysis), NOT assigned here; this
# list only fixes the ORDER + which stills are shown. It is NOT a contiguous run.
# Named candidates from the U2-Netp probe: wide/multi pan-eligibles s020,s044,s055;
# single-subject zooms s002,s007,s039; center-gated s005,s028.
ORDERED_SCENES = [39, 55, 5, 20, 2, 44, 28, 7]


# --- Per-scene move construction (the per-frame zoom + anchor streams) ------------
def build_scene_move(
    cam: "kb_camera.SceneCamera", info: dict,
) -> tuple[list[float], list[tuple[float, float]]]:
    """Turn a still's DERIVED move into per-frame ``(zs, anchors)`` for the warp.

      pan  -- a FIXED ``PAN_ZOOM`` with the anchor eased ``pan_from`` -> ``pan_to``
              via smoothstep (ease in AND out -> arrives at rest on the subject); the
              global ping-pong is deliberately NOT applied this round.
      zoom -- the global ping-pong ``cam.z`` held at the fixed subject anchor.
      center -- the global ping-pong ``cam.z`` held at the fixed (clamped) centre.
    """
    frames = cam.frames
    if info["move"] == "pan":
        pf, pt = info["pan_from"], info["pan_to"]
        denom = frames - 1 if frames > 1 else 1
        anchors = []
        for k in range(frames):
            pe = _smoothstep(k / denom) if frames > 1 else 1.0
            anchors.append((pf[0] + (pt[0] - pf[0]) * pe,
                            pf[1] + (pt[1] - pf[1]) * pe))
        zs = [PAN_ZOOM] * frames
    else:  # zoom / center: ping-pong zoom at a constant anchor
        anchors = [info["anchor"]] * frames
        zs = list(cam.z)
    return zs, anchors


# --- Rendering (the PER-FRAME-anchor warp: same primitives, anchor now per frame) -
def render_scene_moving(
    src: np.ndarray, zs: list[float], anchors: list[tuple[float, float]],
    label: str, out_path: Path, draw_marker: bool,
) -> int:
    """Warp a scene's per-frame ``zs`` at PER-FRAME ``anchors`` (one (x,y) each
    frame) to a silent OUT_W x OUT_H clip, optionally stamping the target-X at that
    frame's anchor and burning ``label``, streamed to libx264. A zoom/center scene
    passes a constant anchor list; a pan passes a gliding one -- the ONLY change
    from the fixed-anchor harness."""
    src_h, src_w = src.shape[:2]
    proc = _open_encoder(out_path)
    assert proc.stdin is not None
    try:
        for z, anchor in zip(zs, anchors):
            frame, M = _warp_frame(src, z, anchor)
            if draw_marker:
                _draw_target_x(frame, M, anchor, src_w, src_h)
            if label:
                _put_label(frame, label)
            proc.stdin.write(np.ascontiguousarray(frame).tobytes())
    finally:
        proc.stdin.close()
    err = proc.stderr.read().decode("utf-8", "replace") if proc.stderr else ""
    if proc.wait() != 0:
        raise RuntimeError(f"ffmpeg encode failed ({out_path.name}):\n{err}")
    return len(zs)


# --- Main ----------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project", default=str(DEFAULT_PROJECT))
    ap.add_argument("--out-dir", default="/tmp/kb_step3")
    ap.add_argument("--model", default=str(kb_shot_analysis.DEFAULT_MODEL))
    ap.add_argument("--marker", dest="marker", action="store_true", default=True,
                    help="draw the target-X debug marker on each frame (default on)")
    ap.add_argument("--no-marker", dest="marker", action="store_false",
                    help="disable the target-X debug marker")
    args = ap.parse_args()

    project = Path(args.project).expanduser()
    footage_dir = project / "footage"
    windows = {w["id"]: w for w in json.loads((project / "scene_windows.json").read_text())}
    out_dir = Path(args.out_dir)
    work_root = out_dir / "_work"
    out_dir.mkdir(parents=True, exist_ok=True)
    work_root.mkdir(parents=True, exist_ok=True)

    # Resolve the curated ORDERED scenes (in list order), skipping any missing still.
    scenes: list[dict] = []
    for sid in ORDERED_SCENES:
        png = footage_dir / f"scene_{sid:03d}.png"
        if sid in windows and png.exists():
            scenes.append(windows[sid])
        else:
            print(f"  (skipping s{sid:03d}: missing still or window)")
    if not scenes:
        raise SystemExit(f"no curated stills found under {footage_dir}")
    ids = [s["id"] for s in scenes]
    durations = [s["duration"] for s in scenes]
    total_s = sum(durations)
    specs = kb_camera.specs_from_durations(durations)

    # The locked global ping-pong camera over the whole ORDERED set (zoom/center
    # scenes read cam.z off this; pan scenes substitute their own fixed-zoom move).
    run = kb_camera.compute_run(
        specs, reversal_period_s=SETTING_P, amplitude=SETTING_A,
        interp=SETTING_INTERP, ease_frac=SETTING_EASE_FRAC,
        ease_seconds=kb_camera.DEFAULT_EASE_SECONDS,
    )

    print(f"project : {project}")
    print(f"out dir : {out_dir}")
    print(f"showcase: {len(scenes)} curated scenes (ids {ids}), {total_s:.1f}s "
          f"(ORDERED, NOT contiguous)")
    print(f"camera  : {SETTING_NAME}  P={SETTING_P:g}s  A={SETTING_A:g}  "
          f"interp={SETTING_INTERP} ease_frac={SETTING_EASE_FRAC:g}  "
          f"ease={kb_camera.DEFAULT_EASE_SECONDS:g}s (quick envelope), {FPS}fps")
    print(f"pan     : fixed zoom {PAN_ZOOM:g}, anchor pan_from->pan_to smoothstep "
          f"(NO ping-pong on pans this round)")
    print(f"marker  : {'ON' if args.marker else 'off'} (target-X debug crosshair)\n")

    # --- Per-scene move classification (mask-derived; cached sidecar per still). ----
    print("=== per-scene move (services/kb_shot_analysis, U2-Netp) ===")
    print(f"  {'scene':>7} {'move':>7} {'gate':>7} {'anchor / pan path':>28} "
          f"{'conf':>5} {'cov':>6} {'dom':>5}")
    infos: list[dict] = []
    for s in scenes:
        r = kb_shot_analysis.analyze_still(
            footage_dir / f"scene_{s['id']:03d}.png", model_path=args.model
        )
        infos.append(r)
        if r["move"] == "pan":
            aim = (f"({r['pan_from'][0]:.2f},{r['pan_from'][1]:.2f})->"
                   f"({r['pan_to'][0]:.2f},{r['pan_to'][1]:.2f})")
        else:
            aim = f"({r['anchor'][0]:.2f},{r['anchor'][1]:.2f})"
        print(f"  s{s['id']:03d} {r['move']:>7} {r['gate']:>7} {aim:>28} "
              f"{r['confidence']:>5.2f} {r['coverage']:>6.3f} {r['dominance']:>5.2f}")
    counts = {m: sum(1 for r in infos if r["move"] == m) for m in ("zoom", "pan", "center")}
    print(f"  -> {counts['zoom']} zoom / {counts['pan']} pan / {counts['center']} center\n")

    # --- Render each scene with its own move, hard-cut into one showcase clip. ------
    print("=== render (per-scene move variety) ===")
    work = work_root / "scenes"
    work.mkdir(parents=True, exist_ok=True)
    clips: list[Path] = []
    t0 = time.perf_counter()
    for s, cam, info in zip(scenes, run.scenes, infos):
        zs, anchors = build_scene_move(cam, info)
        tag = info["move"].upper()
        label = (f"{SETTING_NAME}  s{s['id']:03d}  {tag}"
                 + (f"  z={PAN_ZOOM:g}" if info["move"] == "pan" else ""))
        clip = work / f"scene_{s['id']:03d}.mp4"
        render_scene_moving(
            cv2.imread(str(footage_dir / f"scene_{s['id']:03d}.png"), cv2.IMREAD_COLOR),
            zs, anchors, label, clip, args.marker,
        )
        clips.append(clip)
    out_clip = out_dir / "move_variety.mp4"
    _concat_copy(clips, out_clip, work)
    strip = out_dir / "frames_move_variety.png"
    render_filmstrip(out_clip, strip, work)
    dur = probe_duration(str(out_clip))
    print(f"[move_variety] {out_clip}  ({dur:.1f}s, {time.perf_counter() - t0:.1f}s render)")
    print(f"  {'':14s} filmstrip: {strip}")

    # --- Pan aim check: pull the first (pan_from), mid (glide) and last (pan_to =
    # subject) frame of each pan scene from the concatenated clip, so the burned-in
    # X can be eyeballed gliding to and RESTING on the subject. ----------------------
    print("\n=== pan aim check (marker frames: start -> glide -> rest on subject) ===")
    pan_scenes = [(s, cam, info) for s, cam, info in zip(scenes, run.scenes, infos)
                  if info["move"] == "pan"]
    if not pan_scenes:
        print("  (no pan-classified scenes in this showcase)")
    for s, cam, info in pan_scenes:
        last = cam.frames - 1
        picks = {"start": cam.start, "mid": cam.start + last // 2, "end": cam.start + last}
        out_paths = {
            gidx: out_dir / f"pan_s{s['id']:03d}_{tagn}_f{gidx}.png"
            for tagn, gidx in picks.items()
        }
        extract_frames(out_clip, list(out_paths), out_paths)
        pf, pt = info["pan_from"], info["pan_to"]
        print(f"  s{s['id']:03d}  pan {pf[0]:.2f}->{pt[0]:.2f} (x)  "
              f"subject rests at X@=({pt[0] * OUT_W:.0f},{pt[1] * OUT_H:.0f})px")
        for tagn, gidx in picks.items():
            print(f"    {tagn:>5}: {out_paths[gidx]}")

    # --- Teardown of per-scene intermediates (keep clip + filmstrip + pan frames). --
    for f in sorted(work.glob("*")):
        f.unlink(missing_ok=True)
    work.rmdir()
    if work_root.exists():
        work_root.rmdir()

    # --- Summary -------------------------------------------------------------------
    print("\n=== ORDERED scene list (move + anchor / pan path) ===")
    for s, info in zip(scenes, infos):
        if info["move"] == "pan":
            aim = (f"pan ({info['pan_from'][0]:.2f},{info['pan_from'][1]:.2f}) -> "
                   f"({info['pan_to'][0]:.2f},{info['pan_to'][1]:.2f})")
        else:
            aim = f"anchor ({info['anchor'][0]:.2f},{info['anchor'][1]:.2f})"
        print(f"  s{s['id']:03d}  {info['move']:>6}  {s['duration']:5.1f}s  {aim}")
    print(f"\n  move counts: {counts['zoom']} zoom / {counts['pan']} pan / "
          f"{counts['center']} center  (of {len(scenes)})")
    print(f"  clip: {out_clip}  ({dur:.1f}s)   filmstrip: {strip}")
    print("  WATCH the mp4 -- pan glide + rest-on-subject only reads in motion.")
    print("no generation / API / paid calls -- ffmpeg + OpenCV + local U2-Netp on "
          "existing PNG stills; pipeline untouched")


if __name__ == "__main__":
    main()
