"""Retired cohort tracker for old dealflow funnel."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

_DEAL_FLOW_DIR = Path("eval_results/deal_flow")
_RESULTS_DIR = Path("results")
_COHORT_DB = _DEAL_FLOW_DIR / "cohort_tracker.db"


def compute_cohort_returns(*args: Any, **kwargs: Any) -> Dict[str, Any]:
    return {"status": "retired", "rows": []}


def compare_cohorts(*args: Any, **kwargs: Any) -> Dict[str, Any]:
    return {"status": "retired", "rows": []}
