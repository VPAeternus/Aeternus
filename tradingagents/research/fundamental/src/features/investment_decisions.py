from __future__ import annotations


TRANSITIONS = {
    "new_signal": {"fundamental_review", "llm_pending"},
    "llm_pending": {"fundamental_review", "watchlist", "manually_rejected"},
    "fundamental_review": {"approved_buy", "starter_position", "watchlist", "manually_rejected"},
    "approved_buy": {"active_position"},
    "starter_position": {"active_position", "early_stress", "midpoint_stress", "kill_review", "exited"},
    "watchlist": {"active_watchlist"},
    "active_position": {"early_stress", "midpoint_stress", "kill_review", "exited", "refreshed_by_new_quarter"},
    "active_watchlist": {"fundamental_review", "kill_review", "expired"},
    "kill_review": {"exited", "manually_rejected", "refreshed_by_new_quarter"},
}


def transition_candidate_state(current_state: str, event: str) -> str:
    if event in TRANSITIONS.get(current_state, set()):
        return event
    raise ValueError(f"invalid transition: {current_state} -> {event}")


def build_investment_decision(row: dict, *, decision_date: str) -> dict:
    decision_type = row.get("decision_type") or ("watchlist" if row.get("entry_score_0_100", 0) else "pass")
    return {
        "ticker": row.get("ticker", ""),
        "quarter": row.get("quarter", ""),
        "decision_date": decision_date,
        "decision_type": decision_type,
        "decision_price": row.get("current_price", row.get("entry_open", "")),
        "entry_score_0_100": row.get("entry_score_0_100", ""),
        "active_monitoring_score_0_100": row.get("active_monitoring_score_0_100", ""),
        "monitoring_status": row.get("monitoring_status", ""),
        "investment_decision_score": row.get("dashboard_score_0_100", row.get("entry_score_0_100", "")),
        "position_size": row.get("position_size", ""),
        "primary_thesis": row.get("driver_summary", ""),
        "primary_catalyst": row.get("primary_catalyst", row.get("driver_summary", "")),
        "valuation_summary": row.get("valuation_summary", ""),
        "risk_summary": row.get("risk_summary", row.get("bear_case_summary", "")),
        "invalidation_trigger": row.get("invalidation_trigger", ""),
        "decision_notes": row.get("blocked_reasons", ""),
        "one_sentence_thesis": row.get("one_sentence_thesis", row.get("driver_summary", "")),
        "why_now": row.get("why_now", ""),
        "main_causal_driver": row.get("driver_summary", ""),
        "expected_upside": row.get("expected_upside", ""),
        "expected_downside": row.get("expected_downside", ""),
        "valuation_view": row.get("valuation_view", ""),
        "liquidity_view": row.get("liquidity_view", ""),
        "macro_theme_view": row.get("macro_theme_view", ""),
        "position_size_rationale": row.get("position_size_rationale", ""),
        "next_review_date": row.get("next_review_date", ""),
    }
