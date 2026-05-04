"""Live observation helpers for the shadow fundamental SEC signal family."""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List


def _extract_strategy_name(source_name: str) -> str:
    raw = str(source_name or "").strip()
    if ":" in raw:
        return raw.split(":", 1)[1].strip()
    return raw


def build_fundamental_shadow_report(
    as_of_date: str,
    signals: List[Dict[str, Any]],
    shortlist: Dict[str, Any],
    research_queue: Dict[str, Any],
) -> Dict[str, Any]:
    """Build a compact operator/reporting summary for shadow fundamental signals."""
    shadow_signals = [
        dict(signal)
        for signal in signals
        if str(signal.get("signal_family", "")).strip() == "fundamental_factor_shadow"
    ]
    shadow_signals.sort(key=lambda row: float(row.get("raw_score", 0.0) or 0.0), reverse=True)

    shortlist_map = {
        str(candidate.get("symbol", "")).upper().strip(): candidate
        for candidate in shortlist.get("candidates", []) or []
        if str(candidate.get("symbol", "")).strip()
    }
    deep_map = {
        str(item.get("symbol", "")).upper().strip(): bool(item.get("selected_for_deep", False))
        for item in research_queue.get("items", []) or []
        if str(item.get("symbol", "")).strip()
    }

    strategy_name = ""
    if shadow_signals:
        strategy_name = _extract_strategy_name(str(shadow_signals[0].get("source_name", "")))

    status_counts = Counter(str(signal.get("source_status", "NO_DATA") or "NO_DATA") for signal in shadow_signals)
    top_signals: List[Dict[str, Any]] = []
    ok_count = 0
    shortlist_overlap_count = 0
    deep_overlap_count = 0

    for signal in shadow_signals:
        symbol = str(signal.get("symbol", "")).upper().strip()
        if not symbol:
            continue
        source_status = str(signal.get("source_status", "NO_DATA") or "NO_DATA")
        in_shortlist = symbol in shortlist_map
        selected_for_deep = bool(deep_map.get(symbol, False))
        if source_status == "OK":
            ok_count += 1
        if in_shortlist:
            shortlist_overlap_count += 1
        if selected_for_deep:
            deep_overlap_count += 1
        candidate = shortlist_map.get(symbol, {})
        top_signals.append(
            {
                "symbol": symbol,
                "raw_score": round(float(signal.get("raw_score", 0.0) or 0.0), 4),
                "freshness_hours": float(signal.get("freshness_hours", 9999.0) or 9999.0),
                "source_status": source_status,
                "source_name": str(signal.get("source_name", "") or ""),
                "in_shortlist": in_shortlist,
                "selected_for_deep": selected_for_deep,
                "lane": str(candidate.get("lane", "") or ""),
                "rank": candidate.get("rank"),
            }
        )

    return {
        "as_of_date": as_of_date,
        "strategy_name": strategy_name,
        "coverage_summary": {
            "signal_count": len(shadow_signals),
            "ok_count": ok_count,
            "shortlist_overlap_count": shortlist_overlap_count,
            "selected_for_deep_overlap_count": deep_overlap_count,
        },
        "source_status_counts": dict(sorted(status_counts.items())),
        "top_signals": top_signals[:10],
    }
