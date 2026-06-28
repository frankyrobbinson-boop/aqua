"""Pre-generation visual-prompt enhancement.

scene_plan emits short stock-search phrases (Pexels-shaped). For AI image
generators we want richer, model-ready prompts that encode the channel's
visual identity. This service runs one batched Anthropic call across the
scene list and writes ``visual_prompts.json``; the Nano Banana provider looks
each enhanced prompt up by scene id at generation time.

Public:
    generate_visual_prompts(project_name) -> payload dict
    save_visual_prompts(project_name, payload) -> Path
    load_visual_prompts(project_name) -> dict | None
    compute_cache_key(channel_visuals, scenes) -> sha1 hex

Passthrough mode triggers when the channel has no style_description AND no
creative_direction AND character disabled AND no reference images — no LLM
call, just the baseline cinematic prefix attached to visual_description.
Saves cost/latency for channels not yet styled.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from services import cost_ledger
from services.channel_registry import default_channel_id, resolve_channel_visuals
from services.paths import PROJECTS_ROOT

load_dotenv()

_PROMPTS_DIR = Path("prompts")
_ENHANCER_PROMPT_PATH = _PROMPTS_DIR / "visual_prompt_enhancement.md"

# Bump this when compute_cache_key's payload shape changes. Folded into the
# hash so a version bump invalidates every existing visual_prompts.json
# cleanly — no need to ship a backwards-compat migration.
_VISUAL_PROMPT_CACHE_VERSION = 2

# Used only in passthrough mode. The enhancer prompt incorporates this
# language directly when an LLM call is made.
_BASELINE_PREFIX = (
    "16:9 cinematic photograph, professional quality, natural lighting, "
    "no text, no watermarks, no logos. Subject: "
)

# Single call below the threshold; parallelizable chunks at/above. 50/32
# means a typical 10-minute video (70–100 scenes) hits two or three balanced
# chunks instead of one oversized request.
_CHUNK_THRESHOLD = 50
_CHUNK_SIZE = 32

_VISUAL_PROMPT_SCHEMA = {
    "type": "object",
    "properties": {
        "scenes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "prompt": {"type": "string"},
                    "negative_prompt": {"type": "string"},
                },
                "required": ["id", "prompt", "negative_prompt"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["scenes"],
    "additionalProperties": False,
}


def _project_dir(project_name: str) -> Path:
    return PROJECTS_ROOT / project_name


def _visual_prompts_path(project_name: str) -> Path:
    return _project_dir(project_name) / "visual_prompts.json"


def _load_scene_plan(project_name: str) -> dict:
    p = _project_dir(project_name) / "scene_plan.json"
    if not p.exists():
        raise FileNotFoundError(
            f"scene_plan.json not found for {project_name!r}; "
            f"run the scene plan stage first."
        )
    with p.open() as f:
        return json.load(f)


def _load_channel_id(project_name: str) -> str:
    """Read channel from script_config.json with a registry-default fallback."""
    cfg_path = _project_dir(project_name) / "script_config.json"
    if cfg_path.exists():
        try:
            with cfg_path.open() as f:
                cfg = json.load(f)
            if cfg.get("channel"):
                return cfg["channel"]
        except (OSError, json.JSONDecodeError):
            pass
    return default_channel_id()


def load_visual_prompts(project_name: str) -> dict | None:
    p = _visual_prompts_path(project_name)
    if not p.exists():
        return None
    try:
        with p.open() as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def save_visual_prompts(project_name: str, payload: dict) -> Path:
    p = _visual_prompts_path(project_name)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w") as f:
        json.dump(payload, f, indent=2)
    return p


def _enhancer_template_sha1() -> str:
    """SHA-1 of the on-disk enhancer prompt template. Editing the template
    invalidates every cached visual_prompts.json — the prompt IS the model's
    instruction set, so a change should bust the cache."""
    try:
        with _ENHANCER_PROMPT_PATH.open("rb") as f:
            return hashlib.sha1(f.read()).hexdigest()
    except OSError:
        return ""


def compute_cache_key(channel_visuals: dict, scenes: list[dict]) -> str:
    """SHA-1 over the enhancer inputs that should invalidate the cache:
    cache-format version + enhancer template hash + model id + channel visuals
    block + a minimal scene projection (id, segment_id, visual_description,
    narration, emotional_purpose). Edits to scene_plan fields the enhancer
    doesn't see don't bust the cache."""
    model = channel_visuals.get("prompt_enhancement_model") or "claude-haiku-4-5-20251001"
    payload = {
        "_version": _VISUAL_PROMPT_CACHE_VERSION,
        "enhancer_template_sha1": _enhancer_template_sha1(),
        "model": model,
        "channel_visuals": channel_visuals,
        "scenes": [
            {
                "id": int(s["id"]),
                "segment_id": int(s.get("segment_id", 0)),
                "visual_description": s.get("visual_description", ""),
                "narration": s.get("narration", ""),
                "emotional_purpose": s.get("emotional_purpose", ""),
            }
            for s in scenes
        ],
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha1(blob).hexdigest()


def _is_passthrough(cv: dict) -> bool:
    """True iff the channel has no styling configured — cheap-path trigger."""
    if (cv.get("style_description") or "").strip():
        return False
    if (cv.get("creative_direction") or "").strip():
        return False
    if cv.get("character_enabled") or cv.get("reference_image_paths"):
        return False
    return True


def _passthrough_prompt(visual_description: str) -> str:
    return _BASELINE_PREFIX + (visual_description or "").strip()


def _build_passthrough_payload(
    channel_id: str, model: str, cache_key: str, scenes: list[dict]
) -> dict:
    return {
        "version": 1,
        "model": model,
        "channel_id": channel_id,
        "cache_key": cache_key,
        "source": "passthrough",
        "scenes": [
            {
                "id": int(s["id"]),
                "segment_id": int(s.get("segment_id", 0)),
                "prompt": _passthrough_prompt(s.get("visual_description", "")),
                "negative_prompt": "",
            }
            for s in scenes
        ],
    }


def _fill_style_block(template: str, cv: dict) -> str:
    """Substitute {placeholder} fields with channel visuals. Image paths are
    reduced to basenames — Phase 1 doesn't attach bytes, only names as hints."""
    ref_basenames = [Path(p).name for p in (cv.get("reference_image_paths") or [])]
    char_path = cv.get("character_image_path")
    char_basename = Path(char_path).name if char_path else ""
    return (
        template
        .replace("{style_description}", cv.get("style_description") or "(none)")
        .replace("{creative_direction}", cv.get("creative_direction") or "(none)")
        .replace("{reference_image_basenames}", ", ".join(ref_basenames) or "(none)")
        .replace("{character_enabled}", str(bool(cv.get("character_enabled"))))
        .replace("{character_image_basename}", char_basename or "(none)")
        .replace("{character_strength}", str(cv.get("character_strength", 0.7)))
    )


