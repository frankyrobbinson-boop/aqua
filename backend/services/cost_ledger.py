"""Per-project cost ledger.

Writes to ``<projects_root>/<name>/cost_ledger.json`` (a JSON array, NOT JSONL —
the file is small enough that a flat array stays cheap to load and easy to
diff). Every meaningful billable call (LLM token consumption, image
generation, TTS character spend, stock-clip fetches) appends one entry.

Each entry records the provider, model, stage, units consumed, and an
estimated USD cost so the frontend can surface a running total without
having to know provider price tables.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from services.paths import PROJECTS_ROOT

# Atomic-append guard. JSON arrays can't be appended-to like JSONL, so we
# read-modify-write under a process-level lock. Concurrent multi-process
# writers aren't supported — the orchestrator is single-process today.
_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Price tables
# ---------------------------------------------------------------------------
#
# Anthropic per-MTok rates (USD). Sonnet 4.6 = $3/$15, Opus 4.7 = $5/$25,
# Haiku 4.5 = $1/$5. OpenAI GPT-5 = $1.25/$10, GPT-5-mini = $0.25/$2 per MTok
# (PLACEHOLDER — verify against current OpenAI pricing). Nano Banana = $0.039
# per image.
# ElevenLabs = $0.00030 per character (PLACEHOLDER — depends on plan tier).
# Pexels = $0 per clip (free under their license for our usage).

_TOKEN_PRICES: dict[str, dict[str, tuple[float, float]]] = {
    "anthropic": {
        "claude-sonnet-4-6": (3.0, 15.0),
        "claude-opus-4-7": (5.0, 25.0),
        "claude-haiku-4-5-20251001": (1.0, 5.0),
    },
    "openai": {
        "gpt-5": (1.25, 10.0),
        "gpt-5-mini": (0.25, 2.0),
    },
}

_UNIT_PRICES: dict[str, dict[str, float]] = {
    "gemini": {
        "gemini-2.5-flash-image": 0.039,
    },
    "elevenlabs": {
        # Per-character flat rate, independent of model id.
        "*": 0.00030,
    },
    "pexels": {
        "*": 0.0,
    },
}


def _per_mtok(input_tokens: int, output_tokens: int, rates: tuple[float, float]) -> float:
    in_rate, out_rate = rates
    return (input_tokens / 1_000_000.0) * in_rate + (output_tokens / 1_000_000.0) * out_rate


def estimate_token_cost(
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> float:
    """USD cost estimate for a token-priced call. Returns 0.0 when the model
    isn't in the price table — caller still records the spend with units so a
    missing price doesn't lose the entry."""
    table = _TOKEN_PRICES.get(provider)
    if not table:
        return 0.0
    rates = table.get(model)
    if not rates:
        return 0.0
    return _per_mtok(input_tokens, output_tokens, rates)


def estimate_unit_cost(provider: str, model: str, units: int | float) -> float:
    """USD cost estimate for a per-unit call (images, characters, clips).
    Falls back to a provider-wide "*" rate when the specific model isn't
    listed."""
    table = _UNIT_PRICES.get(provider)
    if not table:
        return 0.0
    price = table.get(model)
    if price is None:
        price = table.get("*")
    if price is None:
        return 0.0
    return float(units) * price


# ---------------------------------------------------------------------------
# IO
# ---------------------------------------------------------------------------

def _project_path(project_name: str) -> Path:
    return PROJECTS_ROOT / project_name


def _ledger_path(project_name: str) -> Path:
    return _project_path(project_name) / "cost_ledger.json"


def _read(project_name: str) -> list[dict]:
    p = _ledger_path(project_name)
    if not p.exists():
        return []
    try:
        with p.open() as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return data


def _atomic_write(project_name: str, entries: list[dict]) -> None:
    """Tempfile + os.replace so a concurrent reader never sees a torn file.
    Mirrors save_edl."""
    p = _ledger_path(project_name)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".cost_ledger.", suffix=".tmp", dir=str(p.parent))
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(entries, f, indent=2)
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def record(
    project_name: str,
    stage: str,
    provider: str,
    model: str,
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
    units: int | float | None = None,
    est_cost_usd: float | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Append one billable-call entry to the project's cost_ledger.json.

    Cost auto-computed when ``est_cost_usd`` is None: token rates if
    input_tokens/output_tokens are present, else unit rates if ``units`` is
    set, else 0.0. Caller can pre-compute and pass an override for cases the
    helpers don't cover (rare).
    """
    if est_cost_usd is None:
        if input_tokens or output_tokens:
            est_cost_usd = estimate_token_cost(provider, model, input_tokens, output_tokens)
        elif units is not None:
            est_cost_usd = estimate_unit_cost(provider, model, units)
        else:
            est_cost_usd = 0.0

    entry: dict[str, Any] = {
        "ts": time.time(),
        "stage": stage,
        "provider": provider,
        "model": model,
        "input_tokens": int(input_tokens or 0),
        "output_tokens": int(output_tokens or 0),
        "units": float(units) if units is not None else None,
        "est_cost_usd": round(float(est_cost_usd), 6),
    }
    if extra:
        entry["extra"] = extra

    with _lock:
        entries = _read(project_name)
        entries.append(entry)
        _atomic_write(project_name, entries)


def total(project_name: str) -> dict:
    """Aggregate the project ledger.

    Returns ``{"total_usd": float, "by_stage": {...}, "by_provider": {...},
    "entries": [...]}``. Returns the zero shape when the file is missing so
    the frontend can render ``$0.00`` for fresh projects without branching."""
    entries = _read(project_name)
    by_stage: dict[str, float] = {}
    by_provider: dict[str, float] = {}
    total_usd = 0.0
    for e in entries:
        cost = float(e.get("est_cost_usd") or 0.0)
        total_usd += cost
        stage = e.get("stage") or "unknown"
        provider = e.get("provider") or "unknown"
        by_stage[stage] = round(by_stage.get(stage, 0.0) + cost, 6)
        by_provider[provider] = round(by_provider.get(provider, 0.0) + cost, 6)
    return {
        "total_usd": round(total_usd, 6),
        "by_stage": by_stage,
        "by_provider": by_provider,
        "entries": entries,
    }
