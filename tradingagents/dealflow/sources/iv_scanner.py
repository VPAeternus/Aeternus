"""Legacy IV compatibility stubs.

The Yahoo-finance earnings IV path has been removed from dealflow. This module
remains only so older tests and monkeypatch targets do not break on import.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from ..contracts import DealFlowSignal, UniverseRow


def scan_earnings_iv(
    days_min: int = 7,
    days_max: int = 14,
    open_positions: Optional[Dict[str, Any]] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    _ = (days_min, days_max, open_positions, dry_run)
    return {
        "force_queue": [],
        "scanned": 0,
        "earnings_approaching": [],
        "covered_call_signals": [],
        "neutral": [],
        "akg_enriched": [],
    }


def collect_earnings_iv_signals(
    universe: Iterable[UniverseRow],
    as_of_date: str,
    config: Optional[Dict[str, Any]] = None,
) -> List[DealFlowSignal]:
    _ = (list(universe), as_of_date, config)
    return []