def _scene_input_for_llm(scene: dict) -> dict:
    return {
        "id": int(scene["id"]),
        "segment_title": scene.get("segment_title", ""),
        "narration": scene.get("narration", ""),
        "emotional_purpose": scene.get("emotional_purpose", ""),
        "visual_description": scene.get("visual_description", ""),
        "on_screen_text": scene.get("on_screen_text", ""),
    }


def _call_enhancer(
    client: anthropic.Anthropic,
    model: str,
    system_prompt: str,
    scenes_chunk: list[dict],
    project_name: str | None = None,
) -> list[dict]:
    """One structured-output Anthropic call. Surfaces stop_reason + partial
    text on parse failure (mirrors script_draft_service)."""
    user_payload = {"scenes": [_scene_input_for_llm(s) for s in scenes_chunk]}
    with client.messages.stream(
        model=model,
        max_tokens=8192,
        output_config={"format": {"type": "json_schema", "schema": _VISUAL_PROMPT_SCHEMA}},
        messages=[{
            "role": "user",
            "content": f"{system_prompt}\n\nINPUT:\n{json.dumps(user_payload, indent=2)}",
        }],
    ) as stream:
        response = stream.get_final_message()

    if project_name:
        usage = getattr(response, "usage", None)
        in_tok = getattr(usage, "input_tokens", 0) if usage else 0
        out_tok = getattr(usage, "output_tokens", 0) if usage else 0
        cost_ledger.record(
            project_name,
            stage="visuals",
            provider="anthropic",
            model=model,
            input_tokens=in_tok,
            output_tokens=out_tok,
            extra={"step": "prompt_enhancement"},
        )

    text = next((b.text for b in response.content if b.type == "text"), None)
    if text is None:
        raise RuntimeError(
            f"No text block in enhancer response; block types: "
            f"{[b.type for b in response.content]} "
            f"stop_reason={getattr(response, 'stop_reason', '?')}"
        )
    try:
        return json.loads(text).get("scenes", [])
    except json.JSONDecodeError as e:
        stop_reason = getattr(response, "stop_reason", "?")
        head, tail = text[:400], (text[-400:] if len(text) > 800 else "")
        raise RuntimeError(
            f"Enhancer JSON did not parse (stop_reason={stop_reason}, "
            f"text_len={len(text)}, error={e!r}).\n"
            f"--- first 400 chars ---\n{head}\n--- last 400 chars ---\n{tail}"
        ) from e


