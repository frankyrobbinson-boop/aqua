"""Seedream 4.5 visual provider — ByteDance Seedream via fal.ai.

Model: ``fal-ai/bytedance/seedream/v4.5/text-to-image``. Cost: ~$0.03 per
image. We request ``image_size: {width: 2048, height: 1152}`` (16:9) and
Seedream returns a native ~3416x1920 16:9 PNG.

We save the FULL native image — NO downscale in the provider. The high res is
deliberate: the render pipeline fills to 1920x1080 later (a clean downscale)
AND the Ken Burns drift needs the 16:9 headroom to pan/zoom without upscaling.

Env:
    FAL_KEY — fal.ai credential (``id:secret``), in backend/.env. Get one at
    https://fal.ai/dashboard/keys.

Caching: per-scene sidecar at ``<output>.cache.json`` keyed by the full prompt
+ negative_prompt sent to Seedream (plus model + source + image_size). Editing
the scene's enhanced prompt invalidates only that one image; a provider change
(different model id) naturally invalidates old cached images.

Concurrency: ThreadPoolExecutor-friendly — a single provider instance bounds
concurrent fal calls with ``_SEEDREAM_CONCURRENCY`` (default 8, override via
env) so the orchestrator can pick pool size while we still rate-cap per
provider.
"""

from __future__ import annotations

import io
import json
import os
import threading
import time
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

from services import cost_ledger
from services.paths import PROJECTS_ROOT
from services.visual_provider import (
    VisualProvider,
    clean_other_mode_files,
    footage_dir_for,
    is_cache_valid,
    write_cache,
)

load_dotenv()

_ENDPOINT = "fal-ai/bytedance/seedream/v4.5/text-to-image"
# Model label used for the cache key AND the cost ledger. Kept short + stable;
# a bump here (new model version) invalidates cached images by design.
_MODEL_ID = "seedream-4.5"
_SEEDREAM_CONCURRENCY = int(os.getenv("SEEDREAM_CONCURRENCY", "8"))
# Requested size — Seedream reads this as an aspect-ratio hint and returns a
# native ~3416x1920 16:9 image. Serialized into the cache key so a ratio change
# invalidates existing images without manual file deletion.
_IMAGE_SIZE = {"width": 2048, "height": 1152}

# 16:9 = 1.7778. Tolerance band accepts Seedream's native return (3416x1920 =
# 1.7792) as-is while still catching a stray off-ratio image. Matches the band
# used by the old Nano Banana provider.
_ASPECT_RATIO_MIN = 1.760
_ASPECT_RATIO_MAX = 1.796

# Retry policy for transient fal failures (rate limit / 5xx / network / timeout).
_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 2.0  # seconds; exponential backoff: 2, 4, 8

# Baseline image-direction prefix used ONLY when a project has no enhanced
# visual_prompts.json (fallback mode). The enhancer already bakes cinematic
# language into its prompts, so enhanced scenes are used verbatim.
_BASELINE_PREFIX = (
    "16:9 widescreen cinematic photograph, professional quality, natural "
    "lighting, no text, no watermarks, no logos. Subject: "
)


