"""Retired artifact writer for old dealflow funnel."""

from __future__ import annotations

from typing import Any, Dict


def write_collect_artifacts(*args: Any, **kwargs: Any) -> Dict[str, Any]:
    return {
        "status": "retired",
        "reason": "Use scout_ticker_summary.persist_scout_ticker_summary instead.",
    }
