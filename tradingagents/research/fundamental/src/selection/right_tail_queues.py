"""Right-tail visibility queues for fundamental research outputs."""
from __future__ import annotations

from typing import Any, Mapping

from .signal_utils import HP_SIGNAL_FIELDS, RM_SIGNAL_FIELDS, signal_bucket, signal_count, to_float, truthy

DEMOTE_SEVERITIES = {"none", "soft", "hard", "unknown"}
HARD_DEMOTE_REASON_CODES = {
    "going_concern",
    "accounting_quality",
    "fraud_or_integrity",
    "broken_thesis",
    "missing_filings",
}
SOFT_DEMOTE_REASON_CODES = {
    "weak_fundamentals",
    "cyclical_trough",
    "high_leverage",
    "inventory_digesting",
    "margin_pressure",
    "customer_concentration",
    "liquidity_risk",
    "dilution_risk",
}
DEMOTE_REASON_CODES = HARD_DEMOTE_REASON_CODES | SOFT_DEMOTE_REASON_CODES

FORBIDDEN_RIGHT_TAIL_ROUTING_COLUMNS = {
    "return_10d_pct",
    "return_20d_pct",
    "return_30d_pct",
    "return_60d_pct",
    "return_90d_pct",
    "winner_90d_30pct",
    "loser_90d_minus30pct",
    "monitoring_score_0_100",
    "active_monitoring_score_0_100",
    "final_rank_score_0_100",
    "rank_score_0_100",
    "current_return_pct",
    "return_since_signal_pct",
    "return_since_purchase_pct",
}

SUPPLIER_THEME_ROLES = {
    "supplier",
    "infrastructure_provider",
    "commodity_exposure",
    "turnaround_with_theme_tailwind",
}
SUPPLIER_KEYWORDS = ("bottleneck", "semicap", "semi cap", "materials", "optical", "supplier")
CORE_RM_SIGNAL_FIELDS = tuple(field for field in RM_SIGNAL_FIELDS if field != "rm_buy_review_flag")


def _clean(value: Any) -> str:
    return str(value if value is not None else "").strip()


def _clean_lower(value: Any) -> str:
    return _clean(value).lower()


def _single_rm_signal_bucket(row: Mapping[str, Any]) -> bool:
    return signal_bucket(row, CORE_RM_SIGNAL_FIELDS)[0] == "1"


def _theme_text(row: Mapping[str, Any]) -> str:
    values = [
        row.get("primary_theme"),
        row.get("theme_tags"),
        row.get("theme_evidence_summary"),
    ]
    return " ".join(_clean(v).lower() for v in values if _clean(v))


def has_active_theme_supplier_role(row: Mapping[str, Any]) -> bool:
    role = _clean_lower(row.get("theme_role"))
    if role in SUPPLIER_THEME_ROLES:
        return True
    text = _theme_text(row)
    return any(keyword in text for keyword in SUPPLIER_KEYWORDS)


def classify_demote_severity(row: Mapping[str, Any]) -> str:
    raw = _clean_lower(row.get("post_llm_demote_severity"))
    if raw in DEMOTE_SEVERITIES:
        return raw
    if not truthy(row.get("post_llm_demote_flag")):
        return "none"
    reason = _clean_lower(row.get("post_llm_demote_reason_code"))
    if reason in HARD_DEMOTE_REASON_CODES:
        return "hard"
    if reason in SOFT_DEMOTE_REASON_CODES:
        return "soft"
    return "unknown"


def compute_right_tail_evidence_score(row: Mapping[str, Any]) -> tuple[float, dict[str, float]]:
    parts: dict[str, float] = {}
    if _single_rm_signal_bucket(row):
        parts["single_rm_signal_bucket"] = 20
    if truthy(row.get("rm_buy_review_flag")):
        parts["rm_buy_review_flag"] = 12
    if truthy(row.get("repricing_momentum_priority")):
        parts["repricing_momentum_priority"] = 10
    if truthy(row.get("repricing_momentum_extension")):
        parts["repricing_momentum_extension"] = 6

    market = to_float(row.get("market_repricing_score")) or 0.0
    if market >= 10:
        parts["market_repricing_score_gte_10"] = 10
    if market >= 14:
        parts["market_repricing_score_gte_14"] = 10
    if signal_count(row, HP_SIGNAL_FIELDS) > 0:
        parts["hp_signal_count_gt_0"] = 10
    if truthy(row.get("hp_LLM_best")):
        parts["hp_LLM_best"] = 12
    if truthy(row.get("theme_acceleration_research_visibility")):
        parts["theme_acceleration_research_visibility"] = 15
    if _clean(row.get("akg_universe_tier")).upper() == "T5_RESCAN":
        parts["akg_t5_rescan"] = 12
    if _clean(row.get("primary_theme")):
        parts["primary_theme"] = 10
    if (to_float(row.get("theme_tailwind_score")) or 0.0) > 0:
        parts["theme_tailwind_score"] = 8
    if truthy(row.get("filing_theme_growth_flag")):
        parts["filing_theme_growth_flag"] = 8
    if truthy(row.get("filing_theme_guidance_flag")):
        parts["filing_theme_guidance_flag"] = 8
    if has_active_theme_supplier_role(row):
        parts["active_theme_supplier_or_bottleneck_role"] = 10

    severity = classify_demote_severity(row)
    if severity == "hard":
        parts["hard_demote"] = -15
    elif severity == "soft":
        parts["soft_demote"] = -8
    if (to_float(row.get("risk_penalty_score")) or 0.0) >= 10:
        parts["risk_penalty_score_gte_10"] = -10
    return float(sum(parts.values())), parts
