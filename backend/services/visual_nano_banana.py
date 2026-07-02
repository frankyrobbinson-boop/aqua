"""Nano Banana visual provider — Google Gemini 2.5 Flash Image.

Model: ``gemini-2.5-flash-image``. Cost: ~$0.039 per image (1290 output tokens
billed at $30/M output). Generations are 16:9 by default once requested in the
prompt; ffmpeg later trims/scales to 1920x1080 during scene-clip render so
exact dimensions aren't load-bearing here.

Env:
    GEMINI_API_KEY — get one at https://aistudio.google.com/app/apikey

Caching: per-scene sidecar at ``<output>.cache.json`` keyed by the full prompt
sent to Gemini (baseline prefix + scene visual_description). Editing the
scene's visual_description invalidates only that one image.

Concurrency: ThreadPoolExecutor bounded by ``_GEMINI_CONCURRENCY`` (default 8,
override via env). Gemini's free tier is 10 RPM for image gen at the time of
writing — paid users get much higher caps. We stay polite here; the orchestrator
calls ``fetch_for_scene`` per-scene and may itself parallelize across providers,
but within Nano Banana a single provider instance is the one that bounds
concurrency to Google.
"""

from __future__ import annotations

import io
import json
import os
import threading
import time
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

_MODEL_ID = "gemini-2.5-flash-image"
_GEMINI_CONCURRENCY = int(os.getenv("GEMINI_CONCURRENCY", "8"))
# Gemini 2.5 Flash Image defaults to 1:1 (square) unless an aspect ratio is
# explicitly requested via image_config. YouTube needs 16:9 — hardcode here.
# This is also factored into the cache key so flipping ratios invalidates
# existing images without manual file deletion.
_ASPECT_RATIO = "16:9"

# 16:9 = 1.7778. Tolerance band catches the actual ratios Gemini returns
# (sometimes 1290x720 = 1.7917, sometimes 1280x720 = 1.7778) while still
# rejecting a stray 1:1 (1.0) or 4:3 (1.333) silently-square return.
_ASPECT_RATIO_MIN = 1.760
_ASPECT_RATIO_MAX = 1.796

# Retry policy for transient Gemini failures (rate limit / 5xx / network).
_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 2.0  # seconds; exponential backoff: 2, 4, 8

# Baseline image-direction prefix prepended to every scene's visual_description.
# Kept short and generic for Phase 1 — better per-channel prompt engineering is
# a future-phase task (see project_visuals_future memory).
_BASELINE_PREFIX = (
    "16:9 widescreen cinematic photograph, professional quality, natural "
    "lighting, no text, no watermarks, no logos. Subject: "
)