class SeedreamProvider(VisualProvider):
    """AI image generation via ByteDance Seedream 4.5 on fal.ai."""

    provider_id = "seedream"
    mode = "ai_image"

    def __init__(self) -> None:
        # Bound how many concurrent calls THIS instance makes to fal even when
        # the orchestrator spawns N worker threads. A semaphore (not a private
        # pool) lets the orchestrator decide pool size while we rate-cap per
        # provider.
        self._seedream_semaphore = threading.Semaphore(_SEEDREAM_CONCURRENCY)
        # Lazy-resolved fal_client module. Importing the SDK at module load
        # would force every caller (including the registry verifier) to have the
        # package installed even if this provider is never exercised.
        self._fal = None
        self._client_lock = threading.Lock()
        # Per-project enhanced visual-prompts payload (visual_prompts.json),
        # lazy-loaded on first scene fetch. ``None`` before load; ``{}``/None
        # after a failed load = "no file, run fallback for every scene". Keyed
        # by project_name so one long-lived instance handling multiple projects
        # doesn't cross-contaminate prompts.
        self._visual_prompts_cache: dict[str, dict | None] = {}
        self._visual_prompts_lock = threading.Lock()

    # ------------------------------------------------------------------
    # SDK wiring
    # ------------------------------------------------------------------

    def _ensure_fal(self):
        """Lazy-load fal_client + confirm FAL_KEY. Raises a clear error naming
        the env var if the key is missing so users see ``FAL_KEY`` in the
        trace."""
        with self._client_lock:
            if self._fal is not None:
                return self._fal
            api_key = os.getenv("FAL_KEY")
            if not api_key:
                raise RuntimeError(
                    "FAL_KEY not set. Add your fal.ai credential to "
                    "backend/.env (get one at https://fal.ai/dashboard/keys)."
                )
            try:
                import fal_client  # type: ignore
            except ImportError as exc:
                raise RuntimeError(
                    "fal-client not installed. Run "
                    "`pip install -r requirements.txt`."
                ) from exc
            # fal_client.subscribe authenticates off FAL_KEY in the environment.
            # load_dotenv() at import already populated it; set defensively in
            # case a caller imported us before the .env was loaded.
            os.environ.setdefault("FAL_KEY", api_key)
            self._fal = fal_client
            return self._fal

    # ------------------------------------------------------------------
    # VisualProvider
    # ------------------------------------------------------------------

    def fetch_for_scene(self, project_name: str, scene: dict) -> Path:
        sid = scene["id"]
        footage_dir = footage_dir_for(project_name)
        output = footage_dir / f"scene_{sid:03d}.png"

        query = (scene.get("visual_description") or "").strip()
        if not query:
            raise ValueError(
                f"Scene {sid} has no visual_description to generate from"
            )

        # Prefer the enhanced prompt (+ negative_prompt) from
        # visual_prompt_service if present; it already incorporates the baseline
        # cinematic language so we use it VERBATIM — no _BASELINE_PREFIX.
        enhanced = self._lookup_enhanced(project_name, sid)
        if enhanced is not None:
            prompt = enhanced["prompt"]
            negative = enhanced["negative_prompt"]
            source = enhanced["source"]
        else:
            prompt = _BASELINE_PREFIX + query
            negative = ""
            source = "fallback"

        # ``source`` makes the cache invalidate on a mode flip even if the exact
        # prompt text happens to collide between enhanced/passthrough. negative
        # is part of the key so editing it alone regenerates the image.
        cache_key = {
            "prompt": prompt,
            "negative_prompt": negative,
            "model": _MODEL_ID,
            "source": source,
            "image_size": f"{_IMAGE_SIZE['width']}x{_IMAGE_SIZE['height']}",
        }
        if is_cache_valid(output, cache_key):
            print(f"  [scene {sid}] seedream cached -> {output}", flush=True)
            return output

        # Clean up any stale stock-video artifact for this scene id so a mode
        # flip (stock_video -> ai_image) doesn't leave both an .mp4 and .png
        # that render's path-scan picks unpredictably.
        clean_other_mode_files(footage_dir, sid, keep_ext=".png")

        with self._seedream_semaphore:
            print(
                f"  [scene {sid}] seedream generating -> {output}",
                flush=True,
            )
            image_bytes = self._generate(prompt, negative, sid)

        # Safety net only: Seedream returns native 16:9 (~3416x1920), so this is
        # a no-op that returns the original bytes UNTOUCHED — we deliberately
        # keep the full native resolution (no downscale). It only crops if fal
        # ever hands back an off-ratio image.
        image_bytes = _conform_to_16_9(image_bytes, sid)

        with open(output, "wb") as f:
            f.write(image_bytes)

        write_cache(output, cache_key)

        cost_ledger.record(
            project_name,
            stage="visuals",
            provider="fal",
            model=_MODEL_ID,
            units=1,
            extra={"scene_id": sid},
        )

        return output

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _lookup_enhanced(self, project_name: str, scene_id: int) -> dict | None:
        """Return ``{"prompt": str, "negative_prompt": str, "source":
        "enhanced"|"passthrough"}`` for ``scene_id`` from this project's
        ``visual_prompts.json``, or None if the file is missing / the scene is
        absent / the prompt is empty.

        Thread-safe lazy load: the orchestrator dispatches scenes across N
        workers, so the first one in pays the disk read while others wait."""
        with self._visual_prompts_lock:
            payload = self._visual_prompts_cache.get(project_name, None)
            if project_name not in self._visual_prompts_cache:
                path = PROJECTS_ROOT / project_name / "visual_prompts.json"
                if path.exists():
                    try:
                        with path.open() as f:
                            payload = json.load(f)
                    except (OSError, json.JSONDecodeError):
                        payload = None
                else:
                    payload = None
                self._visual_prompts_cache[project_name] = payload
        if not payload:
            return None
        source = payload.get("source", "enhanced")
        for entry in payload.get("scenes", []):
            if int(entry.get("id", -1)) == scene_id:
                prompt = (entry.get("prompt") or "").strip()
                if not prompt:
                    return None
                negative = (entry.get("negative_prompt") or "").strip()
                return {
                    "prompt": prompt,
                    "negative_prompt": negative,
                    "source": source,
                }
        return None

    def _generate(self, prompt: str, negative_prompt: str, scene_id: int) -> bytes:
        """One Seedream generation call with retry on transient errors. Returns
        the downloaded PNG bytes. Surfaces the final API error verbatim with the
        scene id attached."""
        fal = self._ensure_fal()
        arguments: dict = {"prompt": prompt, "image_size": dict(_IMAGE_SIZE)}
        # Seedream accepts a negative_prompt (Gemini didn't). Pass it only when
        # the enhancer actually emitted one.
        if negative_prompt:
            arguments["negative_prompt"] = negative_prompt

        resp = _call_with_retry(
            lambda: fal.subscribe(_ENDPOINT, arguments=arguments, with_logs=False),
            scene_id=scene_id,
        )
        url = _extract_image_url(resp, scene_id)
        return _download(url, scene_id)


