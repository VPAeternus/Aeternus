"""13F delta scout scoring from latest normalized holdings.

Uses manager_quality scores produced by the backtest runner. This module does not
fetch SEC data; it converts latest normalized 13F deltas into scout candidates.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List

from .core import normalize_13f_events


def build_13f_delta_scout_candidates(
    holdings_rows: Iterable[Dict[str, Any]],
    manager_quality_rows: Iterable[Dict[str, Any]],
    *,
    min_manager_quality: float = 50.0,
) -> List[Dict[str, Any]]:
    quality = {str(row.get("manager_id", "")): float(row.get("manager_quality_score", 0.0) or 0.0) for row in manager_quality_rows}
    events = normalize_13f_events(holdings_rows)
    candidates: Dict[str, Dict[str, Any]] = {}
    for event in events:
        if event.get("action") not in {"new", "add"}:
            continue
        manager_id = str(event.get("manager_id", ""))
        manager_score = quality.get(manager_id, 0.0)
        if manager_score < min_manager_quality:
            continue
        ticker = str(event.get("ticker", "")).upper().strip()
        if not ticker:
            continue
        row = candidates.setdefault(
            ticker,
            {
                "ticker": ticker,
                "source": "13f_delta_scout",
                "managers": [],
                "manager_count": 0,
                "total_delta_shares": 0.0,
                "total_market_value": 0.0,
                "score": 0.0,
            },
        )
        row["managers"].append(
            {
                "manager_id": manager_id,
                "manager_name": event.get("manager_name", manager_id),
                "manager_quality_score": manager_score,
                "action": event.get("action"),
                "filing_date": event.get("filing_date"),
                "report_date": event.get("report_date"),
                "delta_shares": event.get("delta_shares"),
                "market_value": event.get("market_value"),
            }
        )
        row["total_delta_shares"] += float(event.get("delta_shares", 0.0) or 0.0)
        row["total_market_value"] += float(event.get("market_value", 0.0) or 0.0)
    for row in candidates.values():
        row["manager_count"] = len(row["managers"])
        avg_quality = sum(m["manager_quality_score"] for m in row["managers"]) / max(1, row["manager_count"])
        convergence_bonus = min(20.0, max(0, row["manager_count"] - 1) * 5.0)
        value_bonus = min(15.0, row["total_market_value"] / 100_000_000.0)
        row["score"] = round(min(100.0, avg_quality + convergence_bonus + value_bonus), 4)
    return sorted(candidates.values(), key=lambda row: (-row["score"], -row["manager_count"], row["ticker"]))
