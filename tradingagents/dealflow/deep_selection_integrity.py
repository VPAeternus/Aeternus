"""Read-only Step 4 deep-selection integrity artifact."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List


def _normalized_symbol(row: Dict[str, Any]) -> str:
    return str(row.get("symbol", "")).upper().strip()


def _selection_kind(item: Dict[str, Any]) -> str:
    source = str(item.get("source", "")).upper().strip()
    if source == "MANUAL":
        return "MANUAL"
    if source == "IV_FORCE_QUEUE":
        return "IV_FORCE_QUEUE"
    if source == "PORTFOLIO":
        return "PORTFOLIO"
    return "AUTO"


def _selected_row(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "symbol": _normalized_symbol(item),
        "lane": item.get("lane"),
        "triage_score": item.get("triage_score"),
        "deal_flow_score": item.get("deal_flow_score"),
        "source": item.get("source"),
        "source_detail": item.get("source_detail"),
        "selection_kind": _selection_kind(item),
    }


def _near_miss_row(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "symbol": _normalized_symbol(item),
        "lane": item.get("lane"),
        "triage_score": item.get("triage_score"),
        "deal_flow_score": item.get("deal_flow_score"),
        "source": item.get("source"),
        "source_detail": item.get("source_detail"),
    }


def build_deep_selection_integrity_report(
    *,
    as_of_date: str,
    shortlist: Dict[str, Any],
    research_queue: Dict[str, Any],
) -> Dict[str, Any]:
    shortlist_symbols = {
        _normalized_symbol(candidate)
        for candidate in shortlist.get("candidates", [])
        if _normalized_symbol(candidate)
    }
    queue_items = [dict(item) for item in research_queue.get("items", [])]
    selected_for_deep = [
        _selected_row(item)
        for item in queue_items
        if bool(item.get("selected_for_deep")) and _normalized_symbol(item)
    ]
    selected_symbols = {row["symbol"] for row in selected_for_deep}

    near_miss_candidates = [
        dict(item)
        for item in queue_items
        if not bool(item.get("selected_for_deep"))
        and _normalized_symbol(item)
        and _normalized_symbol(item) in shortlist_symbols
    ]
    near_miss_candidates.sort(
        key=lambda item: (
            -float(item.get("triage_score", 0.0) or 0.0),
            float(item.get("evidence", {}).get("freshness_hours", 9999.0) or 9999.0),
            _normalized_symbol(item),
        )
    )

    near_miss_limit = max(1, len(selected_for_deep) or int(research_queue.get("deep_k", 0) or 0) or 1)
    near_miss_eligible = [_near_miss_row(item) for item in near_miss_candidates[:near_miss_limit]]

    injected_selected = [
        row for row in selected_for_deep
        if row["selection_kind"] in {"MANUAL", "IV_FORCE_QUEUE", "PORTFOLIO"}
    ]

    top_false_negatives = near_miss_eligible[:5]

    auto_selected_count = sum(1 for row in selected_for_deep if row["selection_kind"] == "AUTO")
    manual_selected_count = sum(1 for row in selected_for_deep if row["selection_kind"] == "MANUAL")
    iv_force_selected_count = sum(1 for row in selected_for_deep if row["selection_kind"] == "IV_FORCE_QUEUE")
    portfolio_selected_count = sum(1 for row in selected_for_deep if row["selection_kind"] == "PORTFOLIO")

    return {
        "as_of_date": as_of_date,
        "rule_snapshot": {
            "deep_k": int(research_queue.get("deep_k", 0) or 0),
            "selected_count": len(selected_for_deep),
            "near_miss_limit": near_miss_limit,
            "auto_selected_count": auto_selected_count,
            "manual_selected_count": manual_selected_count,
            "iv_force_selected_count": iv_force_selected_count,
            "portfolio_selected_count": portfolio_selected_count,
        },
        "groups": {
            "selected_for_deep": selected_for_deep,
            "near_miss_eligible": near_miss_eligible,
            "injected_selected": injected_selected,
        },
        "comparisons": {
            "selected_vs_near_miss": {
                "selected_count": len(selected_for_deep),
                "near_miss_count": len(near_miss_eligible),
            },
            "injected_vs_selected": {
                "injected_selected_count": len(injected_selected),
                "selected_count": len(selected_for_deep),
            },
        },
        "top_false_negatives": top_false_negatives,
        "coverage_summary": {
            "shortlist_count": len(shortlist_symbols),
            "queue_item_count": len(queue_items),
            "selected_for_deep_count": len(selected_for_deep),
            "near_miss_count": len(near_miss_eligible),
            "injected_selected_count": len(injected_selected),
            "selected_shortlist_overlap_count": len(selected_symbols & shortlist_symbols),
        },
    }
