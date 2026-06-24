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

import json
import os
import threading
from pathlib import Path

from dotenv import load_dotenv

from services.visual_provider import (
    VisualProvider,
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

# Baseline image-direction prefix prepended to every scene's visual_description.
# Kept short and generic for Phase 1 — better per-channel prompt engineering is
# a future-phase task (see project_visuals_future memory).
_BASELINE_PREFIX = (
    "16:9 cinematic photograph, professional quality, natural lighting, "
    "no text, no watermarks, no logos. Subject: "
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

        # Also clean up any stale Pexels .mp4 for this scene id so a mode-flip
        # (stock_video -> ai_image) doesn't leave both an .mp4 and .png that
        # render's path-scan picks unpredictably. The sidecar is removed too.
        stale_mp4 = footage_dir / f"scene_{sid:03d}.mp4"
        for path in (stale_mp4, footage_dir / f"scene_{sid:03d}.mp4.cache.json"):
            if path.exists():
                try:
                    path.unlink()
                except OSError:
                    pass

        with self._gemini_semaphore:
            print(
                f"  [scene {sid}] nano_banana generating -> {output}",
                flush=True,
            )
            image_bytes = self._generate(prompt, sid)

        with open(output, "wb") as f:
            f.write(image_bytes)

        write_cache(output, cache_key)
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
                path = Path(f"../projects/{project_name}/visual_prompts.json")
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
        """One Gemini image generation call. Surfaces the API error verbatim
        with the scene id attached — per spec, do not swallow."""
        client = self._get_client()
        try:
            response = client.generate_content(
                prompt,
                generation_config={"image_config": {"aspect_ratio": _ASPECT_RATIO}},
            )
        except Exception as exc:
            raise RuntimeError(
                f"Gemini image generation failed for scene {scene_id}: {exc!r}"
            ) from exc

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
