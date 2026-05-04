"""Observed market event-state helpers.

This module intentionally focuses on observed market shock context only.
Scheduled macro calendar labels should come from a real source later, not
from heuristic date rules.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Callable, Dict, Optional, Tuple


def get_event_state(
    *,
    as_of_date: str,
    config: Optional[Dict[str, Any]] = None,
    market_shock_provider: Optional[Callable[[], Tuple[Optional[float], Optional[float]]]] = None,
) -> Dict[str, Any]:
    config = dict(config or {})
    provider = market_shock_provider or (lambda: (None, None))

    spy_move, vix_jump = provider()
    reasons = []

    if vix_jump is not None and abs(vix_jump) >= float(config.get("dealflow_trigger_vix_jump_pct", 15.0)):
        reasons.append(f"VIX jump {vix_jump:.2f}%")

    if spy_move is not None and abs(spy_move) >= float(config.get("dealflow_trigger_spy_move_pct", 1.5)):
        reasons.append(f"SPY move {spy_move:.2f}%")

    return {
        "as_of_date": as_of_date,
        "observed_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "triggered": len(reasons) > 0,
        "reasons": reasons,
        "metrics": {
            "vix_jump_pct": vix_jump,
            "spy_move_pct": spy_move,
        },
    }
