"""Macro regime fit signals for deal flow candidates.

Data source: Grok-sourced per-sector macro cache (manual paste workflow).
When no cache exists, returns neutral score=50 with NO_DATA status.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Iterable, List, Optional

from ..contracts import DealFlowSignal, UniverseRow

# Normalize variant sector names to canonical GICS labels.
_SECTOR_NORMALIZE: Dict[str, str] = {
    "Information Technology": "Technology",
    "Health Care": "Healthcare",
    "Consumer Cyclical": "Consumer Discretionary",
    "Consumer Defensive": "Consumer Staples",
    "Basic Materials": "Materials",
    "Financial Services": "Financials",
    "Financial": "Financials",
}


def collect_macro_signals(universe: Iterable[UniverseRow], *, as_of_date: str = "") -> List[DealFlowSignal]:
    cache = _load_macro_cache(as_of_date) if as_of_date else None
    cache_sectors = cache.get("sectors", {}) if cache else {}
    has_cache = bool(cache_sectors)

    signals: List[DealFlowSignal] = []
    for row in universe:
        raw_sector = str(row.get("sector", "Unknown")).strip()
        sector = _SECTOR_NORMALIZE.get(raw_sector, raw_sector)

        if has_cache:
            sector_entry = cache_sectors.get(sector, {})
            score = max(0.0, min(100.0, float(sector_entry.get("score", 50))))
            source_name = "grok_macro_cache"
            evidence = 6
            freshness = 12.0
            status = "OK"
        else:
            score = 50.0
            source_name = "macro_no_cache"
            evidence = 0
            freshness = 9999.0
            status = "NO_DATA"

        signals.append(
            {
                "symbol": row["symbol"],
                "signal_family": "macro_regime_fit",
                "raw_score": score,
                "z_score": 0.0,
                "direction": _direction_from_score(score),
                "evidence_count": evidence,
                "freshness_hours": freshness,
                "source_status": status,
                "source_name": source_name,
            }
        )

    return signals


def _direction_from_score(score: float) -> str:
    if score >= 60.0:
        return "BULLISH"
    if score <= 40.0:
        return "BEARISH"
    return "NEUTRAL"


# ---------------------------------------------------------------------------
# Macro cache helpers (Grok-sourced data)
# ---------------------------------------------------------------------------

def _macro_cache_path(as_of_date: str) -> str:
    return os.path.join("eval_results", "deal_flow", f"macro_cache_{as_of_date}.json")


def _load_macro_cache(as_of_date: str) -> Optional[Dict[str, Any]]:
    """Load Grok-sourced macro cache. Returns None if absent."""
    path = _macro_cache_path(as_of_date)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _save_macro_cache(as_of_date: str, data: Dict[str, Any]) -> str:
    """Write macro cache to disk. Returns the file path."""
    path = _macro_cache_path(as_of_date)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    return path
