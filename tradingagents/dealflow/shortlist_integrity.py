"""Read-only Step 3 shortlist integrity artifact."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List


def _rank_score(candidate: Dict[str, Any]) -> float:
    lane = str(candidate.get("lane", "CORE")).upper()
    if lane == "MOMENTUM":
        return float(candidate.get("asymmetry_score", candidate.get("deal_flow_score", 0.0)) or 0.0)
    return float(candidate.get("core_score", candidate.get("deal_flow_score", 0.0)) or 0.0)


def build_shortlist_integrity_report(
    *,
    as_of_date: str,
    all_scored_candidates: Iterable[Dict[str, Any]],
    shortlist: Dict[str, Any],
    research_queue: Dict[str, Any],
) -> Dict[str, Any]:
    candidates = [dict(row) for row in all_scored_candidates]
    shortlist_candidates = [dict(row) for row in shortlist.get("candidates", [])]
    shortlist_symbols = {
        str(row.get("symbol", "")).upper().strip()
        for row in shortlist_candidates
        if str(row.get("symbol", "")).upper().strip()
    }
    deep_selected_symbols = {
        str(item.get("symbol", "")).upper().strip()
        for item in research_queue.get("items", [])
        if bool(item.get("selected_for_deep")) and str(item.get("symbol", "")).upper().strip()
    }

    eligible_near_miss = [
        dict(row)
        for row in candidates
        if str(row.get("status", "")).upper() == "ACTIVE"
        and str(row.get("symbol", "")).upper().strip()
        and str(row.get("symbol", "")).upper().strip() not in shortlist_symbols
    ]
    eligible_near_miss.sort(
        key=lambda row: (
            -_rank_score(row),
            float(row.get("freshness_hours", 9999.0) or 9999.0),
            str(row.get("symbol", "")),
        )
    )
    near_miss_limit = max(1, int(shortlist.get("top_k", len(shortlist_candidates)) or len(shortlist_candidates) or 1))
    near_miss_eligible = eligible_near_miss[:near_miss_limit]

    selected_for_deep = [
        {
            "symbol": str(item.get("symbol", "")).upper().strip(),
            "lane": item.get("lane"),
            "triage_score": item.get("triage_score"),
            "deal_flow_score": item.get("deal_flow_score"),
            "rank": next(
                (
                    int(candidate.get("rank", 0) or 0)
                    for candidate in shortlist_candidates
                    if str(candidate.get("symbol", "")).upper().strip() == str(item.get("symbol", "")).upper().strip()
                ),
                0,
            ),
        }
        for item in research_queue.get("items", [])
        if bool(item.get("selected_for_deep")) and str(item.get("symbol", "")).upper().strip() in shortlist_symbols
    ]

    top_false_negatives = [
        {
            "symbol": str(row.get("symbol", "")).upper().strip(),
            "lane": row.get("lane"),
            "rank_score": round(_rank_score(row), 4),
            "deal_flow_score": row.get("deal_flow_score"),
            "core_score": row.get("core_score"),
            "momentum_score": row.get("momentum_score"),
            "asymmetry_score": row.get("asymmetry_score"),
        }
        for row in near_miss_eligible[:5]
    ]

    return {
        "as_of_date": as_of_date,
        "rule_snapshot": {
            "top_k": int(shortlist.get("top_k", 0) or 0),
            "shortlist_count": len(shortlist_candidates),
            "near_miss_limit": near_miss_limit,
            "deep_k": int(research_queue.get("deep_k", 0) or 0),
        },
        "groups": {
            "selected_shortlist": shortlist_candidates,
            "near_miss_eligible": near_miss_eligible,
            "selected_for_deep": selected_for_deep,
        },
        "comparisons": {
            "selected_vs_near_miss": {
                "selected_count": len(shortlist_candidates),
                "near_miss_count": len(near_miss_eligible),
            },
            "deep_vs_shortlist": {
                "selected_for_deep_count": len(selected_for_deep),
                "shortlist_count": len(shortlist_candidates),
            },
        },
        "top_false_negatives": top_false_negatives,
        "coverage_summary": {
            "candidate_count": len(candidates),
            "selected_shortlist_count": len(shortlist_candidates),
            "near_miss_count": len(near_miss_eligible),
            "selected_for_deep_count": len(selected_for_deep),
        },
    }
