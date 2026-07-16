#!/usr/bin/env python3
"""image_model_shootout.py -- PAID head-to-head of fal.ai text-to-image models.

Why this exists
---------------
The pipeline is moving from stock/AI placeholders toward AI-generated stills, and
we need to know which of the current fal.ai flagships gives the best photoreal 16:9
frame per dollar for garden/nature b-roll. This harness fires the SAME two "hard"
photoreal prompts at five models at native ~2K, downloads every result, builds the
real pipeline output (center-crop 16:9 -> 1920x1080), and stitches a labelled
side-by-side montage per prompt so a human can rate them at a glance.

!! THIS SPENDS MONEY !! Each successful generation is a billed fal.ai call
(~$0.03-0.20/image depending on model). A full run is ~10 images. There is a hard
projected-spend guard (default $1.50) that stops the run before it blows past
budget. Use ``--dry-run`` to preview the plan for free.

Isolation / deps
----------------
Follows the kb_* harness convention: system python3 + the isolated
``/tmp/kb/pylibs`` third-party target (numpy + headless opencv already live there;
``fal-client`` was pip-installed with ``--target /tmp/kb/pylibs``). It never touches
either project venv's site-packages. All image work (decode / crop / downscale /
montage / labels) is done with cv2 + numpy; downloads use stdlib urllib. The
``FAL_KEY`` is parsed out of ``backend/.env`` at runtime -- never hardcoded.

How to run
----------
Preview the plan, no API calls, no spend::

    python3 backend/tools/image_model_shootout.py --dry-run

Do the real (PAID) run into /tmp/shootout::

    python3 backend/tools/image_model_shootout.py

Only some models / a tighter budget ceiling::

    python3 backend/tools/image_model_shootout.py --only seedream45,reve2 --budget 0.30

Outputs (default /tmp/shootout)
-------------------------------
  * A_<model>.png / B_<model>.png      -- full-res download per model x prompt
  * A_<model>_1080p.png / B_..._1080p  -- pipeline output (crop 16:9 -> 1920x1080)
  * montage_A.png / montage_B.png      -- 5 models side-by-side, labelled
  * results.json                       -- machine-readable record of the run
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
import urllib.request
from pathlib import Path

# --- Isolated third-party libs: the same /tmp/kb/pylibs target the kb_* harnesses
# use (headless opencv + numpy), with fal-client pip-installed alongside. Keeps this
# tool off both project venvs' site-packages. -----------------------------------
PYLIBS = "/tmp/kb/pylibs"
if PYLIBS not in sys.path:
    sys.path.insert(0, PYLIBS)
import numpy as np  # noqa: E402
import cv2  # noqa: E402
import fal_client  # noqa: E402

FONT = cv2.FONT_HERSHEY_SIMPLEX

# --- Prompts: two deliberately "hard" photoreal garden frames (macro subject +
# vivid-but-clean scene). Both explicitly forbid text/watermarks/logos. ----------
PROMPTS: dict[str, str] = {
    "A": (
        "Extreme macro close-up of a fuzzy bumblebee on a bright orange garden "
        "zinnia, rich vivid color, warm morning sunlight, crisp razor-sharp detail "
        "on the bee and petals, soft green background, professional photograph, "
        "16:9, no text, no watermarks, no logos."
    ),
    "B": (
        "Blue bug-zapper lantern glowing on a clean, well-kept backyard patio at "
        "golden hour, lush green garden behind, rich vibrant warm color, bright and "
        "inviting, sharp focus, professional high-detail photograph, 16:9, no text, "
        "no watermarks, no logos."
    ),
}

# --- Model specs. Each model lists endpoint fallbacks (tried in order) and a small
# ladder of argument variants (tried in order until one SUCCEEDS). Param names differ
# per model (aspect_ratio vs image_size dict vs image_size preset), so the ladder
# absorbs a wrong guess: a rejected variant just moves to the next. The FIRST variant
# is the budget-safe one (pins num_images:1 where supported); later variants drop
# possibly-unsupported params. We break on the first success, so at most ONE billed
# call per model x prompt. est_cost is a best-effort per-image price estimate (fal
# rarely returns real cost in the response) used only for the pre-call budget guard
# and the final tally. -----------------------------------------------------------
MODELS: list[dict] = [
    dict(
        key="seedream45",
        label="Seedream 4.5",
        endpoints=["fal-ai/bytedance/seedream/v4.5/text-to-image"],
        arg_variants=[
            {"image_size": {"width": 2048, "height": 1152}, "num_images": 1},
            {"image_size": {"width": 2048, "height": 1152}},
            {"aspect_ratio": "16:9", "num_images": 1},
            {"aspect_ratio": "16:9"},
        ],
        est_cost=0.03,
    ),
    dict(
        key="reve2",
        label="Reve 2.0",
        # NOTE (verified 2026-07-12): this path 404s ("Application 'reve' not
        # found"); 13 endpoint variants + a fal model-registry search for "reve"
        # all came up empty -> Reve is not currently published on fal.ai. Update
        # this list if/when it appears. The arg ladder below is left ready for that.
        endpoints=["fal-ai/reve/text-to-image"],
        arg_variants=[
            {"aspect_ratio": "16:9", "num_images": 1},
            {"aspect_ratio": "16:9"},
            {"image_size": {"width": 1920, "height": 1080}, "num_images": 1},
            {"image_size": "landscape_16_9"},
        ],
        est_cost=0.04,  # price UNCONFIRMED -- log real resolution/cost from response
    ),
    dict(
        key="nanobanana2",
        label="Nano Banana 2",
        endpoints=["fal-ai/nano-banana-2"],
        arg_variants=[
            {"aspect_ratio": "16:9", "image_size": "2K", "num_images": 1},
            {"aspect_ratio": "16:9", "image_size": "2K"},
            {"aspect_ratio": "16:9", "resolution": "2K"},
            {"aspect_ratio": "16:9"},
        ],
        est_cost=0.12,
    ),
    dict(
        key="gptimage2",
        label="GPT Image 2",
        endpoints=["openai/gpt-image-2", "fal-ai/gpt-image-2"],
        arg_variants=[
            {"image_size": {"width": 1920, "height": 1080}, "quality": "high", "num_images": 1},
            {"image_size": "1536x1024", "quality": "high"},
            {"aspect_ratio": "16:9", "quality": "high"},
            {"image_size": "landscape_16_9"},
        ],
        est_cost=0.20,
    ),
    dict(
        key="grok",
        label="Grok Imagine",
        endpoints=["xai/grok-imagine-image"],
        arg_variants=[
            {"aspect_ratio": "16:9", "image_size": "2K", "num_images": 1},
            {"aspect_ratio": "16:9", "num_images": 1},
            {"aspect_ratio": "16:9"},
        ],
        est_cost=0.05,
    ),
]


# --------------------------------------------------------------------------- env
def load_fal_key(env_path: Path) -> str:
    """Parse FAL_KEY out of a .env file. Handles optional ``export`` prefix and
    surrounding quotes; splits only on the FIRST '=' so the key's own ``id:secret``
    colon is preserved. Never hardcoded."""
    if not env_path.is_file():
        raise FileNotFoundError(f".env not found at {env_path}")
    for raw in env_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        name = name.strip()
        if name.startswith("export "):
            name = name[len("export "):].strip()
        if name != "FAL_KEY":
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] in "\"'" and value[-1] == value[0]:
            value = value[1:-1]
        if value:
            return value
    raise KeyError(f"FAL_KEY not present / empty in {env_path}")


# ------------------------------------------------------------------- fal helpers
def _compact(d: dict) -> str:
    return json.dumps(d, separators=(",", ":"))


def extract_image(resp) -> tuple[str | None, int | None, int | None, str | None]:
    """Pull (url, width, height, content_type) out of a fal response, tolerating the
    common shapes (``images: [ {...}|str ]`` or single ``image``)."""
    if not isinstance(resp, dict):
        raise ValueError(f"non-dict response: {type(resp).__name__}")
    imgs = resp.get("images")
    if isinstance(imgs, list) and imgs:
        im = imgs[0]
        if isinstance(im, str):
            return im, None, None, None
        if isinstance(im, dict):
            return im.get("url"), im.get("width"), im.get("height"), im.get("content_type")
    im = resp.get("image")
    if isinstance(im, dict):
        return im.get("url"), im.get("width"), im.get("height"), im.get("content_type")
    if isinstance(im, str):
        return im, None, None, None
    raise ValueError(f"no image field in response; keys={list(resp.keys())}")


def extract_cost(resp) -> float | None:
    """Best-effort: return a cost if fal happened to expose one in the JSON body.
    Usually absent (billing is server-side), so callers fall back to est_cost."""
    if not isinstance(resp, dict):
        return None
    for k in ("cost", "price", "billing", "billable_units", "credits"):
        v = resp.get(k)
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, dict):
            for kk in ("amount", "usd", "total", "cost"):
                if isinstance(v.get(kk), (int, float)):
                    return float(v[kk])
    return None


def call_model(model: dict, prompt_text: str, timeout: float, log) -> dict:
    """Try endpoint x arg-variant combinations until one returns an image. Break on
    first success => at most one billed call. Raises with the attempt log if all
    combinations fail."""
    attempts: list[tuple[str, str]] = []
    for endpoint in model["endpoints"]:
        for variant in model["arg_variants"]:
            args = {"prompt": prompt_text, **variant}
            desc = f"{endpoint} {_compact(variant)}"
            try:
                log(f"      -> {desc}")
                resp = fal_client.subscribe(
                    endpoint, arguments=args, with_logs=False, client_timeout=timeout
                )
                url, w, h, ct = extract_image(resp)
                if not url:
                    raise ValueError("response had no image url")
                return dict(
                    resp=resp, endpoint=endpoint, args=args, url=url,
                    rep_w=w, rep_h=h, content_type=ct, attempts=attempts,
                )
            except Exception as e:  # noqa: BLE001 -- robustness: log & try next
                status = getattr(e, "status_code", None)
                msg = f"{type(e).__name__}{f'[{status}]' if status else ''}: {e}"
                attempts.append((desc, msg))
                log(f"         x {msg[:200]}")
    raise RuntimeError(f"all {len(attempts)} attempt(s) failed", attempts)


# ------------------------------------------------------------------ image helpers
def download(url: str, timeout: float = 90.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "image-shootout/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def decode(data: bytes) -> np.ndarray:
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("cv2 could not decode downloaded image bytes")
    return img


def crop_to_16x9(img: np.ndarray) -> np.ndarray:
    """Center-crop to a clean 16:9 (no distortion) -- what the pipeline does before
    scaling a still to frame."""
    h, w = img.shape[:2]
    target = 16.0 / 9.0
    ar = w / h
    if ar > target:  # too wide -> trim sides
        nw = int(round(h * target))
        x0 = (w - nw) // 2
        return img[:, x0:x0 + nw]
    if ar < target:  # too tall -> trim top/bottom
        nh = int(round(w / target))
        y0 = (h - nh) // 2
        return img[y0:y0 + nh, :]
    return img


def pipeline_1080(img: np.ndarray) -> np.ndarray:
    return cv2.resize(crop_to_16x9(img), (1920, 1080), interpolation=cv2.INTER_AREA)


def _tile(img_1080: np.ndarray, label: str, tile_w: int) -> np.ndarray:
    """A montage cell: label bar on top of a scaled 16:9 frame."""
    tile_h = int(round(tile_w * 9 / 16))
    body = cv2.resize(img_1080, (tile_w, tile_h), interpolation=cv2.INTER_AREA)
    bar_h = 56
    bar = np.full((bar_h, tile_w, 3), 28, np.uint8)
    cv2.putText(bar, label, (14, 38), FONT, 0.85, (255, 255, 255), 2, cv2.LINE_AA)
    return np.vstack([bar, body])


def _placeholder_1080(label: str) -> np.ndarray:
    img = np.full((1080, 1920, 3), 55, np.uint8)
    cv2.putText(img, "FAILED", (760, 560), FONT, 3.0, (70, 70, 230), 6, cv2.LINE_AA)
    return img


def build_montage(records: list[dict], tile_w: int = 900) -> np.ndarray:
    """5 cells side-by-side (one row), model order preserved, failures shown as a
    gray FAILED cell so every slot is visible."""
    gutter = 10
    cells = []
    for rec in records:
        if rec["status"] == "ok" and rec.get("_img1080") is not None:
            res = f"{rec['actual_w']}x{rec['actual_h']}"
            cells.append(_tile(rec["_img1080"], f"{rec['label']}  {res}", tile_w))
        else:
            cells.append(_tile(_placeholder_1080(rec["label"]), f"{rec['label']}  FAILED", tile_w))
    h = max(c.shape[0] for c in cells)
    sep = np.full((h, gutter, 3), 15, np.uint8)
    row = []
    for i, c in enumerate(cells):
        if c.shape[0] != h:
            c = np.vstack([c, np.full((h - c.shape[0], c.shape[1], 3), 28, np.uint8)])
        row.append(c)
        if i != len(cells) - 1:
            row.append(sep)
    return np.hstack(row)


# ---------------------------------------------------------------------------- run
def run(args) -> int:
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    models = MODELS
    if args.only:
        want = {k.strip() for k in args.only.split(",") if k.strip()}
        models = [m for m in MODELS if m["key"] in want]
        if not models:
            print(f"!! --only matched no models (known: {[m['key'] for m in MODELS]})")
            return 2
    prompt_keys = [k.strip().upper() for k in args.prompts.split(",") if k.strip()]
    prompt_keys = [k for k in prompt_keys if k in PROMPTS]
    if not prompt_keys:
        print("!! no valid prompts selected")
        return 2

    n_calls = len(models) * len(prompt_keys)
    est_total = sum(m["est_cost"] for m in models) * len(prompt_keys)
    print("=" * 78)
    print(f"fal.ai image model shootout  |  {len(models)} models x {len(prompt_keys)} prompts "
          f"= {n_calls} images")
    print(f"out_dir        : {out_dir}")
    print(f"budget ceiling : ${args.budget:.2f}")
    print(f"est. total     : ${est_total:.2f}  (per-image estimates, real cost may differ)")
    print("=" * 78)

    if est_total > args.budget:
        print(f"!! STOP: estimated total ${est_total:.2f} exceeds budget ${args.budget:.2f}. "
              f"Raise --budget or trim --only.")
        return 3

    if args.dry_run:
        print("\n[DRY RUN] no API calls, no spend. Planned calls:")
        for pk in prompt_keys:
            for m in models:
                v0 = _compact(m["arg_variants"][0])
                print(f"  {pk}  {m['label']:<14} {m['endpoints'][0]}  first-try={v0}  ~${m['est_cost']:.2f}")
        return 0

    # Real run needs the key in the environment for fal_client's auth.
    key = load_fal_key(Path(args.env))
    os.environ["FAL_KEY"] = key
    print(f"FAL_KEY loaded from {args.env} (len={len(key)}); starting PAID run...\n")

    records: list[dict] = []
    spent_est = 0.0
    aborted = False
    for pk in prompt_keys:
        prompt_text = PROMPTS[pk]
        for m in models:
            # Pre-call budget guard: never START a call that could push us over.
            if spent_est + m["est_cost"] > args.budget:
                print(f"\n!! BUDGET GUARD: spent est ${spent_est:.2f} + next ${m['est_cost']:.2f} "
                      f"> ${args.budget:.2f}. Stopping before {pk}/{m['key']}.")
                aborted = True
                break
            rec = dict(prompt=pk, model_key=m["key"], label=m["label"], est_cost=m["est_cost"],
                       status="failed", endpoint=None, args=None, actual_w=None, actual_h=None,
                       reported_w=None, reported_h=None, content_type=None, actual_cost=None,
                       full_path=None, path_1080=None, error=None, seconds=None)
            print(f"[{pk}] {m['label']}")
            t0 = time.time()
            try:
                res = call_model(m, prompt_text, args.timeout, log=print)
                data = download(res["url"])
                img = decode(data)
                h, w = img.shape[:2]
                img1080 = pipeline_1080(img)

                full_path = out_dir / f"{pk}_{m['key']}.png"
                path_1080 = out_dir / f"{pk}_{m['key']}_1080p.png"
                cv2.imwrite(str(full_path), img)
                cv2.imwrite(str(path_1080), img1080)

                rec.update(
                    status="ok", endpoint=res["endpoint"], args=res["args"],
                    actual_w=w, actual_h=h, reported_w=res["rep_w"], reported_h=res["rep_h"],
                    content_type=res["content_type"], actual_cost=extract_cost(res["resp"]),
                    full_path=str(full_path), path_1080=str(path_1080),
                    seconds=round(time.time() - t0, 1),
                )
                rec["_img1080"] = img1080
                spent_est += m["est_cost"]
                cost_note = (f"${rec['actual_cost']:.4f} (reported)" if rec["actual_cost"] is not None
                             else f"~${m['est_cost']:.2f} (est)")
                print(f"      ok  {w}x{h} {res['content_type'] or ''}  {rec['seconds']}s  "
                      f"cost {cost_note}  -> {full_path.name}")
            except Exception as e:  # noqa: BLE001 -- one model must never abort the run
                rec["error"] = f"{type(e).__name__}: {e}"
                rec["seconds"] = round(time.time() - t0, 1)
                print(f"      FAILED: {rec['error'][:220]}")
                if not isinstance(e, RuntimeError):  # unexpected -> keep a trace in the log
                    traceback.print_exc()
            records.append(rec)
        if aborted:
            break

    # ---- montages (built even on partial runs, from whatever succeeded) ----
    montage_paths: dict[str, str] = {}
    for pk in prompt_keys:
        recs = [r for r in records if r["prompt"] == pk]
        if not recs:
            continue
        # keep MODELS order for a stable side-by-side
        order = {m["key"]: i for i, m in enumerate(models)}
        recs.sort(key=lambda r: order.get(r["model_key"], 99))
        montage = build_montage(recs)
        mpath = out_dir / f"montage_{pk}.png"
        cv2.imwrite(str(mpath), montage)
        montage_paths[pk] = str(mpath)

    # ---- persist a clean JSON record (drop the in-memory image array) ----
    clean = []
    for r in records:
        c = {k: v for k, v in r.items() if k != "_img1080"}
        clean.append(c)
    results_path = out_dir / "results.json"
    results_path.write_text(json.dumps(
        {"prompts": {k: PROMPTS[k] for k in prompt_keys},
         "spent_est": round(spent_est, 2), "aborted": aborted,
         "montages": montage_paths, "records": clean}, indent=2))

    # -------------------------------- summary table --------------------------------
    print("\n" + "=" * 78)
    print("RESULTS")
    print("=" * 78)
    hdr = f"{'prompt':<7}{'model':<15}{'status':<8}{'resolution':<13}{'cost':<16}{'secs':<6}"
    print(hdr)
    print("-" * 78)
    for r in clean:
        res = f"{r['actual_w']}x{r['actual_h']}" if r["actual_w"] else "-"
        if r["status"] == "ok":
            cost = (f"${r['actual_cost']:.4f} rep" if r["actual_cost"] is not None
                    else f"~${r['est_cost']:.2f} est")
        else:
            cost = "$0 (no bill)"
        print(f"{r['prompt']:<7}{r['label']:<15}{r['status']:<8}{res:<13}{cost:<16}{str(r['seconds'] or '-'):<6}")
    print("-" * 78)
    print(f"TOTAL estimated spend: ${spent_est:.2f}"
          + ("  [PARTIAL -- run aborted by budget guard]" if aborted else ""))

    print("\nMONTAGES:")
    for pk in prompt_keys:
        if pk in montage_paths:
            print(f"  {pk}: {montage_paths[pk]}")
    print("\nINDIVIDUAL (full-res):")
    for r in clean:
        if r["status"] == "ok":
            print(f"  {r['prompt']}/{r['label']}: {r['full_path']}")
    print(f"\nresults.json: {results_path}")
    print("(paths only -- not opening anything)")
    return 0


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out-dir", default="/tmp/shootout", help="output dir (default /tmp/shootout)")
    p.add_argument("--env", default=str(Path(__file__).resolve().parents[1] / ".env"),
                   help="path to .env holding FAL_KEY (default backend/.env)")
    p.add_argument("--budget", type=float, default=1.50,
                   help="hard projected-spend ceiling in USD (default 1.50)")
    p.add_argument("--timeout", type=float, default=180.0, help="per-call client timeout secs")
    p.add_argument("--prompts", default="A,B", help="comma list of prompt keys (default A,B)")
    p.add_argument("--only", default="", help="comma list of model keys to restrict to")
    p.add_argument("--dry-run", action="store_true", help="print the plan, no calls, no spend")
    return p


if __name__ == "__main__":
    sys.exit(run(build_argparser().parse_args()))
