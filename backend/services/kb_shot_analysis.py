"""kb_shot_analysis.py -- reusable SEMANTIC shot analysis for Ken Burns targeting.

Why this exists
---------------
``services/kb_camera`` computes ONE continuous ping-pong zoom shared across a run
of stills; it carries a per-scene ``anchor`` so a future auto-target can aim the
zoom at the subject instead of always pushing the frame centre. This module is
that auto-target: given a still, it returns WHERE to aim (the subject anchor) plus
a GATE that says whether the still even has one clear subject to aim at.

The detector logic is ported verbatim from the proven FREE probe
``tools/kb_target_probe_u2net.py`` (same U2-Netp network, same faithful ImageNet
preprocessing, same largest-blob centroid, same clear-subject gate thresholds), so
what the harness saw in that probe is exactly what this module produces. Two things
are ADDED on top of the raw probe:

  1. an EDGE-MARGIN CLAMP that keeps the returned anchor in the INTERIOR of the
     visible 16:9 delivery frame, so the zoom can never aim at a subject that the
     base-fill crop has pushed off-screen (and so a subject hugging an edge is not
     jammed against it); and
  2. a tiny per-image CACHE sidecar keyed on the still's path + mtime, so re-runs
     of the harness are instant and deterministic.

It reads PNG stills that already exist on disk and (optionally) writes a small
JSON sidecar next to each. No script/scene/outline/TTS/image generation, no paid
API, no network at run time (the model is a one-time local download).

Status: NOT wired into the pipeline (``assembly_service`` etc.). The offline
Ken Burns harness imports it; the pipeline does not -- yet.

Model
-----
U2-Netp ONNX (~4.6MB), the lite salient-object model behind rembg's background
removal, at ``backend/models/u2netp.onnx`` (git-ignored blob). Inference route is
auto-probed exactly as the probe does: ``cv2.dnn.readNetFromONNX`` first (loads AND
runs u2netp on the cv2 5.0 build here), else an ``onnxruntime`` fallback.

    https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2netp.onnx
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np

# --- Paths -----------------------------------------------------------------------
THIS = Path(__file__).resolve()
BACKEND = THIS.parent.parent  # backend/
DEFAULT_MODEL = BACKEND / "models" / "u2netp.onnx"
MODEL_URL = "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2netp.onnx"

# --- Delivery canvas -------------------------------------------------------------
# Matches the pipeline (assembly_service OUT_W/OUT_H) and the KB tools. Used ONLY
# to derive the visible 16:9 band for the edge-margin clamp; the module renders
# nothing.
OUT_W, OUT_H = 1920, 1080

# --- U2-Netp I/O & preprocessing (identical to kb_target_probe_u2net / rembg) -----
IN_SIZE = 320  # U2-Netp fixed input side
IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], np.float32)  # RGB
IMAGENET_STD = np.array([0.229, 0.224, 0.225], np.float32)   # RGB

# --- Mask / analysis thresholds (on the [0,1] foreground-probability map) ---------
MASK_THR = 0.5           # foreground = prob >= this (standard U2-Net cutoff)
MIN_BLOB_FRAC = 0.001    # ignore foreground specks < 0.1% of the frame

# --- Clear-subject gate (SAME first-pass thresholds the probe used) ---------------
# TARGET requires ONE clear, confident, compact subject; anything weak / scattered
# / whole-frame / tiny falls to CENTER (a safe centre zoom).
COV_MIN = 0.01   # subject must cover >= 1% of the frame (else tiny/noise -> CENTER)
COV_MAX = 0.85   # foreground over >85% of frame = no distinct subject -> CENTER
CONF_MIN = 0.65  # mean probability inside the mask must be this confident
DOM_MIN = 0.60   # largest blob must hold >= 60% of all foreground (compact/single)

# --- Move classification (zoom / pan / center) -----------------------------------
# On top of the target/center gate, decide HOW to move on a still, purely from the
# same U2-Netp mask (no manual assignment):
#   center -- no aimable subject (tiny / whole-frame / low-confidence foreground);
#   pan    -- a WIDE subject (its salient union spans a large fraction of the frame
#             width) OR a MULTI subject (>= 2 significant blobs spread horizontally)
#             -> glide the focal point ACROSS to the subject;
#   zoom   -- otherwise, a single compact confident subject -> the fixed-anchor zoom.
# All thresholds are first-pass guesses, tunable here.
PAN_EXTENT_MIN = 0.50     # salient union spanning >= this fraction of width -> WIDE
PAN_BLOB_MIN_FRAC = 0.01  # a blob >= 1% of the frame counts as a distinct subject
PAN_MIN_BLOBS = 2         # >= this many significant blobs ...
PAN_SPREAD_MIN = 0.22     # ... whose centroids span >= this fraction of width -> MULTI
PAN_FROM_OFFSET = 0.32    # pan start offset from the subject toward the opposite side

# --- Edge-margin clamp -----------------------------------------------------------
# Keep the anchor at least this fraction of each axis's VISIBLE span away from the
# visible frame edge. Horizontally the whole [0,1] source width shows (square ->
# 16:9 fill is width-driven), so this is a plain [0.14, 0.86] framing margin.
# Vertically only the centre band of the source survives the fill (top/bottom are
# cropped), so the clamp both keeps the anchor off the visible edge AND guarantees
# it never lands in the cropped-off region. For a 1024^2 source into 1920x1080 the
# visible band is ~[0.219, 0.781]; clamped it becomes ~[0.298, 0.702].
EDGE_MARGIN_FRAC = 0.14

# --- Cache -----------------------------------------------------------------------
CACHE_SUFFIX = ".kbshot.json"  # sidecar next to the still, e.g. scene_005.png.kbshot.json
CACHE_SCHEMA = 2  # bumped when the analysis schema changed (added move/pan fields)


# --- Detector loading / inference (ported verbatim from kb_target_probe_u2net) ----
class U2NetDetector:
    """Loads u2netp once and returns a full-resolution [0,1] foreground-probability
    map per BGR image. Route is auto-probed: cv2.dnn first (verified to load AND
    run u2netp on the cv2 5.0 build here), else onnxruntime. Preprocessing is
    identical on both routes and matches U2-Net/rembg: resize 320, per-image
    max-scale, ImageNet mean/std, RGB, NCHW float32."""

    def __init__(self, model_path: Path):
        if not model_path.exists():
            raise FileNotFoundError(
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
        # -- Route 1: cv2.dnn (no extra install; uses the caller's cv2). Verify it
        #    can both LOAD and RUN by forwarding a dummy -- some ONNX ops parse but
        #    fail at forward, and we want to fall through cleanly if so. ------------
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
            raise RuntimeError(
                "could not load u2netp via cv2.dnn OR onnxruntime.\n"
                f"  cv2.dnn error : {type(dnn_err).__name__}: {str(dnn_err)[:200]}\n"
                f"  onnxruntime   : {type(ort_err).__name__}: {str(ort_err)[:200]}"
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


# --- Lazy per-model detector singleton (load the ~4.6MB net once per process) ------
_DETECTORS: dict[str, U2NetDetector] = {}


def _get_detector(model_path: Path) -> U2NetDetector:
    key = str(model_path)
    det = _DETECTORS.get(key)
    if det is None:
        det = U2NetDetector(model_path)
        _DETECTORS[key] = det
    return det


# --- Analysis (ported from kb_target_probe_u2net.analyze) -------------------------
def _analyze(prob: np.ndarray) -> dict:
    """Reduce the [0,1] foreground-probability map to the gate metrics + raw anchor.

    coverage  -- fraction of the frame above MASK_THR (how much is foreground).
    mean_conf -- mean probability INSIDE that mask (how confident the foreground).
    dom       -- largest connected blob's share of total (kept) foreground area.
    anchor    -- probability-weighted centroid of the LARGEST blob, normalized
                 [0,1] source coords (UNCLAMPED; the clamp is applied later).
    h_extent  -- normalized width of the bounding union of the SIGNIFICANT blobs
                 (>= PAN_BLOB_MIN_FRAC of the frame): large for a wide subject.
    hspread   -- normalized horizontal distance between the leftmost and rightmost
                 significant-blob centroids (0 if < 2): large for spread subjects.
    n_sig     -- number of significant blobs (the pan MULTI test's blob count).
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

    # --- Pan/zoom geometry: among the kept blobs take the SIGNIFICANT ones (a
    # higher bar than the speck filter) and measure how wide their union is and how
    # far their centroids spread horizontally. A lone compact subject -> small
    # h_extent, n_sig 1; a wide subject -> large h_extent; several spread subjects
    # -> n_sig >= 2 with a large hspread. -------------------------------------------
    sig_min_area = PAN_BLOB_MIN_FRAC * h * w
    sig = [lab for lab in kept if stats[lab, cv2.CC_STAT_AREA] >= sig_min_area]
    if sig:
        lefts = [stats[lab, cv2.CC_STAT_LEFT] for lab in sig]
        rights = [stats[lab, cv2.CC_STAT_LEFT] + stats[lab, cv2.CC_STAT_WIDTH] for lab in sig]
        cxs = [(stats[lab, cv2.CC_STAT_LEFT] + stats[lab, cv2.CC_STAT_WIDTH] / 2.0) / w
               for lab in sig]
        h_extent = float(max(rights) - min(lefts)) / w
        hspread = float(max(cxs) - min(cxs)) if len(cxs) >= 2 else 0.0
        n_sig = len(sig)
    else:
        h_extent, hspread, n_sig = 0.0, 0.0, 0

    return {
        "coverage": coverage, "mean_conf": mean_conf, "dom": dom, "anchor": anchor,
        "h_extent": h_extent, "hspread": hspread, "n_sig": n_sig,
    }


# --- Edge-margin clamp -----------------------------------------------------------
def _visible_band(src_w: int, src_h: int) -> tuple[float, float, float, float]:
    """The [0,1] source-normalized region that survives the base 16:9 cover-fill,
    as (h_left, h_right, v_top, v_bottom). Mirrors kenburns_subpixel's geometry:
    ``base = max(OUT_W/src_w, OUT_H/src_h)`` scales the source to COVER the frame,
    so the visible window at z=1 is ``OUT_W/base`` x ``OUT_H/base`` source px,
    centred. For a square source this is the full width and the centre ~56% band
    of the height."""
    base = max(OUT_W / src_w, OUT_H / src_h)
    hfrac = min(1.0, (OUT_W / base) / src_w)  # visible fraction of source width
    vfrac = min(1.0, (OUT_H / base) / src_h)  # visible fraction of source height
    h_left = (1.0 - hfrac) / 2.0
    v_top = (1.0 - vfrac) / 2.0
    return h_left, 1.0 - h_left, v_top, 1.0 - v_top


def _clamp_anchor(x: float, y: float, src_w: int, src_h: int) -> tuple[float, float]:
    """Clamp a normalized anchor into the INTERIOR of the visible 16:9 frame: at
    least ``EDGE_MARGIN_FRAC`` of each axis's visible span away from the visible
    edge. Keeps the zoom target framed and never on cropped-off content."""
    h_left, h_right, v_top, v_bot = _visible_band(src_w, src_h)
    mx = EDGE_MARGIN_FRAC * (h_right - h_left)
    my = EDGE_MARGIN_FRAC * (v_bot - v_top)
    lo_x, hi_x = h_left + mx, h_right - mx
    lo_y, hi_y = v_top + my, v_bot - my
    cx = min(hi_x, max(lo_x, x))
    cy = min(hi_y, max(lo_y, y))
    return cx, cy


# --- Move classification (zoom / pan / center) -----------------------------------
def _classify_move(a: dict) -> str:
    """Pick HOW to move on this still from the mask metrics (see the PAN_* / gate
    constants). ``center`` is the same population as the gate's ``center`` (no
    aimable subject); a WIDE or MULTI subject becomes a ``pan``; a single compact
    confident subject becomes a ``zoom``."""
    if not (COV_MIN <= a["coverage"] <= COV_MAX) or a["mean_conf"] < CONF_MIN:
        return "center"  # tiny / whole-frame / weak -> safe centre zoom
    wide = a["h_extent"] >= PAN_EXTENT_MIN
    multi = a["n_sig"] >= PAN_MIN_BLOBS and a["hspread"] >= PAN_SPREAD_MIN
    if wide or multi:
        return "pan"
    if a["dom"] >= DOM_MIN:
        return "zoom"  # one clear, compact subject (the gate's ``target`` case)
    return "center"    # confident but fragmented and not spread -> safe centre zoom


def _pan_endpoints(
    target_raw: tuple[float, float], src_w: int, src_h: int
) -> tuple[tuple[float, float], tuple[float, float]]:
    """Pan anchors for a pan shot. ``pan_to`` is the subject (the largest blob's
    weighted centroid) clamped into the visible interior -- the destination the
    camera comes to rest on. ``pan_from`` is offset ``PAN_FROM_OFFSET`` toward the
    OPPOSITE horizontal side at the subject's OWN vertical position (so the camera
    glides ACROSS to the subject), also clamped. Returns ``(pan_from, pan_to)``."""
    tx, ty = target_raw
    fx = tx - PAN_FROM_OFFSET if tx >= 0.5 else tx + PAN_FROM_OFFSET
    pan_to = _clamp_anchor(tx, ty, src_w, src_h)
    pan_from = _clamp_anchor(fx, ty, src_w, src_h)
    return pan_from, pan_to


# --- Cache -----------------------------------------------------------------------
def _cache_path(png_path: Path) -> Path:
    return Path(str(png_path) + CACHE_SUFFIX)


def _read_cache(png_path: Path) -> dict | None:
    """Return the cached result iff the sidecar exists, has the current schema, and
    was written for the still's CURRENT mtime; else None. Best-effort (any error
    -> recompute)."""
    cp = _cache_path(png_path)
    try:
        if not cp.exists():
            return None
        data = json.loads(cp.read_text())
        if data.get("schema") != CACHE_SCHEMA:
            return None
        if data.get("mtime_ns") != png_path.stat().st_mtime_ns:
            return None
        r = data["result"]
        pf, pt = r.get("pan_from"), r.get("pan_to")
        return {
            "anchor": (float(r["anchor"][0]), float(r["anchor"][1])),
            "gate": str(r["gate"]),
            "move": str(r["move"]),
            "pan_from": (float(pf[0]), float(pf[1])) if pf else None,
            "pan_to": (float(pt[0]), float(pt[1])) if pt else None,
            "confidence": float(r["confidence"]),
            "coverage": float(r["coverage"]),
            "dominance": float(r["dominance"]),
        }
    except Exception:  # noqa: BLE001 -- corrupt/partial cache: just recompute
        return None


def _write_cache(png_path: Path, src_w: int, src_h: int, result: dict,
                 anchor_raw: tuple[float, float]) -> None:
    """Write the small JSON sidecar keyed on the still's mtime. Best-effort: a
    read-only footage dir just means no caching, never a failure."""
    payload = {
        "schema": CACHE_SCHEMA,
        "mtime_ns": png_path.stat().st_mtime_ns,
        "src_w": src_w,
        "src_h": src_h,
        "anchor_raw": [anchor_raw[0], anchor_raw[1]],  # pre-clamp, for debugging
        "result": {
            "anchor": [result["anchor"][0], result["anchor"][1]],
            "gate": result["gate"],
            "move": result["move"],
            "pan_from": list(result["pan_from"]) if result["pan_from"] else None,
            "pan_to": list(result["pan_to"]) if result["pan_to"] else None,
            "confidence": result["confidence"],
            "coverage": result["coverage"],
            "dominance": result["dominance"],
        },
    }
    try:
        _cache_path(png_path).write_text(json.dumps(payload))
    except OSError:
        pass


# --- Public API ------------------------------------------------------------------
def analyze_still(
    png_path: str | Path,
    model_path: str | Path = DEFAULT_MODEL,
    use_cache: bool = True,
) -> dict:
    """Analyze one still and return where the Ken Burns zoom should aim.

    Returns a dict::

        {
          "anchor": (x, y),   # normalized [0,1] source coords, edge-margin clamped
          "gate": "target" | "center",
          "move": "zoom" | "pan" | "center",   # HOW to move on this still
          "pan_from": (x, y) | None,  # pan start anchor (only when move == "pan")
          "pan_to": (x, y) | None,    # pan end anchor / subject (only when "pan")
          "confidence": float,   # mean U2-Net probability inside the subject mask
          "coverage": float,     # subject's fraction of the frame
          "dominance": float,    # largest blob's share of all foreground
        }

    ``gate == "target"`` means one clear, confident, compact subject was found and
    ``anchor`` is that subject (clamped into the visible frame). ``gate ==
    "center"`` means no clear single subject -> ``anchor`` is the (clamped) centre,
    a safe centre zoom. ``move`` refines this into the CAMERA MOVE to use: ``zoom``
    (fixed-anchor zoom on a compact subject), ``pan`` (glide ACROSS a wide/multi
    subject, using ``pan_from`` -> ``pan_to``, both clamped into the visible frame),
    or ``center`` (safe centre zoom). ``pan_from``/``pan_to`` are ``None`` unless
    ``move == "pan"``. Results are cached in a per-still sidecar keyed on path +
    mtime (disable with ``use_cache=False``).
    """
    png_path = Path(png_path)
    if use_cache:
        cached = _read_cache(png_path)
        if cached is not None:
            return cached

    bgr = cv2.imread(str(png_path), cv2.IMREAD_COLOR)
    if bgr is None:
        raise ValueError(f"unreadable still: {png_path}")
    src_h, src_w = bgr.shape[:2]

    det = _get_detector(Path(model_path))
    prob = det.prob_map(bgr)
    a = _analyze(prob)

    is_target = (
        COV_MIN <= a["coverage"] <= COV_MAX
        and a["mean_conf"] >= CONF_MIN
        and a["dom"] >= DOM_MIN
    )
    gate = "target" if is_target else "center"
    anchor_raw = a["anchor"] if is_target else (0.5, 0.5)
    anchor = _clamp_anchor(anchor_raw[0], anchor_raw[1], src_w, src_h)

    # Move refines the gate: a WIDE/MULTI subject pans (from the raw largest-blob
    # centroid, independent of the gate) instead of zooming; else zoom/center.
    move = _classify_move(a)
    if move == "pan":
        pan_from, pan_to = _pan_endpoints(a["anchor"], src_w, src_h)
    else:
        pan_from, pan_to = None, None

    result = {
        "anchor": anchor,
        "gate": gate,
        "move": move,
        "pan_from": pan_from,
        "pan_to": pan_to,
        "confidence": a["mean_conf"],
        "coverage": a["coverage"],
        "dominance": a["dom"],
    }
    if use_cache:
        _write_cache(png_path, src_w, src_h, result, anchor_raw)
    return result


# --- Standalone self-check (free: local model + PNG stills, no API) --------------
def _self_check() -> None:
    """Analyze a spread of mosquito-project stills and print gate + move + anchor
    (and the pan path for pan shots), spanning the clamp edge cases (s044 is shoved
    off the left margin) and the wide/multi pan candidates (s020, s044, s055) next
    to compact single-subject zooms (s002, s007, s039) and center-gated stills
    (s005, s028). Verifies the module runs end-to-end, that every anchor -- and
    every pan endpoint -- stays inside the visible interior, and lets the pan/zoom
    thresholds be eyeballed. No API / generation."""
    project = (
        Path.home()
        / "Documents/Aqua/projects/this-5-bucket-wiped-out-the-mosquitoes-in-my-yard"
    )
    footage = project / "footage"
    h_left, h_right, v_top, v_bot = _visible_band(1024, 1024)
    mx = EDGE_MARGIN_FRAC * (h_right - h_left)
    my = EDGE_MARGIN_FRAC * (v_bot - v_top)
    lo_x, hi_x, lo_y, hi_y = h_left + mx, h_right - mx, v_top + my, v_bot - my

    def _inside(pt: tuple[float, float]) -> bool:
        x, y = pt
        return lo_x - 1e-9 <= x <= hi_x + 1e-9 and lo_y - 1e-9 <= y <= hi_y + 1e-9

    print("kb_shot_analysis self-check")
    print(f"  clamp: x in [{lo_x:.3f}, {hi_x:.3f}]  y in [{lo_y:.3f}, {hi_y:.3f}]  "
          f"(1024^2 -> 16:9)")
    print(f"  {'scene':>7} {'gate':>7} {'move':>7} {'anchor(x,y)':>13} "
          f"{'conf':>5} {'cov':>6} {'dom':>5}  pan_from->pan_to")
    counts: dict[str, int] = {"zoom": 0, "pan": 0, "center": 0}
    for sid in (2, 5, 7, 20, 28, 39, 44, 55):
        png = footage / f"scene_{sid:03d}.png"
        if not png.exists():
            print(f"  s{sid:03d}: MISSING ({png})")
            continue
        r = analyze_still(png, use_cache=False)
        counts[r["move"]] = counts.get(r["move"], 0) + 1
        ax, ay = r["anchor"]
        assert _inside(r["anchor"]), (sid, r["anchor"])
        pan = ""
        if r["move"] == "pan":
            assert _inside(r["pan_from"]) and _inside(r["pan_to"]), (sid, r)
            pan = (f"({r['pan_from'][0]:.2f},{r['pan_from'][1]:.2f})->"
                   f"({r['pan_to'][0]:.2f},{r['pan_to'][1]:.2f})")
        print(f"  s{sid:03d} {r['gate']:>10} {r['move']:>7} ({ax:.2f},{ay:.2f}) "
              f"{r['confidence']:>5.2f} {r['coverage']:>6.3f} {r['dominance']:>5.2f}  {pan}")
    print(f"  move counts: {counts['zoom']} zoom / {counts['pan']} pan / "
          f"{counts['center']} center")
    print("  all anchors + pan endpoints inside the clamped interior: PASS")
    print("  no generation / API / paid calls -- local U2-Netp + OpenCV on PNGs.")


if __name__ == "__main__":
    _self_check()
