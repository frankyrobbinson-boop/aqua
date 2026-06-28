"""Shared transforms applied to research before it's injected into a prompt.

Lifted out of script_draft_service so the outline stage can apply the same
strip — the channel voice forbids citing institutions, agencies, studies, or
researchers, but research.json carries `source` fields naming CDC / WHO /
Rutgers / EPA / etc. The model leaks those names into narration despite the
soft voice rule; deleting the data is more reliable than asking the model to
ignore data sitting in front of it.
"""

from __future__ import annotations

import copy


def strip_research_sources(research: dict) -> dict:
    """Return a deep-copied research dict with `source` removed from every
    `key_facts` and `statistics` entry. In-memory only — the on-disk file is
    untouched."""
    stripped = copy.deepcopy(research)
    inner = stripped.get("research", {})
    for key in ("key_facts", "statistics"):
        for entry in inner.get(key, []) or []:
            if isinstance(entry, dict):
                entry.pop("source", None)
    return stripped
