"""Retired hindsight review for old dealflow funnel."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

_DEAL_FLOW_DIR = Path("eval_results/deal_flow")
_PLANS_DIR = Path("eval_results/paper_execution/plans")
_HINDSIGHT_DB = _DEAL_FLOW_DIR / "hindsight.db"


def compute_hindsight(*args: Any, **kwargs: Any) -> Dict[str, Any]:
    return {
        "status": "retired",
        "error": "Old dealflow hindsight is retired; scout names are evaluated after fundamental scoring.",
    }
