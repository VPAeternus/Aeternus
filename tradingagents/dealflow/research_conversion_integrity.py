"""Read-only Step 5 research conversion integrity artifact."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional


FRESH_SUCCESS_STATUSES = {"SUCCESS", "SUCCESS_QUICK"}
CACHED_SUCCESS_STATUSES = {"SUCCESS_CACHED", "SUCCESS_QUICK_FALLBACK"}


def _normalized_symbol(row: Dict[str, Any]) -> str:
    return str(row.get("symbol", "")).upper().strip()


def _portfolio_symbols(plan: Optional[Dict[str, Any]]) -> set[str]:
    if not isinstance(plan, dict):
        return set()
    return {
        _normalized_symbol(order)
        for order in plan.get("orders", [])
        if _normalized_symbol(order)
    }


def _integrity_group(item: Dict[str, Any]) -> str:
    selected = bool(item.get("selected_for_deep"))
    mode = str(item.get("analysis_mode", "DEEP")).upper().strip()
    status = str(item.get("status", "")).upper().strip()

    if selected and mode == "DEEP":
        if status in FRESH_SUCCESS_STATUSES:
            return "deep_success"
        if status in CACHED_SUCCESS_STATUSES:
            return "deep_cached"
        return "deep_failed"

    if status in FRESH_SUCCESS_STATUSES:
        return "quick_success"
    if status in CACHED_SUCCESS_STATUSES:
        return "quick_cached"
    return "quick_failed"


def _candidate_record(item: Dict[str, Any], portfolio_symbols: set[str]) -> Dict[str, Any]:
    symbol = _normalized_symbol(item)
    return {
        "symbol": symbol,
        "selected_for_deep": bool(item.get("selected_for_deep")),
        "analysis_mode": str(item.get("analysis_mode", "")),
        "status": str(item.get("status", "")),
        "analysis_report_found": bool(item.get("analysis_report_found")),
        "aeternus_score": item.get("aeternus_score"),
        "recommendation": item.get("recommendation"),
        "portfolio_included": symbol in portfolio_symbols,
        "realized_horizons": dict(item.get("realized_horizons", {})),
        "integrity_group": _integrity_group(item),
    }


def _group_rows(records: Iterable[Dict[str, Any]], group_name: str) -> List[Dict[str, Any]]:
    return [row for row in records if str(row.get("integrity_group", "")) == group_name]


def _rate(rows: List[Dict[str, Any]], predicate) -> Optional[float]:
    if not rows:
        return None
    return round(sum(1.0 for row in rows if predicate(row)) / float(len(rows)), 4)


def build_research_conversion_integrity_report(
    *,
    as_of_date: str,
    batch_summary: Dict[str, Any],
    portfolio_plan: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    items = [dict(item) for item in batch_summary.get("items", []) if isinstance(item, dict)]
    portfolio_symbols = _portfolio_symbols(portfolio_plan)
    records = [_candidate_record(item, portfolio_symbols) for item in items if _normalized_symbol(item)]

    groups = {
        "deep_success": _group_rows(records, "deep_success"),
        "deep_cached": _group_rows(records, "deep_cached"),
        "deep_failed": _group_rows(records, "deep_failed"),
        "quick_success": _group_rows(records, "quick_success"),
        "quick_cached": _group_rows(records, "quick_cached"),
        "quick_failed": _group_rows(records, "quick_failed"),
    }
    group_counts = {name: len(rows) for name, rows in groups.items()}

    deep_rows = groups["deep_success"] + groups["deep_cached"] + groups["deep_failed"]
    quick_rows = groups["quick_success"] + groups["quick_cached"] + groups["quick_failed"]
    fresh_rows = groups["deep_success"] + groups["quick_success"]
    cached_rows = groups["deep_cached"] + groups["quick_cached"]

    return {
        "as_of_date": as_of_date,
        "rule_snapshot": {
            "requested": int(batch_summary.get("requested", 0) or 0),
            "processed": int(batch_summary.get("processed", 0) or 0),
            "include_unselected": bool(batch_summary.get("include_unselected")),
            "quick_unselected": bool(batch_summary.get("quick_unselected")),
            "per_item_timeout_seconds": int(batch_summary.get("per_item_timeout_seconds", 0) or 0),
            "portfolio_plan_found": bool(portfolio_plan),
        },
        "group_counts": group_counts,
        "candidate_records": records,
        "groups": groups,
        "comparisons": {
            "deep_vs_quick": {
                "deep_count": len(deep_rows),
                "quick_count": len(quick_rows),
                "deep_usable_report_rate": _rate(deep_rows, lambda row: bool(row.get("analysis_report_found"))),
                "quick_usable_report_rate": _rate(quick_rows, lambda row: bool(row.get("analysis_report_found"))),
                "deep_portfolio_conversion_rate": _rate(deep_rows, lambda row: bool(row.get("portfolio_included"))),
                "quick_portfolio_conversion_rate": _rate(quick_rows, lambda row: bool(row.get("portfolio_included"))),
            },
            "fresh_vs_cached": {
                "fresh_count": len(fresh_rows),
                "cached_count": len(cached_rows),
                "fresh_portfolio_conversion_rate": _rate(fresh_rows, lambda row: bool(row.get("portfolio_included"))),
                "cached_portfolio_conversion_rate": _rate(cached_rows, lambda row: bool(row.get("portfolio_included"))),
            },
        },
        "coverage_summary": {
            "candidate_count": len(records),
            "portfolio_included_count": sum(1 for row in records if bool(row.get("portfolio_included"))),
            "analysis_report_found_count": sum(1 for row in records if bool(row.get("analysis_report_found"))),
            "realized_horizon_count": sum(1 for row in records if bool(row.get("realized_horizons"))),
        },
    }
