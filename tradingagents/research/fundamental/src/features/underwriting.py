from __future__ import annotations

from typing import Any

from src.features.common import clean, flag, to_float


DEFAULT_DECISION_RULES = {
    "min_avg_dollar_volume": 500_000,
    "min_market_cap": 0,
    "entry_score_buy_threshold": 75,
    "entry_score_research_threshold": 65,
    "price_vs_signal_soft_limit": 15,
    "price_vs_signal_hard_limit": 50,
    "manual_override_allowed_outcomes": ["approved_buy", "force_watchlist", "force_reject", "ignore_kill_review"],
}


def _truthy(value: Any) -> bool:
    text = clean(value)
    return bool(text) and text not in {"0", "0.0", "false", "False", "FALSE", "none", "None"}


def repricing_theme_underwriting_path(row: dict[str, Any]) -> bool:
    repricing_priority = _truthy(row.get("repricing_momentum_priority"))
    theme_confirmed = (to_float(row.get("theme_tailwind_score")) or 0) > 0 or _truthy(row.get("theme_semicap_datacenter_confirmed"))
    llm_or_monitoring_confirmed = (
        flag(row.get("post_llm_candidate_flag"))
        or clean(row.get("causal_change")) == "3"
        or clean(row.get("positive_repricing_status")) == "repricing_confirmed"
    )
    return repricing_priority and theme_confirmed and llm_or_monitoring_confirmed


def rm_buy_review_flag(row: dict[str, Any]) -> int:
    return int(
        _truthy(row.get("repricing_momentum_priority"))
        or (to_float(row.get("market_repricing_score")) or 0) >= 14
        or _truthy(row.get("repricing_confirmed"))
        or clean(row.get("positive_repricing_status")) == "repricing_confirmed"
    )


def rm_risk_controls(row: dict[str, Any]) -> tuple[float, list[str]]:
    if not _truthy(row.get("repricing_momentum_extension")):
        return 1.0, []

    multiplier = 1.0
    warnings: list[str] = []
    if to_float(row.get("financing_dependence_score")) == -1:
        multiplier *= 0.5
        warnings.append("rm_financing_dependence_half_size")
    if flag(row.get("post_llm_demote_flag")):
        multiplier *= 0.5
        warnings.append("rm_demote_half_size")
    if (to_float(row.get("entry_qoq_pct")) or 0) >= 100:
        warnings.append("rm_entry_qoq_overextended_starter_only")
    if (to_float(row.get("current_price_vs_signal_pct")) or 0) > 50:
        warnings.append("rm_price_vs_signal_overextended_starter_or_watchlist")
    return multiplier, warnings


def evaluate_underwriting_gates(row: dict[str, Any], rules: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = {**DEFAULT_DECISION_RULES, **(rules or {})}
    score = to_float(row.get("entry_score_0_100")) or 0
    blocked: list[str] = []
    warnings: list[str] = []
    override_outcome = clean(row.get("manual_override_outcome"))
    force_pm_underwriting = repricing_theme_underwriting_path(row)
    rm_review = rm_buy_review_flag(row)
    rm_size_multiplier, rm_warnings = rm_risk_controls(row)
    warnings.extend(rm_warnings)

    if flag(row.get("manual_override_flag")) and override_outcome not in cfg["manual_override_allowed_outcomes"]:
        blocked.append("invalid_manual_override_outcome")
    if clean(row.get("monitoring_status")) == "kill_review":
        blocked.append("kill_review")
    if clean(row.get("signal_freshness_status")) == "expired_signal":
        blocked.append("expired_signal")
    if flag(row.get("llm_required_for_full_buy_flag")) and clean(row.get("llm_status")) != "complete":
        blocked.append("llm_required_fields_missing")
    if flag(row.get("extraction_quality_failure")):
        blocked.append("extraction_quality_failure")
    if not flag(row.get("has_identifiable_catalyst")) and not clean(row.get("primary_catalyst")):
        blocked.append("no_identifiable_catalyst")
    if not clean(row.get("invalidation_trigger")):
        blocked.append("invalidation_trigger_undefined")

    adv = to_float(row.get("avg_dollar_volume"))
    if adv is not None and adv < cfg["min_avg_dollar_volume"]:
        blocked.append("liquidity_below_threshold")
    market_cap = to_float(row.get("market_cap"))
    if market_cap is not None and market_cap < cfg["min_market_cap"]:
        blocked.append("market_cap_below_threshold")

    price_vs_signal = to_float(row.get("current_price_vs_signal_pct"))
    if price_vs_signal is not None:
        if price_vs_signal > cfg["price_vs_signal_hard_limit"]:
            blocked.append("price_too_far_above_signal")
        elif price_vs_signal > cfg["price_vs_signal_soft_limit"]:
            warnings.append("price_above_signal_soft_limit")

    if override_outcome == "force_reject":
        decision = "pass"
    elif override_outcome == "force_watchlist":
        decision = "watchlist"
    elif blocked:
        decision = "watchlist" if score >= cfg["entry_score_research_threshold"] else "pass"
    elif score >= cfg["entry_score_buy_threshold"]:
        decision = "approved_buy"
    elif force_pm_underwriting or rm_review:
        decision = "fundamental_review"
    elif score >= cfg["entry_score_research_threshold"]:
        decision = "fundamental_review"
    else:
        decision = "watchlist"

    return {
        "decision_type": decision,
        "blocked_reasons": ";".join(blocked),
        "warning_reasons": ";".join(warnings),
        "manual_override_outcome": override_outcome,
        "force_pm_underwriting_flag": int(force_pm_underwriting),
        "rm_buy_review_flag": rm_review,
        "underwriting_path": "repricing_momentum_theme" if force_pm_underwriting else "standard",
        "rm_risk_size_multiplier": rm_size_multiplier,
    }
