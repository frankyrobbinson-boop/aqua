#!/usr/bin/env python3
"""kb_target_probe.py -- FREE feasibility probe: can we auto-target Ken Burns?

Why this exists
---------------
The prototype/shipping Ken Burns move (``kenburns_compare.kb_chain`` /
``kenburns_subpixel``) always zooms toward the FRAME CENTER, or toward a focal
point a human picked by hand. Before we build "no manual targeting" -- pick the
zoom/pan anchor automatically per still -- we need to know whether cheap, LOCAL
computer vision actually lands on the real subject (the flower / bucket / person)
on OUR AI-generated stills, or wanders off into the background.

This tool answers exactly that, spending nothing. For a diverse spread of the
mosquito project's AI stills it:

  1. picks a Ken Burns ANCHOR (where to zoom toward), layered:
       a. FACE  -- Haar cascade from ``cv2.data.haarcascades`` (or a cv2.dnn /
          FaceDetectorYN model) IF the build ships one. On the probe build here it
          does not (see the backend probe printed at run time), so this layer is a
          graceful no-op and we fall through.
       b. SALIENCY -- ``cv2.saliency`` (opencv-contrib) if present, ELSE a
          spectral-residual saliency map implemented directly in numpy (Hou &
          Zhang 2007: FFT -> log-amplitude -> subtract mean-filtered log-amplitude
          -> inverse FFT -> blur -> normalize). Anchor = saliency-weighted centroid
          of the dominant thresholded blob.
       c. CENTER -- safe fallback when nothing is confident.
  2. classifies the MOVE from the saliency map's shape:
       ZOOM   -- one compact salient blob -> push toward the anchor.
       PAN    -- saliency spread WIDE horizontally / multi-modal (a wide
                 establishing shot) -> reports span + direction + destination.
       CENTER -- diffuse / low peak-to-mean ratio (no clear subject) -> safe zoom
                 on frame center.
  3. draws a per-image overlay -- saliency heatmap + salient-region contour +
     anchor crosshair + label (move / confidence / which detector fired), plus a
     pan-path arrow on PAN shots -- and tiles all of them into one montage a human
     can eyeball to judge whether the anchors land on the actual subjects.

It reads only PNG stills that already exist on disk and writes only PNGs to
``--out-dir``. No script/scene/outline/TTS/image generation, no API, no paid or
network calls: pure local OpenCV + numpy. Nothing is written into any project.

Backend note
------------
Run it with the cv2-equipped interpreter::

    backend/venv/bin/python backend/tools/kb_target_probe.py

That venv carries cv2 5.0.0 + numpy. It is a SLIM build: no ``cv2.saliency``
(contrib), no ``cv2.CascadeClassifier`` and no bundled Haar XML -- so the face
layer is unavailable and saliency runs through the numpy spectral-residual
fallback. The tool PROBES and prints this at start so the result is self-describing
on any build; on a fuller build it would light up the contrib/Haar paths
automatically.

How to run
----------
Default 9-scene diverse spread from the mosquito project into /tmp/kb_targets::

    backend/venv/bin/python backend/tools/kb_target_probe.py

Point at other scenes / project / out dir::

    backend/venv/bin/python backend/tools/kb_target_probe.py \
        --scenes 2,7,8,13,20,30,39,44,55 \
        --project ~/Documents/Aqua/projects/<slug> --out-dir /tmp/kb_targets
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

import cv2
import numpy as np

# --- Project / scene selection. Same DEFAULT_PROJECT the sibling KB tools use.
# The default scene ids are a hand-picked DIVERSE spread across the 58-scene
# mosquito project (verified on a contact sheet): macro subjects, buckets/objects,
# people, and wide garden/pond establishing shots -- so the probe is stressed on
# every shot type, not just easy centered close-ups. ----------------------------
DEFAULT_PROJECT = (
    Path.home()
    / "Documents/Aqua/projects/this-5-bucket-wiped-out-the-mosquitoes-in-my-yard"
)
DEFAULT_SCENES = [2, 7, 8, 13, 20, 30, 39, 44, 55]
# 002 white-rose macro | 007 bucket close | 008 person at microscope
# 013 person pouring bucket | 020 wide garden | 030 person in garden
# 039 frog on grass | 044 pond / lily pads (wide) | 055 people at a table

# --- Spectral-residual saliency. Hou & Zhang operate on a small canvas (~64px);
# the residual + reconstruction there give a coarse but robust "what pops" map. --
SAL_SIZE = 64  # side length the still is resized to for the FFT saliency pass
SR_MEAN_KSIZE = 3  # box filter over the log-amplitude spectrum (the "residual")
SR_SMOOTH_SIGMA = 1.5  # Gaussian smoothing of the reconstructed map (in SAL_SIZE px)

# --- Analysis thresholds (all on the [0,1]-normalized saliency map) --------------
# The salient MASK is everything above mean + SAL_STD_K*std. This adapts to each
# map: on a peaked map it isolates a compact core; on a diffuse one it grabs only
# scattered noise (filtered out by MIN_BLOB_FRAC) -> no subject -> CENTER. (Otsu
# was tried first but split diffuse maps near their middle, swallowing ~half the
# frame and making every span read as ~1.0.) --------------------------------------
SAL_STD_K = 2.0  # salient = saliency >= mean + SAL_STD_K * std
MIN_BLOB_FRAC = 0.004  # ignore salient components smaller than 0.4% of the frame
PMR_DIFFUSE = 4.0  # peak/mean below this => no clear subject => CENTER (safe)
PMR_STRONG = 12.0  # peak/mean at/above this => full confidence (for the 0..1 conf)
# PAN needs genuine multi-modality -- a SECOND strong, horizontally-SEPARATED blob
# (a wide establishing shot with subjects on both sides), not merely a wide union
# span. Union span alone misfired PAN on single textured subjects (e.g. a rose
# whose petal highlights scatter across the frame but centre on one flower). ------
PAN_SEP_MIN = 0.33  # 2nd blob this far from the primary in x (frac width) = separated
PAN_SECOND_FRAC = 0.55  # ...and holding >= this fraction of the primary blob's strength
SPAN_VERYWIDE = 0.85  # a single blob spanning >= this much width also reads as PAN

# --- Face detection gate ---------------------------------------------------------
FACE_MIN_FRAC = 0.03  # a detected face must span >=3% of min(H,W) to be trusted

# --- Drawing ---------------------------------------------------------------------
HEAT_ALPHA = 0.45  # saliency heatmap opacity over the still
C_CONTOUR = (255, 255, 0)  # cyan   -- salient-region outline (BGR)
C_ANCHOR = (0, 255, 255)  # yellow -- anchor crosshair
C_ANCHOR_OUT = (0, 0, 0)  # black outline behind the crosshair for contrast
C_PAN = (0, 200, 255)  # orange -- suggested pan path
C_FACE = (0, 255, 0)  # green  -- face box (only if a face fires)
MONT_TILE = 600  # montage cell size (px); per-image PNGs are saved full-res
MONT_COLS = 3
MONT_GAP = 10


# --- Backend probe ---------------------------------------------------------------
def probe_backends() -> dict:
    """Report which CV backends this cv2 build actually offers, so the run is
    self-describing: contrib saliency, dnn, a usable Haar frontal-face cascade, and
    the FaceDetectorYN/CascadeClassifier classes. Returns a dict the rest of the
    tool reads to decide which anchor backends to light up."""
    info: dict = {}

    # opencv-contrib StaticSaliency*.
    sal = getattr(cv2, "saliency", None)
    info["saliency_contrib"] = sal is not None and (
        hasattr(sal, "StaticSaliencyFineGrained_create")
        or hasattr(sal, "StaticSaliencySpectralResidual_create")
    )

    info["dnn"] = hasattr(cv2, "dnn")
    info["FaceDetectorYN"] = hasattr(cv2, "FaceDetectorYN")
    info["CascadeClassifier"] = hasattr(cv2, "CascadeClassifier")

    # A usable Haar frontal-face cascade needs BOTH the class and the XML on disk.
    haar_dir = getattr(getattr(cv2, "data", None), "haarcascades", None)
    haar_xml = None
    if haar_dir:
        cand = os.path.join(haar_dir, "haarcascade_frontalface_default.xml")
        if os.path.exists(cand):
            haar_xml = cand
    info["haar_dir"] = haar_dir
    info["haar_xml"] = haar_xml
    info["haar_usable"] = bool(haar_xml) and info["CascadeClassifier"]

    if info["saliency_contrib"]:
        info["saliency_path"] = "cv2.saliency (opencv-contrib StaticSaliency)"
    else:
        info["saliency_path"] = "numpy spectral-residual (Hou & Zhang) fallback"
    info["face_backend"] = "haar" if info["haar_usable"] else "unavailable"

    print("=== cv2 backend probe ===")
    print(f"  cv2 version           : {cv2.__version__}")
    print(f"  numpy version         : {np.__version__}")
    print(f"  cv2.saliency (contrib): {'YES' if info['saliency_contrib'] else 'no'}")
    print(f"  cv2.dnn               : {'YES' if info['dnn'] else 'no'}")
    print(f"  cv2.FaceDetectorYN    : {'YES' if info['FaceDetectorYN'] else 'no'}"
          " (needs an ONNX model we don't ship -> not used)")
    print(f"  cv2.CascadeClassifier : {'YES' if info['CascadeClassifier'] else 'no'}")
    print(f"  haarcascades dir      : {info['haar_dir']}")
    print(f"  frontalface XML       : {info['haar_xml'] or 'MISSING'}")
    print(f"  -> saliency path      : {info['saliency_path']}")
    print(f"  -> face backend       : {info['face_backend']}")
    print()
    return info


# --- Anchor layer (a): face ------------------------------------------------------
def detect_face(bgr: np.ndarray, info: dict):
    """Layer (a). Return (x, y, wfrac) with the largest confident face center in
    normalized [0,1] coords, or None. Defensive: on a build with no Haar class /
    XML (this one) it simply returns None and the caller falls through to saliency.
    Written so a fuller build lights this up with no other change."""
    if not info.get("haar_usable"):
        return None
    try:
        cascade = cv2.CascadeClassifier(info["haar_xml"])
        if cascade.empty():
            return None
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape
        min_side = int(FACE_MIN_FRAC * min(h, w))
        faces = cascade.detectMultiScale(
            gray, scaleFactor=1.1, minNeighbors=5,
            minSize=(min_side, min_side),
        )
        if len(faces) == 0:
            return None
        fx, fy, fw, fh = max(faces, key=lambda r: r[2] * r[3])  # largest
        return ((fx + fw / 2) / w, (fy + fh / 2) / h, fw / w)
    except Exception:  # noqa: BLE001 -- a probe must never crash on a face path
        return None


# --- Anchor layer (b): saliency --------------------------------------------------
def spectral_residual_saliency(gray: np.ndarray, out_hw: tuple[int, int]) -> np.ndarray:
    """Hou & Zhang spectral-residual saliency, pure numpy FFT (used when
    opencv-contrib ``cv2.saliency`` is absent). Steps: resize to SAL_SIZE ->
    2-D FFT -> log-amplitude L and phase P -> spectral residual R = L - meanfilt(L)
    -> reconstruct S = |IFFT(exp(R + iP))|^2 -> Gaussian blur -> min-max normalize
    -> resize back to the original frame. Returns a float32 map in [0,1]."""
    small = cv2.resize(gray, (SAL_SIZE, SAL_SIZE)).astype(np.float32)
    f = np.fft.fft2(small)
    log_amp = np.log(np.abs(f) + 1e-8)
    phase = np.angle(f)
    mean_log = cv2.blur(log_amp, (SR_MEAN_KSIZE, SR_MEAN_KSIZE))
    residual = log_amp - mean_log
    recon = np.fft.ifft2(np.exp(residual + 1j * phase))
    sal = np.abs(recon) ** 2
    sal = cv2.GaussianBlur(sal, (0, 0), SR_SMOOTH_SIGMA)
    sal -= sal.min()
    peak = sal.max()
    if peak > 1e-12:
        sal /= peak
    h, w = out_hw
    return cv2.resize(sal.astype(np.float32), (w, h))


def contrib_saliency(bgr: np.ndarray) -> np.ndarray:
    """opencv-contrib StaticSaliency path (fine-grained preferred, spectral-residual
    otherwise), normalized to [0,1]. Only reached when ``cv2.saliency`` exists."""
    sal = cv2.saliency
    algo = (
        sal.StaticSaliencyFineGrained_create()
        if hasattr(sal, "StaticSaliencyFineGrained_create")
        else sal.StaticSaliencySpectralResidual_create()
    )
    ok, m = algo.computeSaliency(bgr)
    if not ok:
        raise RuntimeError("contrib computeSaliency failed")
    m = m.astype(np.float32)
    m -= m.min()
    if m.max() > 1e-12:
        m /= m.max()
    return m


def saliency_map(bgr: np.ndarray, gray: np.ndarray, info: dict) -> np.ndarray:
    """Dispatch to contrib saliency if available, else the numpy fallback."""
    if info.get("saliency_contrib"):
        try:
            return contrib_saliency(bgr)
        except Exception:  # noqa: BLE001 -- fall back rather than fail the run
            pass
    return spectral_residual_saliency(gray, gray.shape[:2])


def analyze_saliency(sal: np.ndarray) -> dict:
    """Reduce a [0,1] saliency map to the numbers the classifier + drawing need:
    peak-to-mean ratio (is there a subject at all?), the thresholded salient mask
    and its connected components (compactness / multi-modality), the horizontal
    span, and the saliency-weighted centroid of the DOMINANT blob (the anchor)."""
    h, w = sal.shape
    smean = float(sal.mean())
    sstd = float(sal.std())
    speak = float(np.percentile(sal, 99.5))  # robust "peak" (not a lone hot pixel)
    pmr = speak / (smean + 1e-6)

    # Salient mask = above mean + K*std (adaptive; see SAL_STD_K note up top).
    thr = smean + SAL_STD_K * sstd
    mask = (sal >= thr).astype(np.uint8) * 255

    n_lab, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    min_area = MIN_BLOB_FRAC * h * w
    xs, ys = np.meshgrid(np.arange(w), np.arange(h))

    comps = []  # (strength, cx, cy, x0, y0, bw, bh, area, label)
    for lab in range(1, n_lab):
        area = int(stats[lab, cv2.CC_STAT_AREA])
        if area < min_area:
            continue
        m = labels == lab
        wsum = float(sal[m].sum())
        if wsum <= 1e-9:
            continue
        cx = float((xs[m] * sal[m]).sum() / wsum)
        cy = float((ys[m] * sal[m]).sum() / wsum)
        comps.append({
            "strength": wsum, "cx": cx, "cy": cy,
            "x0": int(stats[lab, cv2.CC_STAT_LEFT]),
            "y0": int(stats[lab, cv2.CC_STAT_TOP]),
            "bw": int(stats[lab, cv2.CC_STAT_WIDTH]),
            "bh": int(stats[lab, cv2.CC_STAT_HEIGHT]),
            "area": area, "label": lab,
        })

    comps.sort(key=lambda c: c["strength"], reverse=True)

    if comps:
        union = np.zeros((h, w), np.uint8)
        for c in comps:
            union[labels == c["label"]] = 255
        col_any = union.any(axis=0)
        cols = np.where(col_any)[0]
        span_x = float((cols.max() - cols.min() + 1) / w) if cols.size else 0.0
        primary = comps[0]
        compactness = primary["area"] / max(1, primary["bw"] * primary["bh"])
        coverage = float((union > 0).sum()) / (h * w)
    else:
        union = np.zeros((h, w), np.uint8)
        span_x, compactness, coverage = 0.0, 0.0, 0.0
        primary = None

    return {
        "h": h, "w": w, "pmr": pmr, "mean": smean, "peak": speak,
        "mask": mask, "labels": labels, "union": union,
        "comps": comps, "primary": primary, "n_comp": len(comps),
        "span_x": span_x, "compactness": compactness, "coverage": coverage,
    }


# --- Move classification ---------------------------------------------------------
def classify_move(a: dict) -> dict:
    """Decide the move + anchor from the saliency analysis.

    ZOOM   -- a confident, reasonably compact single subject: push toward it.
    PAN    -- confident but spread WIDE horizontally / multi-modal (establishing
              shot): report span, direction and the destination (strongest blob).
    CENTER -- peak-to-mean below PMR_DIFFUSE (no subject stands out): safe center.

    Anchor is normalized [0,1]. ``conf`` maps peak/mean onto 0..1 between
    PMR_DIFFUSE and PMR_STRONG; ``compactness`` is reported alongside as the
    secondary signal. detector = which layer set the anchor."""
    pmr = a["pmr"]
    conf = float(np.clip((pmr - PMR_DIFFUSE) / (PMR_STRONG - PMR_DIFFUSE), 0.0, 1.0))
    out = {"conf": conf, "pmr": pmr, "compactness": a["compactness"],
           "span_x": a["span_x"], "n_comp": a["n_comp"],
           "pan": None, "detector": "saliency"}

    if a["primary"] is None or pmr < PMR_DIFFUSE:
        out.update(move="CENTER", detector="center", anchor=(0.5, 0.5))
        return out

    primary = a["primary"]
    dest = (primary["cx"] / a["w"], primary["cy"] / a["h"])
    # Multi-modal = a second strong blob, horizontally separated from the primary.
    multimodal = any(
        c["strength"] >= PAN_SECOND_FRAC * primary["strength"]
        and abs(c["cx"] - primary["cx"]) / a["w"] >= PAN_SEP_MIN
        for c in a["comps"][1:]
    )
    wide = multimodal or a["span_x"] >= SPAN_VERYWIDE

    if wide:
        direction = "right" if dest[0] >= 0.5 else "left"
        start_x = float(np.clip(1.0 - dest[0], 0.0, 1.0))  # opposite side
        out.update(
            move="PAN", anchor=dest,
            pan={"dest": dest, "direction": direction,
                 "span_x": a["span_x"], "start": (start_x, dest[1])},
        )
        return out

    out.update(move="ZOOM", anchor=dest)
    return out


# --- Drawing ---------------------------------------------------------------------
def _put_label(img: np.ndarray, lines: list[str], scale: float = 1.0) -> None:
    """Top-left multi-line label in a translucent black banner (mirrors the
    cv2.putText label the sibling kenburns_subpixel tool burns into frames)."""
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
    """A yellow crosshair (ring + cross) with a black outline behind it so it
    reads on any background."""
    for color, t in ((C_ANCHOR_OUT, 7), (C_ANCHOR, 3)):
        cv2.circle(img, (x, y), r, color, t, cv2.LINE_AA)
        cv2.line(img, (x - r - 12, y), (x + r + 12, y), color, t, cv2.LINE_AA)
        cv2.line(img, (x, y - r - 12), (x, y + r + 12), color, t, cv2.LINE_AA)


def draw_overlay(bgr: np.ndarray, sal: np.ndarray, a: dict, cls: dict,
                 scene_id: int, face) -> np.ndarray:
    """Compose the per-image overlay: heatmap + salient-region contour + anchor
    crosshair (+ pan arrow / face box) + a text label stating move, confidence and
    which detector fired. Returns a full-resolution BGR image."""
    h, w = a["h"], a["w"]
    heat = cv2.applyColorMap(np.clip(sal * 255, 0, 255).astype(np.uint8),
                             cv2.COLORMAP_INFERNO)
    img = cv2.addWeighted(bgr, 1.0 - HEAT_ALPHA, heat, HEAT_ALPHA, 0.0)

    # Outline the thresholded salient region(s).
    if a["union"].any():
        contours, _ = cv2.findContours(a["union"], cv2.RETR_EXTERNAL,
                                       cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(img, contours, -1, C_CONTOUR, 2, cv2.LINE_AA)

    ax, ay = cls["anchor"]
    px, py = int(ax * w), int(ay * h)
    r = int(0.035 * min(h, w))

    if cls["move"] == "PAN" and cls["pan"]:
        sx, sy = cls["pan"]["start"]
        cv2.arrowedLine(img, (int(sx * w), int(sy * h)), (px, py), C_PAN, 5,
                        cv2.LINE_AA, tipLength=0.06)

    if face is not None:
        fx, fy, wfrac = face
        fw = int(wfrac * w)
        cv2.rectangle(img, (int(fx * w - fw / 2), int(fy * h - fw / 2)),
                      (int(fx * w + fw / 2), int(fy * h + fw / 2)), C_FACE, 3)

    _crosshair(img, px, py, r)

    det = cls["detector"]
    l1 = f"scene_{scene_id:03d}   {cls['move']}   det={det}"
    l2 = (f"pmr={cls['pmr']:.1f}  comp={cls['compactness']:.2f}  "
          f"conf={cls['conf']:.2f}  span={cls['span_x']:.2f}  n={cls['n_comp']}")
    lines = [l1, l2]
    if cls["move"] == "PAN" and cls["pan"]:
        lines.append(f"PAN {cls['pan']['direction']}  "
                     f"dest=({cls['pan']['dest'][0]:.2f},{cls['pan']['dest'][1]:.2f})")
    _put_label(img, lines, scale=max(0.8, w / 1024.0))
    return img


def build_montage(overlays: list[tuple[int, np.ndarray]], out_path: Path) -> None:
    """Tile the per-image overlays into one montage at readable size, with a short
    legend along the bottom explaining the marks."""
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
        "heatmap=saliency  cyan=salient region  yellow crosshair=KB anchor  "
        "orange arrow=pan path",
        (MONT_GAP, H - 16), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (210, 210, 210), 2,
        cv2.LINE_AA,
    )
    cv2.imwrite(str(out_path), canvas)


# --- Main ------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description="Free local Ken Burns auto-target probe.")
    ap.add_argument("--project", default=str(DEFAULT_PROJECT))
    ap.add_argument("--out-dir", default="/tmp/kb_targets")
    ap.add_argument("--scenes", default=",".join(str(s) for s in DEFAULT_SCENES),
                    help="comma-separated scene ids to probe")
    args = ap.parse_args()

    project = Path(args.project).expanduser()
    footage_dir = project / "footage"
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    scene_ids = [int(s) for s in args.scenes.split(",") if s.strip() != ""]

    info = probe_backends()

    print(f"project : {project}")
    print(f"out dir : {out_dir}")
    print(f"scenes  : {scene_ids}\n")

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
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

        face = detect_face(bgr, info)
        sal = saliency_map(bgr, gray, info)
        a = analyze_saliency(sal)
        cls = classify_move(a)

        if face is not None:  # layer (a) wins if a confident face fired
            cls["detector"] = "face"
            cls["move"] = "ZOOM"
            cls["anchor"] = (face[0], face[1])
            cls["pan"] = None

        ov = draw_overlay(bgr, sal, a, cls, sid, face)
        per_path = out_dir / f"scene_{sid:03d}_overlay.png"
        cv2.imwrite(str(per_path), ov)
        overlays.append((sid, ov))

        ax, ay = cls["anchor"]
        rows.append({"sid": sid, "det": cls["detector"], "move": cls["move"],
                     "ax": ax, "ay": ay, "conf": cls["conf"], "pmr": cls["pmr"],
                     "comp": cls["compactness"], "span": cls["span_x"],
                     "n": cls["n_comp"], "path": per_path})

    if not overlays:
        raise SystemExit(f"no readable stills among {scene_ids} under {footage_dir}")

    montage_path = out_dir / "montage.png"
    build_montage(overlays, montage_path)

    # --- Report ------------------------------------------------------------------
    print("=== per-image results ===")
    hdr = (f"  {'scene':>7} {'detector':>9} {'move':>7} {'anchor(x,y)':>13} "
           f"{'conf':>5} {'pmr':>6} {'comp':>5} {'span':>5} {'n':>2}")
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))
    for r in rows:
        print(f"  {('s%03d' % r['sid']):>7} {r['det']:>9} {r['move']:>7} "
              f"{('(%.2f,%.2f)' % (r['ax'], r['ay'])):>13} "
              f"{r['conf']:>5.2f} {r['pmr']:>6.1f} {r['comp']:>5.2f} "
              f"{r['span']:>5.2f} {r['n']:>2}")

    print("\n=== outputs ===")
    for r in rows:
        print(f"  {r['path']}")
    print(f"  montage: {montage_path}")

    print("\nno generation / API / paid calls -- local OpenCV + numpy on existing "
          "PNG stills only")


if __name__ == "__main__":
    main()
