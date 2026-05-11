"""Retired source attribution for old dealflow funnel."""

from __future__ import annotations

from typing import Any, Dict


def build_source_attribution(*args: Any, **kwargs: Any) -> Dict[str, Any]:
    return {
        "status": "retired",
        "reason": "Scout handoff now preserves source scouts directly per ticker.",
        "rows": [],
    }