def _extract_image_url(resp, scene_id: int) -> str:
    """Pull the first image URL out of a fal response, tolerating the common
    shapes (``images: [ {url,...}|str ]`` or a single ``image``)."""
    if isinstance(resp, dict):
        imgs = resp.get("images")
        if isinstance(imgs, list) and imgs:
            im = imgs[0]
            if isinstance(im, str) and im:
                return im
            if isinstance(im, dict) and im.get("url"):
                return im["url"]
        im = resp.get("image")
        if isinstance(im, dict) and im.get("url"):
            return im["url"]
        if isinstance(im, str) and im:
            return im
    keys = list(resp.keys()) if isinstance(resp, dict) else type(resp).__name__
    raise RuntimeError(
        f"Seedream returned no image url for scene {scene_id}; response={keys}"
    )


def _download(url: str, scene_id: int, timeout: float = 90.0) -> bytes:
    """Download the generated image bytes over HTTP (stdlib urllib)."""
    req = urllib.request.Request(
        url, headers={"User-Agent": "aqua-seedream/1.0"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except Exception as exc:
        raise RuntimeError(
            f"Scene {scene_id}: failed to download Seedream image from "
            f"{url!r}: {exc!r}"
        ) from exc


def _conform_to_16_9(image_bytes: bytes, scene_id: int) -> bytes:
    """Return ``image_bytes`` conformed to 16:9. Seedream returns native 16:9,
    so in practice the decoded ratio is already within the accepted tolerance
    band and the ORIGINAL bytes are returned UNCHANGED (no re-encode, full
    native resolution preserved). Kept as a lightweight safety net: if fal ever
    hands back an off-ratio image we center-crop to exactly 16:9 rather than
    fail the scene. A totally undecodable image is a real failure and raises."""
    from PIL import Image  # Pillow is in requirements.txt; import inline keeps
    # module import cheap for the registry verifier.

    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            img.load()
            w, h = img.size
            mode = img.mode
            cropped = None
            if h > 0:
                ratio = w / h
                if not (_ASPECT_RATIO_MIN <= ratio <= _ASPECT_RATIO_MAX):
                    target = 16 / 9
                    if ratio < target:
                        # Too tall: keep full width, crop height.
                        new_h = round(w * 9 / 16)
                        top = (h - new_h) // 2
                        box = (0, top, w, top + new_h)
                    else:
                        # Too wide: keep full height, crop width.
                        new_w = round(h * 16 / 9)
                        left = (w - new_w) // 2
                        box = (left, 0, left + new_w, h)
                    cropped = img.crop(box)
    except Exception as exc:
        raise RuntimeError(
            f"Scene {scene_id}: could not decode Seedream PNG to conform "
            f"aspect ratio: {exc!r}"
        ) from exc

    if h <= 0:
        raise RuntimeError(
            f"Scene {scene_id}: Seedream returned image with non-positive "
            f"height ({w}x{h})"
        )

    if cropped is None:
        # Already within tolerance — return the original bytes untouched.
        return image_bytes

    cw, ch = cropped.size
    print(
        f"  [scene {scene_id}] seedream image was {w}x{h}, "
        f"cropped to 16:9 ({cw}x{ch})",
        flush=True,
    )

    # PNG can't cleanly save every PIL mode; fall back to RGB for anything
    # outside the modes PNG handles directly.
    if mode not in ("1", "L", "LA", "I", "P", "RGB", "RGBA"):
        cropped = cropped.convert("RGB")

    buf = io.BytesIO()
    cropped.save(buf, format="PNG")
    return buf.getvalue()


def _call_with_retry(fn, scene_id: int):
    """Call ``fn`` with exponential backoff on transient fal errors. Permanent
    client errors — a 4xx (other than 429 rate-limit): bad args, auth, etc. —
    propagate immediately since a retry won't help. Everything else (429, 5xx,
    timeouts, network) is retried up to ``_MAX_RETRIES`` times."""
    last_exc: Exception | None = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 — status-aware triage below
            status = getattr(exc, "status_code", None)
            if status is not None and 400 <= status < 500 and status != 429:
                raise RuntimeError(
                    f"Seedream image generation failed for scene {scene_id} "
                    f"(HTTP {status}): {exc!r}"
                ) from exc
            last_exc = exc
            if attempt == _MAX_RETRIES:
                break
            delay = _RETRY_BASE_DELAY * (2 ** (attempt - 1))
            print(
                f"  [scene {scene_id}] seedream transient error "
                f"({type(exc).__name__}); retry {attempt}/{_MAX_RETRIES - 1} "
                f"in {delay:.1f}s",
                flush=True,
            )
            time.sleep(delay)

    raise RuntimeError(
        f"Seedream image generation failed for scene {scene_id} after "
        f"{_MAX_RETRIES} attempts: {last_exc!r}"
    ) from last_exc
