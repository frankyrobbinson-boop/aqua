#!/usr/bin/env python3
"""icon_resolver_eval.py -- FREE, offline tuning harness for services.icon_resolver.

Why this exists
---------------
The scene planner emits a loose 1-2 word icon CONCEPT per fact chip (e.g.
"measurement", "sunlight", "yearly schedule"). services.icon_resolver snaps that
concept to a real staged Phosphor glyph -- or to None, when the honest answer is
"no clean symbol fits" (the chip then renders text-only). Getting that mapping
right is a judgement call, so this harness makes it inspectable: it runs the
resolver over a broad, niche-DIVERSE battery of concepts (the common gardening /
how-to callouts PLUS deliberately-unmappable abstractions), prints a
concept -> icon | score | decision table, and writes a handful of representative
{icon, fact} picks for the FREE overlay renderer to draw.

NO API / NO network / NO spend -- pure local dict lookups. Standalone, NOT wired
into the pipeline (mirrors the kb_* / image_model_shootout harness convention).

Guiding rule being tuned FOR
----------------------------
Prefer None (text-only) over a confident-but-wrong icon. Common callout concepts
(measurement, sunlight, duration, temperature, count, cost, warning, schedule,
spacing, location, ...) should resolve to a SENSIBLE glyph; genuinely abstract
concepts (nostalgia, democracy, quantum, philosophy, ...) should gate to None.
Tune MIN_SCORE / MIN_MARGIN and the synonym map in services.icon_resolver until
this table reads well.

How to run
----------
    python3 backend/tools/icon_resolver_eval.py

Outputs
-------
  * stdout   -- the concept -> icon table + decision summary counts
  * /tmp/icon_eval/picks.json  -- ~8 {icon, fact} picks for the overlay renderer
    (includes ONE intentional gated-None -> a text-only chip)
  Then render them (FREE, local) with the printed node command.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Put backend/ on the path so `services.icon_resolver` imports regardless of CWD
# (harness convention: tools tweak sys.path rather than assume a working dir).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from services.icon_resolver import (  # noqa: E402
    MIN_MARGIN,
    MIN_SCORE,
    resolve_icon,
    resolve_icon_verbose,
)

OUT_DIR = Path("/tmp/icon_eval")

# Niche-DIVERSE concept battery. Grouped for reading; order within the table
# follows this list. The last group is expected to gate to None.
CONCEPTS = [
    # measurement / size
    "measurement", "spacing", "planting depth", "size", "distance", "diameter",
    "width", "length",
    # sun / light
    "sunlight", "sun exposure", "full sun", "brightness", "shade", "partial shade",
    # time / schedule
    "duration", "yearly schedule", "timeline", "countdown", "patience", "how long",
    "seasons",
    # water / temperature
    "watering", "moisture", "humidity", "temperature", "heat", "frost",
    # count / number
    "count", "quantity", "how many", "number",
    # warning
    "warning", "caution", "mistake", "danger",
    # location / map
    "location", "place", "map", "area",
    # food / tools
    "food", "tool", "equipment", "digging", "pruning",
    # money
    "cost", "price", "budget", "cash",
    # weather / nature
    "weather", "wind", "rain", "snow", "growth", "leaf", "tree", "mountain",
    # structural / misc sensible
    "checklist", "steps", "target", "repeat", "speed", "fire",
    # deliberately UNMAPPABLE -> expect NONE (proves the gate)
    "nostalgia", "democracy", "quantum", "philosophy", "irony", "freedom",
]

# Representative picks the overlay renderer draws: (concept, fact-card text). The
# icon is whatever the resolver returns for the concept (may be None). The LAST
# pair is an intentional gated-None -> a text-only chip.
PICK_SPECS = [
    ("temperature", "Keep above 60°F"),
    ("duration", "Ready in 60 days"),
    ("spacing", "Space 18 inches apart"),
    ("yearly schedule", "Divide every 2-3 years"),
    ("sunlight", "6 hours of sun"),
    ("cost", "Under $5 a plant"),
    ("count", "3 seeds per hole"),
    ("nostalgia", "The old-timer's trick"),  # intentional gated-None -> text-only
]


def _decision_label(decision: str) -> str:
    return "NONE" if decision == "none" else decision


def main() -> None:
    print(f"icon_resolver_eval -- MIN_SCORE={MIN_SCORE}  MIN_MARGIN={MIN_MARGIN}\n")

    # ---- concept -> icon table ----
    header = f"{'concept':<20} {'icon':<18} {'score':>5}  decision"
    print(header)
    print("-" * len(header))
    counts = {"exact": 0, "synonym": 0, "fuzzy": 0, "none": 0}
    for concept in CONCEPTS:
        v = resolve_icon_verbose(concept)
        counts[v["decision"]] += 1
        icon = v["icon"] if v["icon"] is not None else "—"  # em dash
        score = "-" if v["score"] is None else str(v["score"])
        print(f"{concept:<20} {icon:<18} {score:>5}  {_decision_label(v['decision'])}")

    # ---- summary ----
    total = len(CONCEPTS)
    resolved = total - counts["none"]
    print("\nsummary:")
    print(f"  total concepts : {total}")
    print(f"  resolved       : {resolved}  (exact {counts['exact']}, "
          f"synonym {counts['synonym']}, fuzzy {counts['fuzzy']})")
    print(f"  none (gated)   : {counts['none']}")

    # ---- picks for the renderer ----
    picks = [{"icon": resolve_icon(concept), "fact": fact} for concept, fact in PICK_SPECS]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    picks_path = OUT_DIR / "picks.json"
    picks_path.write_text(json.dumps(picks, indent=2) + "\n")

    print("\npicks (concept -> icon | fact):")
    for (concept, fact), pick in zip(PICK_SPECS, picks):
        icon = pick["icon"] if pick["icon"] is not None else "— (text-only)"
        print(f"  {concept:<18} {icon:<20} \"{fact}\"")
    print(f"\nwrote {picks_path}")

    # ---- render command (FREE, local) ----
    print("\nRender the picks (FREE, local overlay render):")
    print(f"  cd frontend && node scripts/render-ost-overlays.mjs "
          f"--picks={picks_path} --out-dir={OUT_DIR}")


if __name__ == "__main__":
    main()