def generate_visual_prompts(project_name: str) -> dict:
    """Build the enhanced (or passthrough) visual-prompts payload. Returns the
    dict; does NOT write — caller decides via save_visual_prompts."""
    scenes = _load_scene_plan(project_name).get("scene_intent", []) or []
    if not scenes:
        raise RuntimeError(f"scene_plan for {project_name!r} has no scenes")

    channel_id = _load_channel_id(project_name)
    channel_visuals = resolve_channel_visuals(channel_id)
    model = channel_visuals.get("prompt_enhancement_model") or "claude-haiku-4-5-20251001"
    cache_key = compute_cache_key(channel_visuals, scenes)

    # Cache hit short-circuits the LLM call on no-op re-runs.
    existing = load_visual_prompts(project_name)
    if existing and existing.get("cache_key") == cache_key:
        return existing

    if _is_passthrough(channel_visuals):
        return _build_passthrough_payload(channel_id, model, cache_key, scenes)

    template = _load_enhancer_prompt()
    system_prompt = _fill_style_block(template, channel_visuals)
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    chunks = (
        [scenes[i:i + _CHUNK_SIZE] for i in range(0, len(scenes), _CHUNK_SIZE)]
        if len(scenes) >= _CHUNK_THRESHOLD else [scenes]
    )

    # Sequential — Anthropic SDK is sync and chunks are small; threading isn't
    # worth the complexity yet. Backfill any scene the model dropped with
    # passthrough so every scene id is present in the output.
    enhanced_by_id: dict[int, dict] = {}
    for chunk in chunks:
        for entry in _call_enhancer(client, model, system_prompt, chunk, project_name):
            enhanced_by_id[int(entry["id"])] = entry

    out_scenes: list[dict] = []
    for s in scenes:
        sid = int(s["id"])
        e = enhanced_by_id.get(sid)
        if e and (e.get("prompt") or "").strip():
            prompt, negative = e["prompt"], (e.get("negative_prompt") or "")
        else:
            prompt, negative = _passthrough_prompt(s.get("visual_description", "")), ""
        out_scenes.append({
            "id": sid,
            "segment_id": int(s.get("segment_id", 0)),
            "prompt": prompt,
            "negative_prompt": negative,
        })

    return {
        "version": 1,
        "model": model,
        "channel_id": channel_id,
        "cache_key": cache_key,
        "source": "enhanced",
        "scenes": out_scenes,
    }


def _load_enhancer_prompt() -> str:
    with _ENHANCER_PROMPT_PATH.open() as f:
        return f.read()
