"""Provider-agnostic interface for fetching/generating per-scene footage.

Concrete providers (Pexels stock video, Nano Banana AI image, future Veo /
Imagen / Grok) implement ``VisualProvider``. The orchestrator in
``visual_service`` consumes the interface, not the concrete classes — adding a
new provider is one class + one registry entry.

Each provider is responsible for placing one footage file per scene at
``../projects/<name>/footage/scene_<sid:03d>.<ext>`` (PNG for stills, MP4 for
clips) and writing a ``<output>.cache.json`` sidecar so re-runs can skip
unchanged scenes. The cache helper here is the shared default — providers may
key it on whatever fields make sense (visual_description hash, stock_id,
generation prompt, etc).
"""

from __future__ import annotations

import hashlib
import json
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


def cache_path_for(output_path: str | Path) -> str:
    """Sidecar path: ``<output>.cache.json``. Mirrors the convention used by
    ``visual_pexels`` and ``assembly_service`` so a future on-disk audit script
    can rely on one extension."""
    return str(output_path) + ".cache.json"


def hash_visual_description(scene: dict) -> str:
    """SHA-1 of the scene's normalized visual_description. Stable across runs.

    Used as the default cache key so editing a scene's query invalidates that
    scene's footage (and only that scene's). Hash rather than raw text keeps
    sidecars compact and tolerant of whitespace edits."""
    query = (scene.get("visual_description") or "").strip()
    return hashlib.sha1(query.encode("utf-8")).hexdigest()


def is_cache_valid(output_path: str | Path, expected: dict[str, Any]) -> bool:
    """True iff ``output_path`` exists with size > 0 AND its sidecar's keys all
    match ``expected``. Any unrecognized key in the sidecar is ignored — only
    the keys the caller asks about are checked, so providers can add their own
    fields (stock_id, request_id, model, etc.) without breaking old caches."""
    out = str(output_path)
    sidecar = cache_path_for(out)
    if not (os.path.exists(out) and os.path.exists(sidecar)):
        return False
    try:
        if os.path.getsize(out) == 0:
            return False
    except OSError:
        return False
    try:
        with open(sidecar) as f:
            cache = json.load(f)
    except (OSError, json.JSONDecodeError):
        return False
    return all(cache.get(k) == v for k, v in expected.items())


def write_cache(output_path: str | Path, payload: dict[str, Any]) -> None:
    """Write the sidecar AFTER the output file is fully on disk. Callers must
    not invoke this until the output is finalized — a sidecar pointing at a
    half-written file would mark a corrupt clip as a cache hit."""
    with open(cache_path_for(output_path), "w") as f:
        json.dump(payload, f)


class VisualProvider(ABC):
    """One footage source (stock library, AI image model, AI video model).

    Subclasses MUST set ``provider_id`` and ``mode`` as class attributes and
    implement ``fetch_for_scene``. The id must match the entry in
    ``prompts/visual_providers.json``; the registry uses it for lookup. ``mode``
    is one of the modes declared in the same file (ai_image, ai_video,
    stock_image, stock_video).
    """

    provider_id: str = ""
    mode: str = ""

    @abstractmethod
    def fetch_for_scene(self, project_name: str, scene: dict) -> Path:
        """Produce a footage file for ``scene`` and return its path.

        Implementations should:
          1) Check ``is_cache_valid`` against their provider-specific cache key
             and skip work on a hit.
          2) On a miss, generate/download the file to
             ``../projects/<project_name>/footage/scene_<sid:03d>.<ext>``.
          3) Call ``write_cache`` AFTER the output is fully written.
          4) Raise on failure with the scene id in the error — do not swallow.
        """


def footage_dir_for(project_name: str) -> Path:
    """Canonical per-project footage directory. Created if absent so providers
    don't each re-implement the mkdir dance."""
    p = Path(f"../projects/{project_name}/footage")
    p.mkdir(parents=True, exist_ok=True)
    return p


# Set of footage extensions any provider may produce. Used by
# clean_other_mode_files to know what to sweep on a mode flip.
_FOOTAGE_EXTS = (".png", ".mp4")


def clean_other_mode_files(
    footage_dir: Path, scene_id: int, keep_ext: str
) -> None:
    """Delete any scene_<id>.<ext> + matching sidecar for extensions OTHER than
    ``keep_ext`` so a mode flip (e.g., stock_video -> ai_image) doesn't leave
    both an .mp4 and .png that render's path-scan picks unpredictably.

    Providers call this AFTER a cache miss decides it'll regenerate. Safe to
    call when nothing to clean — missing files are silently skipped."""
    keep = keep_ext if keep_ext.startswith(".") else f".{keep_ext}"
    for ext in _FOOTAGE_EXTS:
        if ext == keep:
            continue
        primary = footage_dir / f"scene_{scene_id:03d}{ext}"
        sidecar = footage_dir / f"scene_{scene_id:03d}{ext}.cache.json"
        for path in (primary, sidecar):
            if path.exists():
                try:
                    path.unlink()
                except OSError:
                    pass
