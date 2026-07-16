#!/usr/bin/env python3
"""kb_target_probe_u2net.py -- FREE feasibility probe: SEMANTIC Ken Burns targeting.

Why this exists
---------------
The sibling ``kb_target_probe.py`` answers "can cheap LOCAL vision auto-target the
Ken Burns zoom?" using BRIGHTNESS saliency (spectral-residual / contrib
StaticSaliency). On our AI mosquito stills that landed on the real subject only
~4 of 9 times -- it chases contrast, so it missed the people shots (scene_008,
scene_030) entirely and wandered into bright background on wide scenes.

This probe swaps the detector for a SEMANTIC one: U2-Netp, the ~4.6MB lite
salient-object-detection network (the model behind ``rembg``'s background
removal). Instead of "what is bright/high-contrast", U2-Net asks "what is the
foreground OBJECT" -- so in principle it should grab the flower / frog / bucket /
person as a whole. We run it locally, mark where it would aim the zoom (the
subject anchor) plus a clear-subject gate call, and tile everything into one
montage so a human can judge accuracy against the brightness probe.

This is OBSERVATIONAL. There is deliberately NO face rule, NO "never zoom a face"
rule, and NO person special-casing anywhere in this file. It is the raw detector
plus a confidence gate, nothing more -- we look at what U2-Net actually does first.

Per image it:
  1. runs U2-Netp (320x320 input -> single-channel foreground-probability map,
     upscaled back to the still) with the model's own preprocessing (per-image
     max-scale + ImageNet mean/std, exactly as U2-Net / rembg feed it);
  2. picks the ANCHOR = probability-weighted centroid of the LARGEST connected
     foreground blob (mask thresholded at MASK_THR), normalized to [0,1];
  3. computes a CLEAR-SUBJECT GATE from the mask -- coverage (fraction of frame),
     mean confidence inside the mask, dominance (largest blob's share of all
     foreground) and blob count -- and classifies TARGET (one clear, confident,
     compact subject -> zoom the anchor) vs CENTER (weak / scattered / whole-frame
     / tiny -> safe center zoom). Every number is printed and burned into the
     overlay so the gate can be TUNED later; the thresholds here are first guesses;
  4. draws the overlay -- foreground-prob heatmap + mask contour + anchor
     crosshair + a label (gate + metrics) -- and tiles all of them into a montage.

It reads only PNG stills that already exist on disk and writes only PNGs to
``--out-dir``. No script/scene/outline/TTS/image generation, no paid API, no
network calls at run time (the model is a one-time local download). Nothing is
written into any project.

Model
-----
U2-Netp ONNX (~4.6MB), the lite salient-object model, from the rembg model
release::

    https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2netp.onnx
    sha256 309c8469258dda742793dce0ebea8e6dd393174f89934733ecc8b14c76f4ddd8

It lives at ``backend/models/u2netp.onnx`` (git-ignored -- the blob is not
committed; re-download with the curl line above). Inference route is auto-probed:
``cv2.dnn.readNetFromONNX`` is tried first (it loads AND runs u2netp on the cv2
5.0 build here -- verified), and only if cv2.dnn cannot load the graph does it
fall back to ``onnxruntime`` (import from an isolated ``/tmp/kb/pylibs`` if that is
where it was pip-installed with ``--target`` -- the project venvs are never
touched). The run prints which route fired.

How to run
----------
Default 26-scene diverse spread from the mosquito project into /tmp/kb_u2net::

    backend/venv/bin/python backend/tools/kb_target_probe_u2net.py

Point at other scenes / project / model / out dir::

    backend/venv/bin/python backend/tools/kb_target_probe_u2net.py \
        --scenes 2,7,8,13,20,30,39,44,55 \
        --project ~/Documents/Aqua/projects/<slug> \
        --model ~/Documents/Aqua/backend/models/u2netp.onnx \
        --out-dir /tmp/kb_u2net
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

# --- Paths -----------------------------------------------------------------------
THIS = Path(__file__).resolve()
BACKEND = THIS.parent.parent  # backend/
DEFAULT_MODEL = BACKEND / "models" / "u2netp.onnx"
MODEL_URL = "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2netp.onnx"

# --- Project / scene selection. Same DEFAULT_PROJECT the sibling KB tools use. ----
# A DIVERSE 26-scene spread across the 58-scene mosquito project. It INCLUDES the
# sibling brightness probe's 9 ids (2,7,8,13,20,30,39,44,55 -- notably the people
# shots 008 & 030 that brightness missed) so the two detectors can be compared
# scene-for-scene, plus ~17 more spaced across the whole project so we also see
# behavior on objects, wide establishing shots and crowds. -----------------------
DEFAULT_PROJECT = (
    Path.home()
    / "Documents/Aqua/projects/this-5-bucket-wiped-out-the-mosquitoes-in-my-yard"
)
DEFAULT_SCENES = [
    0, 2, 3, 5, 7, 8, 10, 13, 15, 18, 20, 23, 25, 28, 30,
    33, 36, 39, 40, 42, 44, 47, 50, 53, 55, 57,
]  # 26 total; the 9 brightness-probe ids are all present.

# --- U2-Netp I/O & preprocessing (matches the U2-Net repo / rembg exactly) --------
IN_SIZE = 320  # U2-Netp fixed input side
IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], np.float32)  # RGB
IMAGENET_STD = np.array([0.229, 0.224, 0.225], np.float32)   # RGB

# --- Mask / analysis thresholds (all on the [0,1] foreground-probability map) -----
MASK_THR = 0.5           # foreground = prob >= this (standard U2-Net cutoff)
MIN_BLOB_FRAC = 0.001    # ignore foreground specks < 0.1% of the frame (blob count)

# --- Clear-subject gate (OBSERVATIONAL, all tunable, all shown) -------------------
# TARGET requires ONE clear, confident, compact subject; anything weak / scattered
# / whole-frame / tiny falls to CENTER (a safe center zoom). These are first-pass
# guesses -- the per-image metrics are printed and drawn so they can be retuned.
COV_MIN = 0.01   # subject must cover >= 1% of the frame (else tiny/noise -> CENTER)
COV_MAX = 0.85   # foreground over >85% of frame = no distinct subject -> CENTER
CONF_MIN = 0.65  # mean probability inside the mask must be this confident
DOM_MIN = 0.60   # largest blob must hold >= 60% of all foreground (compact/single)

# --- Drawing ---------------------------------------------------------------------
HEAT_ALPHA = 0.45          # foreground-prob heatmap opacity over the still
C_CONTOUR = (255, 255, 0)  # cyan   -- mask contour (BGR)
C_ANCHOR = (0, 255, 255)   # yellow -- anchor crosshair
C_ANCHOR_OUT = (0, 0, 0)   # black outline behind the crosshair for contrast
MONT_TILE = 560            # montage cell size (px); per-image PNGs are full-res
MONT_COLS = 5
MONT_GAP = 10


# --- Detector loading / inference ------------------------------------------------
class U2NetDetector:
    """Loads u2netp once and returns a full-resolution [0,1] foreground-probability
    map per BGR image. Route is auto-probed: cv2.dnn first (verified to load AND
    run u2netp on the cv2 5.0 build here), else onnxruntime. Preprocessing is
    identical on both routes and matches U2-Net/rembg: resize 320, per-image
    max-scale, ImageNet mean/std, RGB, NCHW float32."""

    def __init__(self, model_path: Path):
        if not model_path.exists():
            raise SystemExit(
                f"model not found: {model_path}\n"
                f"  download it (one-time, free, ~4.6MB):\n"
                f"    curl -sL -o {model_path} {MODEL_URL}"
            )
        self.model_path = model_path
        self.route, self._fwd = self._load(model_path)

    @staticmethod
    def _load(model_path: Path):
        """Return (route_str, forward_fn) where forward_fn(blob_nchw)->(1,1,H,W)."""
        dnn_err = None
        # -- Route 1: cv2.dnn (no extra install; uses the venv's cv2). Verify it can
        #    both LOAD and RUN by forwarding a dummy -- some ONNX ops parse but fail
        #    at forward, and we want to fall through cleanly if so. -----------------
        try:
            net = cv2.dnn.readNetFromONNX(str(model_path))

            def fwd(blob):
                net.setInput(blob)
                return net.forward()

            fwd(np.zeros((1, 3, IN_SIZE, IN_SIZE), np.float32))  # runtime check
            return "cv2.dnn.readNetFromONNX", fwd
        except Exception as e:  # noqa: BLE001 -- fall through to onnxruntime
            dnn_err = e

        # -- Route 2: onnxruntime. Import from an isolated /tmp/kb/pylibs if that is
        #    where it was pip-installed with --target (project venvs untouched). ----
        try:
            pylibs = "/tmp/kb/pylibs"
            if pylibs not in sys.path:
                sys.path.insert(0, pylibs)
            import onnxruntime as ort  # noqa: PLC0415

            sess = ort.InferenceSession(
                str(model_path), providers=["CPUExecutionProvider"]
            )
            in_name = sess.get_inputs()[0].name
            out_name = sess.get_outputs()[0].name

            def fwd(blob):
                return sess.run([out_name], {in_name: blob})[0]

            return "onnxruntime.InferenceSession", fwd
        except Exception as ort_err:  # noqa: BLE001
            raise SystemExit(
                "could not load u2netp via cv2.dnn OR onnxruntime.\n"
                f"  cv2.dnn error : {type(dnn_err).__name__}: {str(dnn_err)[:200]}\n"
                f"  onnxruntime   : {type(ort_err).__name__}: {str(ort_err)[:200]}\n"
                "  to enable the fallback (isolated, does NOT touch the venv):\n"
                "    /Users/aidanmcomie/Documents/Aqua/backend/venv/bin/python -m pip \\\n"
                "      install --target /tmp/kb/pylibs onnxruntime"
            )

    def prob_map(self, bgr: np.ndarray) -> np.ndarray:
        """Full-res [0,1] foreground-probability map for a BGR still."""
        h, w = bgr.shape[:2]
        rgb = cv2.cvtColor(cv2.resize(bgr, (IN_SIZE, IN_SIZE)), cv2.COLOR_BGR2RGB)
        rgb = rgb.astype(np.float32)
        mx = float(rgb.max())
        rgb = rgb / (mx if mx > 0 else 1.0)          # U2-Net scales by per-image max
        rgb = (rgb - IMAGENET_MEAN) / IMAGENET_STD   # ImageNet mean/std, RGB order
        blob = rgb.transpose(2, 0, 1)[None].copy()   # NCHW float32
        out = self._fwd(blob)
        prob = np.asarray(out).reshape(out.shape[-2], out.shape[-1]).astype(np.float32)
        prob = np.clip(prob, 0.0, 1.0)
        return cv2.resize(prob, (w, h))


# --- Analysis --------------------------------------------------------------------
def analyze(prob: np.ndarray) -> dict:
    """Reduce the [0,1] foreground-probability map to the gate metrics + anchor.

    coverage   -- fraction of the frame above MASK_THR (how much is foreground).
    mean_conf  -- mean probability INSIDE that mask (how confident the foreground).
    dom        -- largest connected blob's share of total (kept) foreground area
                  (1.0 = a single blob, low = fragmented across many blobs).
    n_blob     -- number of foreground blobs above MIN_BLOB_FRAC.
    compact    -- dom / n_blob, a single "one tidy subject" scalar for tuning.
    anchor     -- probability-weighted centroid of the LARGEST blob, normalized.
    """
    h, w = prob.shape
    mask = (prob >= MASK_THR).astype(np.uint8)
    coverage = float(mask.mean())
    mean_conf = float(prob[mask.astype(bool)].mean()) if coverage > 0 else 0.0

    n_lab, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    min_area = MIN_BLOB_FRAC * h * w
    kept = [
        lab for lab in range(1, n_lab)
        if stats[lab, cv2.CC_STAT_AREA] >= min_area
    ]
    n_blob = len(kept)

    union = np.zeros((h, w), np.uint8)
    for lab in kept:
        union[labels == lab] = 255
    total_fg = float(sum(stats[lab, cv2.CC_STAT_AREA] for lab in kept))

    if kept:
        largest = max(kept, key=lambda lab: stats[lab, cv2.CC_STAT_AREA])
        dom = float(stats[largest, cv2.CC_STAT_AREA]) / max(1.0, total_fg)
        m = labels == largest
        xs, ys = np.meshgrid(np.arange(w), np.arange(h))
        wgt = prob * m
        wsum = float(wgt.sum())
        if wsum > 1e-9:
            cx = float((xs * wgt).sum() / wsum) / w
            cy = float((ys * wgt).sum() / wsum) / h
        else:  # degenerate: fall back to blob geometric center
            cx = (stats[largest, cv2.CC_STAT_LEFT] + stats[largest, cv2.CC_STAT_WIDTH] / 2) / w
            cy = (stats[largest, cv2.CC_STAT_TOP] + stats[largest, cv2.CC_STAT_HEIGHT] / 2) / h
        anchor = (float(np.clip(cx, 0, 1)), float(np.clip(cy, 0, 1)))
    else:
        dom = 0.0
        anchor = (0.5, 0.5)

    compact = dom / n_blob if n_blob else 0.0
    return {
        "h": h, "w": w, "mask": mask * 255, "union": union,
        "coverage": coverage, "mean_conf": mean_conf, "dom": dom,
        "n_blob": n_blob, "compact": compact, "anchor": anchor,
    }


def gate(a: dict) -> dict:
    """Clear-subject gate: TARGET (one clear, confident, compact subject -> zoom the
    anchor) vs CENTER (weak / scattered / whole-frame / tiny -> safe center zoom).
    Purely from the printed metrics; no face/person logic anywhere."""
    is_target = (
        COV_MIN <= a["coverage"] <= COV_MAX
        and a["mean_conf"] >= CONF_MIN
        and a["dom"] >= DOM_MIN
    )
    if is_target:
        return {"call": "TARGET", "anchor": a["anchor"]}
    return {"call": "CENTER", "anchor": (0.5, 0.5)}


# --- Drawing ---------------------------------------------------------------------
def _put_label(img: np.ndarray, lines: list[str], scale: float = 1.0) -> None:
    """Top-left multi-line label in a translucent black banner (mirrors the sibling
    kb_target_probe / kenburns_subpixel label style)."""
    font, thick, pad, gap = cv2.FONT_HERSHEY_SIMPLEX, 2, 14, 10
    sizes = [cv2.getTextSize(t, font, scale, thick)[0] for t in lines]
    tw = max(w for w, _ in sizes)
    th = max(h for _, h in sizes)
    x1, y1 = 18, 18
    x2 = x1 + tw + 2 * pad
    y2 = y1 + len(lines) * th + (len(lines) - 1) * gap + 2 * pad
    roi = img[y1:y2, x1:x2].astype(np.float32) * 0.40  # 60% black
    img[y1:y2, x1:x2] = roi.astype(np.uint8)
    y = y1 + pad + th
    for t in lines:
        cv2.putText(img, t, (x1 + pad, y), font, scale, (255, 255, 255),
                    thick, cv2.LINE_AA)
        y += th + gap


def _crosshair(img: np.ndarray, x: int, y: int, r: int) -> None:
    """Yellow crosshair (ring + cross) with a black outline so it reads anywhere."""
    for color, t in ((C_ANCHOR_OUT, 7), (C_ANCHOR, 3)):
        cv2.circle(img, (x, y), r, color, t, cv2.LINE_AA)
        cv2.line(img, (x - r - 12, y), (x + r + 12, y), color, t, cv2.LINE_AA)
        cv2.line(img, (x, y - r - 12), (x, y + r + 12), color, t, cv2.LINE_AA)


def draw_overlay(bgr: np.ndarray, prob: np.ndarray, a: dict, g: dict,
                 scene_id: int) -> np.ndarray:
    """Compose the per-image overlay: foreground-prob heatmap + mask contour +
    anchor crosshair + a label (gate call + all gate metrics). Full-res BGR."""
    h, w = a["h"], a["w"]
    heat = cv2.applyColorMap(np.clip(prob * 255, 0, 255).astype(np.uint8),
                             cv2.COLORMAP_INFERNO)
    img = cv2.addWeighted(bgr, 1.0 - HEAT_ALPHA, heat, HEAT_ALPHA, 0.0)

    if a["union"].any():
        contours, _ = cv2.findContours(a["union"], cv2.RETR_EXTERNAL,
                                       cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(img, contours, -1, C_CONTOUR, 2, cv2.LINE_AA)

    ax, ay = g["anchor"]
    px, py = int(ax * w), int(ay * h)
    _crosshair(img, px, py, int(0.035 * min(h, w)))

    l1 = f"scene_{scene_id:03d}   {g['call']}   det=u2netp"
    l2 = (f"cov={a['coverage']:.3f}  conf={a['mean_conf']:.2f}  dom={a['dom']:.2f}  "
          f"nblob={a['n_blob']}  compact={a['compact']:.2f}")
    _put_label(img, [l1, l2], scale=max(0.8, w / 1024.0))
    return img


def build_montage(overlays: list[tuple[int, np.ndarray]], out_path: Path) -> None:
    """Tile the per-image overlays into one readable, multi-row montage with a
    short legend along the bottom."""
    n = len(overlays)
    cols = MONT_COLS
    rows = (n + cols - 1) // cols
    cell = MONT_TILE
    legend_h = 46
    W = cols * cell + (cols + 1) * MONT_GAP
    H = rows * cell + (rows + 1) * MONT_GAP + legend_h
    canvas = np.full((H, W, 3), 22, np.uint8)
    for i, (_sid, ov) in enumerate(overlays):
        tile = cv2.resize(ov, (cell, cell))
        r, c = divmod(i, cols)
        y = MONT_GAP + r * (cell + MONT_GAP)
        x = MONT_GAP + c * (cell + MONT_GAP)
        canvas[y:y + cell, x:x + cell] = tile
    cv2.putText(
        canvas,
        "heatmap=U2-Net foreground prob   cyan=mask contour   yellow crosshair=KB "
        "anchor   TARGET=zoom subject / CENTER=safe center zoom",
        (MONT_GAP, H - 16), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (210, 210, 210), 2,
        cv2.LINE_AA,
    )
    cv2.imwrite(str(out_path), canvas)


# --- Main ------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(
        description="Free local SEMANTIC (U2-Netp) Ken Burns auto-target probe."
    )
    ap.add_argument("--project", default=str(DEFAULT_PROJECT))
    ap.add_argument("--out-dir", default="/tmp/kb_u2net")
    ap.add_argument("--model", default=str(DEFAULT_MODEL))
    ap.add_argument("--scenes", default=",".join(str(s) for s in DEFAULT_SCENES),
                    help="comma-separated scene ids to probe")
    args = ap.parse_args()

    project = Path(args.project).expanduser()
    footage_dir = project / "footage"
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    scene_ids = [int(s) for s in args.scenes.split(",") if s.strip() != ""]

    det = U2NetDetector(Path(args.model).expanduser())

    print("=== U2-Netp semantic target probe ===")
    print(f"  cv2 version   : {cv2.__version__}")
    print(f"  numpy version : {np.__version__}")
    print(f"  model         : {det.model_path}")
    print(f"  model source  : {MODEL_URL}")
    print(f"  route         : {det.route}")
    print(f"  gate          : TARGET if {COV_MIN} <= cov <= {COV_MAX} and "
          f"conf >= {CONF_MIN} and dom >= {DOM_MIN}  (all tunable)")
    print(f"  project       : {project}")
    print(f"  out dir       : {out_dir}")
    print(f"  scenes ({len(scene_ids)})  : {scene_ids}\n")

    overlays: list[tuple[int, np.ndarray]] = []
    rows: list[dict] = []
    for sid in scene_ids:
        png = footage_dir / f"scene_{sid:03d}.png"
        if not png.exists():
            print(f"  scene_{sid:03d}: MISSING ({png}) -- skipped")
            continue
        bgr = cv2.imread(str(png), cv2.IMREAD_COLOR)
        if bgr is None:
            print(f"  scene_{sid:03d}: unreadable -- skipped")
            continue

        prob = det.prob_map(bgr)
        a = analyze(prob)
        g = gate(a)

        ov = draw_overlay(bgr, prob, a, g, sid)
        per_path = out_dir / f"scene_{sid:03d}_overlay.png"
        cv2.imwrite(str(per_path), ov)
        overlays.append((sid, ov))

        ax, ay = g["anchor"]
        rows.append({"sid": sid, "call": g["call"], "ax": ax, "ay": ay,
                     "cov": a["coverage"], "conf": a["mean_conf"], "dom": a["dom"],
                     "n": a["n_blob"], "compact": a["compact"], "path": per_path})

    if not overlays:
        raise SystemExit(f"no readable stills among {scene_ids} under {footage_dir}")

    montage_path = out_dir / "montage.png"
    build_montage(overlays, montage_path)

    # --- Report ------------------------------------------------------------------
    print("=== per-image results ===")
    hdr = (f"  {'scene':>7} {'gate':>7} {'anchor(x,y)':>13} {'cov':>6} "
           f"{'conf':>5} {'dom':>5} {'nblob':>5} {'compact':>7}")
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))
    for r in rows:
        print(f"  {('s%03d' % r['sid']):>7} {r['call']:>7} "
              f"{('(%.2f,%.2f)' % (r['ax'], r['ay'])):>13} "
              f"{r['cov']:>6.3f} {r['conf']:>5.2f} {r['dom']:>5.2f} "
              f"{r['n']:>5} {r['compact']:>7.2f}")

    n_target = sum(1 for r in rows if r["call"] == "TARGET")
    print(f"\n  gate summary: {n_target} TARGET / {len(rows) - n_target} CENTER "
          f"of {len(rows)}")

    print("\n=== outputs ===")
    for r in rows:
        print(f"  {r['path']}")
    print(f"  montage: {montage_path}")

    print("\nno generation / API / paid calls -- local U2-Netp (one-time model "
          "download) + OpenCV/numpy on existing PNG stills only.")
    print("observational: raw detector + confidence gate; NO face/person rules.")


if __name__ == "__main__":
    main()