class NanoBananaProvider(VisualProvider):
    """AI image generation via Gemini 2.5 Flash Image."""

    provider_id = "nano_banana"
    mode = "ai_image"

    def __init__(self) -> None:
        # Bound how many concurrent calls THIS instance makes to Gemini even
        # when the orchestrator spawns N worker threads. A semaphore (not a
        # private pool) is the right tool — it lets the orchestrator decide
        # pool size while we still rate-cap per provider.
        self._gemini_semaphore = threading.Semaphore(_GEMINI_CONCURRENCY)
        # Lazy-resolved Gemini client. Importing the SDK at module load would
        # force every caller (including the registry verifier) to have the
        # package installed; this provider may not even be exercised today.
        self._client = None
        self._client_lock = threading.Lock()
        # Per-project enhanced visual-prompts payload (visual_prompts.json),
        # lazy-loaded on first scene fetch. ``None`` = "not yet loaded";
        # ``{}`` after attempted load = "no file present, run in fallback mode
        # for every scene". Keyed by project_name so a long-lived provider
        # instance handling multiple projects (test scripts, not the live
        # orchestrator) doesn't cross-contaminate prompts.
        self._visual_prompts_cache: dict[str, dict | None] = {}
        self._visual_prompts_lock = threading.Lock()

    # ------------------------------------------------------------------
    # SDK wiring
    # ------------------------------------------------------------------

    def _get_client(self):
        """Lazy-load and configure the google-generativeai client. Raises a
        clear error naming the env var if the key is missing — the spec calls
        this out explicitly so users see ``GEMINI_API_KEY`` in the trace."""
        with self._client_lock:
            if self._client is not None:
                return self._client
            api_key = os.getenv("GEMINI_API_KEY")
            if not api_key:
                raise RuntimeError(
                    "GEMINI_API_KEY not set. Get one at "
                    "https://aistudio.google.com/app/apikey and add it to "
                    "backend/.env"
                )
            try:
                import google.generativeai as genai  # type: ignore
            except ImportError as exc:
                raise RuntimeError(
                    "google-generativeai SDK not installed. Run "
                    "`pip install -r requirements.txt`."
                ) from exc
            genai.configure(api_key=api_key)
            self._client = genai.GenerativeModel(_MODEL_ID)
            return self._client

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

        # Prefer the enhanced prompt from visual_prompt_service if present.
        # The enhancer already incorporates the baseline cinematic language,
        # so we use its prompt VERBATIM — no _BASELINE_PREFIX prepending.
        enhanced = self._lookup_enhanced(project_name, sid)
        if enhanced is not None:
            prompt = enhanced["prompt"]
            source = enhanced["source"]
        else:
            prompt = _BASELINE_PREFIX + query
            source = "fallback"

        # ``source`` makes the cache invalidate on a mode flip even if the
        # exact prompt text happens to collide between enhanced/passthrough.
        cache_key = {"prompt": prompt, "model": _MODEL_ID, "source": source, "aspect_ratio": _ASPECT_RATIO}
        if is_cache_valid(output, cache_key):
            print(f"  [scene {sid}] nano_banana cached -> {output}", flush=True)
            return output

        # Clean up any stale stock-video artifact for this scene id so a
        # mode-flip (stock_video -> ai_image) doesn't leave both an .mp4 and
        # .png that render's path-scan picks unpredictably.
        clean_other_mode_files(footage_dir, sid, keep_ext=".png")

        with self._gemini_semaphore:
            print(
                f"  [scene {sid}] nano_banana generating -> {output}",
                flush=True,
            )
            image_bytes = self._generate(prompt, sid)

        # 16:9 conform: Gemini sometimes silently returns 1:1 despite a prompt
        # request. Center-crop to 16:9 BEFORE writing to disk so the AI scene
        # always produces a usable widescreen image instead of failing.
        image_bytes = _conform_to_16_9(image_bytes, sid)

        with open(output, "wb") as f:
            f.write(image_bytes)

        write_cache(output, cache_key)

        cost_ledger.record(
            project_name,
            stage="visuals",
            provider="gemini",
            model=_MODEL_ID,
            units=1,
            extra={"scene_id": sid},
        )

        return output

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _lookup_enhanced(self, project_name: str, scene_id: int) -> dict | None:
        """Return ``{"prompt": str, "source": "enhanced"|"passthrough"}`` for
        ``scene_id`` from this project's ``visual_prompts.json``, or None if
        the file is missing / the scene is absent / the prompt is empty.

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
                return {"prompt": prompt, "source": source}
        return None

    def _generate(self, prompt: str, scene_id: int) -> bytes:
        """One Gemini image generation call with retry on transient errors.
        Surfaces the final API error verbatim with the scene id attached."""
        client = self._get_client()
        # WHY no generation_config={"image_config": {"aspect_ratio": ...}}:
        # google-generativeai 0.8.x rejects unknown generation_config keys with
        # a hard error from the underlying proto. The aspect ratio is requested
        # in the prompt itself (_BASELINE_PREFIX) and conformed post-decode by
        # _conform_to_16_9. Do NOT re-add this kwarg.
        response = _call_with_retry(
            lambda: client.generate_content(prompt),
            scene_id=scene_id,
        )

        # The 2.5 Flash Image response embeds the PNG bytes in an inline_data
        # part on the first candidate. Defensive against schema drift: walk
        # every part and grab the first inline_data we find.
        candidates = getattr(response, "candidates", None) or []
        for cand in candidates:
            parts = getattr(getattr(cand, "content", None), "parts", None) or []
            for part in parts:
                inline = getattr(part, "inline_data", None)
                if inline and getattr(inline, "data", None):
                    return inline.data
        raise RuntimeError(
            f"Gemini returned no inline_data for scene {scene_id}; "
            f"response.text={getattr(response, 'text', None)!r}"
        )


def _conform_to_16_9(image_bytes: bytes, scene_id: int) -> bytes:
    """Return ``image_bytes`` conformed to 16:9. Gemini sometimes returns a
    square (1:1) image despite the prompt request; rather than fail the scene
    we center-crop to exactly 16:9 so the AI scene always yields a usable
    widescreen image.

    If the decoded ratio is already within the accepted tolerance band the
    ORIGINAL bytes are returned unchanged (no re-encode — avoids needless
    recompression). A totally undecodable image is still a real failure and
    raises, mirroring the prior assertion."""
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
                        # Too tall (e.g. square): keep full width, crop height.
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
            f"Scene {scene_id}: could not decode Gemini PNG to conform aspect "
            f"ratio: {exc!r}"
        ) from exc

    if h <= 0:
        raise RuntimeError(
            f"Scene {scene_id}: Gemini returned image with non-positive height "
            f"({w}x{h})"
        )

    if cropped is None:
        # Already within tolerance — return the original bytes untouched.
        return image_bytes

    cw, ch = cropped.size
    print(
        f"  [scene {scene_id}] nano_banana image was {w}x{h}, "
        f"cropped to 16:9 ({cw}x{ch})",
        flush=True,
    )

    # PNG can't cleanly save every PIL mode (e.g. some palette/alpha combos);
    # fall back to RGB for anything outside the modes PNG handles directly.
    if mode not in ("1", "L", "LA", "I", "P", "RGB", "RGBA"):
        cropped = cropped.convert("RGB")

    buf = io.BytesIO()
    cropped.save(buf, format="PNG")
    return buf.getvalue()


def _call_with_retry(fn, scene_id: int):
    """Call ``fn`` with exponential backoff on transient Google API errors.
    Catches by EXCEPTION TYPE (ResourceExhausted = 429, ServiceUnavailable =
    503, DeadlineExceeded = 504, InternalServerError = 500); permanent errors
    (bad request, auth, etc.) propagate immediately."""
    # Import inline so module load doesn't require google packages installed
    # for callers that never touch this provider.
    from google.api_core import exceptions as gax

    transient = (
        gax.ResourceExhausted,
        gax.ServiceUnavailable,
        gax.DeadlineExceeded,
        gax.InternalServerError,
    )

    last_exc: Exception | None = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            return fn()
        except transient as exc:
            last_exc = exc
            if attempt == _MAX_RETRIES:
                break
            delay = _RETRY_BASE_DELAY * (2 ** (attempt - 1))
            print(
                f"  [scene {scene_id}] nano_banana transient error "
                f"({type(exc).__name__}); retry {attempt}/{_MAX_RETRIES - 1} "
                f"in {delay:.1f}s",
                flush=True,
            )
            time.sleep(delay)
        except Exception as exc:
            raise RuntimeError(
                f"Gemini image generation failed for scene {scene_id}: {exc!r}"
            ) from exc

    raise RuntimeError(
        f"Gemini image generation failed for scene {scene_id} after "
        f"{_MAX_RETRIES} attempts: {last_exc!r}"
    ) from last_exc
