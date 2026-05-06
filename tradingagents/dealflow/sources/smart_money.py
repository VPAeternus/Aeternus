"""Deprecated smart-money collector.

The old implementation mixed a shallow 13F holder check with unofficial Congress
trade data. It is intentionally disabled:
- 13F sourcing is handled by thirteenf_watchlist_scout with PIT backtests.
- Congress trades need their own PIT backtest/scout before promotion.

Kept as a no-op compatibility module so older imports/tests do not break.
"""

from __future__ import annotations

from typing import Iterable, Optional, Dict, List

from ..contracts import DealFlowSignal, UniverseRow


def collect_smart_money_signals(
    universe: Iterable[UniverseRow],
    as_of_date: Optional[str] = None,
    config: Optional[Dict] = None,
) -> List[DealFlowSignal]:
    """Return no signals; legacy smart-money collector is retired."""
    return []
