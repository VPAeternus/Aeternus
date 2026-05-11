"""Retired miss audit for old dealflow funnel."""

from __future__ import annotations

from typing import Any, Dict


def compute_why_missed(*args: Any, **kwargs: Any) -> Dict[str, Any]:
    return {
        "status": "retired",
        "ticker": str(kwargs.get("ticker") or ""),
        "runs": [],
        "flagged_run_count": 0,
        "lookback_runs_used": 0,
    }
