"""Retired manual merge policy for old dealflow funnel."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple


def apply_manual_merge_policy(*args: Any, **kwargs: Any) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    return [], {
        "status": "retired",
        "reason": "Manual/scout names now enter the unranked scout ticker handoff.",
    }
