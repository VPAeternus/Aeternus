from __future__ import annotations

from typing import Any

from tradingagents.research.fundamental.src.features.common import clamp, clean, flag, prior_quarter, to_float, to_int
from tradingagents.research.fundamental.src.features.hp_subtiers import HP_LABELS
from tradingagents.research.fundamental.src.features.post_llm_scores import REQUIRED_LLM_FIELDS
from tradingagents.research.fundamental.src.features.themes import assign_theme_tailwind_score, detect_candidate_themes
from tradingagents.research.fundamental.src.features.underwriting import rm_buy_review_flag


ENTRY_SCORE_FORBIDDEN_COLUMNS = {
    "return_10d_pct",
    "return_20d_pct",
    "return_30d_pct",
    "return_60d_pct",
    "return_90d_pct",
    "current_return_pct",
    "return_since_signal_pct",
    "return_since_purchase_pct",
    "active_monitoring_score_0_100",
    "monitoring_score_0_100",
    "final_rank_score_0_100",
    "rank_score_label",
    "monitoring_status",
    "winner_90d_30pct",
    "loser_90d_minus30pct",
}


def tier_structure_score(row: dict[str, Any]) -> int:
    score = 0
    if clean(row.get("tier_0_bucket")) or clean(row.get("tier_bucket")):
        score = max(score, 10)
    if clean(row.get("tier_1_bucket")):
        score = max(score, 18)
    if clean(row.get("tier_2_bucket")):
        score = max(score, 25)
    if clean(row.get("tier_3_bucket")):
        score += 4
    if clean(row.get("tier_4_bucket")):
        score += 5
    return min(score, 30)


def _hp_field_enabled(row: dict[str, Any], column: str) -> bool:
    value = row.get(column)
    return flag(value) or clean(value) == HP_LABELS[column]


def hp_structure_score(row: dict[str, Any]) -> int:
    existing = to_float(row.get("hp_structure_score"))
    if existing is not None:
        return max(0, min(30, int(existing)))
    score = 0
    if _hp_field_enabled(row, "hp1_quality_pullback"):
        score = max(score, 15)
    if _hp_field_enabled(row, "hp2_dislocation_momentum_priority"):
        score = max(score, 18)
    if _hp_field_enabled(row, "hp2_dislocation_momentum_watch"):
        score = max(score, 8)
    if _hp_field_enabled(row, "hp3_large_quality_theme_exception"):
        score = max(score, 10)
    if _hp_field_enabled(row, "hp4_score_reacceleration_watch"):
        score = max(score, 8)
    return min(score, 30)


def llm_business_improvement_score(row: dict[str, Any], prior_score_addition: int | None = None) -> int:
    score = 0
    if flag(row.get("post_llm_candidate_flag")):
        score += 8
    if flag(row.get("post_llm_high_priority_flag")):
        score += 6
    causal = to_int(row.get("causal_change"))
    score += {1: 4, 2: 10, 3: 20}.get(causal, 0)
    neg_risk = to_float(row.get("negative_revision_risk"))
    if neg_risk is not None:
        if neg_risk <= 1:
            score += 6
        elif neg_risk == 2:
            score += 4
    narrative = clean(row.get("narrative_delta_bucket"))
    score += {"inflecting": 5, "constructive": 3, "neutral": 1}.get(narrative, 0)
    score += {2: 4, 1: 2}.get(to_int(row.get("operating_leverage_quality")), 0)
    score += {2: 3, 1: 1}.get(to_int(row.get("durability")), 0)
    if (to_float(row.get("score_addition")) or 0) > 0 and prior_score_addition is not None and prior_score_addition > 0:
        score += 5
    if flag(row.get("post_llm_high_priority_flag")) and prior_score_addition is not None and prior_score_addition > 0:
        score += 3
    return min(score, 45)


def fundamental_rerating_score(row: dict[str, Any], prior_pre_score: float | None = None) -> int:
    score = 0
    score += {2: 5, 1: 3}.get(to_int(row.get("asset_efficiency_score")), 0)
    pre_score = to_float(row.get("pre_llm_fundamental_score"))
    causal = to_int(row.get("causal_change"))
    if pre_score is not None:
        if pre_score <= 0:
            score += 3
        if pre_score <= -2:
            score += 2
        if pre_score > 0 and causal == 3:
            score += 3
    if pre_score is not None and prior_pre_score is not None and pre_score <= 0 and prior_pre_score <= 0:
        score += 3
    financing = to_float(row.get("financing_dependence_score"))
    if financing == 1:
        score += 3
    elif financing == 0:
        score += 1
    return min(score, 15)


def theme_tailwind_score(row: dict[str, Any]) -> int:
    if not _theme_score_pit_allowed(row):
        return 0
    existing = to_float(row.get("theme_tailwind_score"))
    if existing is not None and existing > 0:
        return max(0, min(20, int(existing)))
    return assign_theme_tailwind_score(row, detect_candidate_themes(row), {})


def _theme_score_pit_allowed(row: dict[str, Any]) -> bool:
    source_available = clean(row.get("theme_source_available_date"))
    decision_date = clean(row.get("decision_date"))
    if source_available and decision_date and source_available[:10] > decision_date[:10]:
        return False
    if clean(row.get("theme_source_type")).lower() == "static_taxonomy":
        return flag(row.get("theme_score_allowed_for_historical_scoring"))
    return True


def theme_external_confirmation_score(row: dict[str, Any]) -> int:
    # Legacy compatibility only. New framework uses adaptive theme_tailwind_score.
    score = 0
    if flag(row.get("theme_active")):
        score += 4
    if flag(row.get("theme_leader_or_direct_beneficiary")):
        score += 3
    if flag(row.get("theme_cohort_strength")):
        score += 3
    return min(score, 10)


def market_repricing_score(row: dict[str, Any]) -> int:
    return max(0, min(20, to_int(row.get("market_repricing_score"))))


def missing_critical_llm_fields(row: dict[str, Any]) -> int:
    if clean(row.get("llm_status")) not in {"complete", ""} and not flag(row.get("has_post_llm")):
        return 0
    if clean(row.get("llm_status")) == "complete" or flag(row.get("has_post_llm")):
        return int(any(clean(row.get(field)) == "" for field in REQUIRED_LLM_FIELDS))
    return 0


def risk_penalty_score(row: dict[str, Any], missing_llm_fields: int = 0) -> int:
    penalty = 0
    if flag(row.get("post_llm_demote_flag")):
        penalty += 7
    if clean(row.get("narrative_delta_bucket")) == "deteriorating":
        penalty += 5
    if to_int(row.get("negative_revision_risk")) >= 3:
        penalty += 6
    financing = to_float(row.get("financing_dependence_score"))
    if financing == -1:
        penalty += 4
    elif financing == 0:
        penalty += 1
    entry = to_float(row.get("entry_open"))
    if entry is not None:
        if entry < 2:
            penalty += 6
        elif entry < 5:
            penalty += 2
    if missing_llm_fields == 1:
        penalty += 3
    return penalty


def hard_reject_reason(row: dict[str, Any]) -> str:
    reasons: list[str] = []
    if clean(row.get("pre_llm_fundamental_bucket")) == "not_scored":
        reasons.append("pre_llm_fundamental_bucket_not_scored")
    if to_float(row.get("entry_open")) is None:
        reasons.append("missing_entry_open")
    if not clean(row.get("revenue_bucket")):
        reasons.append("missing_revenue_bucket")
    if flag(row.get("extraction_quality_failure")):
        reasons.append("extraction_quality_failure")
    if clean(row.get("document_status")) == "missing_required_metadata":
        reasons.append("missing_required_filings")
    return ";".join(reasons)


def score_label(score: int, status: str = "") -> str:
    if status == "kill_review":
        return "Stop / review"
    if score >= 85:
        return "A+"
    if score >= 75:
        return "A"
    if score >= 65:
        return "B"
    if score >= 50:
        return "C"
    if score >= 30:
        return "D"
    return "Avoid / stale / low priority"


def entry_score_bucket(score: int) -> str:
    if score >= 80:
        return "Highest-priority entry research"
    if score >= 70:
        return "High-priority entry research"
    if score >= 60:
        return "Good candidate, needs downstream confirmation"
    if score >= 40:
        return "Watchlist / secondary research"
    return "Low priority unless theme override exists"


def compute_entry_score(row: dict[str, Any], prior_row: dict[str, Any] | None = None) -> dict[str, Any]:
    clean_row = {key: value for key, value in row.items() if key not in ENTRY_SCORE_FORBIDDEN_COLUMNS}
    prior = prior_row or {}
    missing_llm = missing_critical_llm_fields(clean_row)
    reject = hard_reject_reason(clean_row)
    tier_score = tier_structure_score(clean_row)
    hp_score = hp_structure_score(clean_row)
    total_structure_score = max(tier_score, hp_score)
    llm_score = llm_business_improvement_score(clean_row, to_int(prior.get("score_addition")) if clean(prior.get("score_addition")) else None)
    fundamental_score = fundamental_rerating_score(clean_row, to_float(prior.get("pre_llm_fundamental_score")))
    repricing_score = market_repricing_score(clean_row)
    rm_review = rm_buy_review_flag({**clean_row, "market_repricing_score": repricing_score})
    theme_score = theme_tailwind_score(clean_row)
    penalty = risk_penalty_score(clean_row, missing_llm)
    raw_score = total_structure_score + llm_score + fundamental_score + repricing_score + theme_score - penalty
    entry_score = 0 if reject else clamp(raw_score)
    return {
        "prior_score_addition": clean(prior.get("score_addition")),
        "prior_pre_llm_fundamental_score": clean(prior.get("pre_llm_fundamental_score")),
        "missing_critical_llm_fields": missing_llm,
        "tier_structure_score": tier_score,
        "hp_structure_score": hp_score,
        "total_structure_score": total_structure_score,
        "llm_business_improvement_score": llm_score,
        "fundamental_rerating_score": fundamental_score,
        "market_repricing_score": repricing_score,
        "rm_buy_review_flag": rm_review,
        "theme_tailwind_score": theme_score,
        "theme_external_confirmation_score": theme_external_confirmation_score(clean_row),
        "risk_penalty_score": penalty,
        "base_entry_raw_score": raw_score,
        "base_entry_score_0_100": entry_score,
        "entry_raw_score": raw_score,
        "entry_score_0_100": entry_score,
        "entry_score_0_100_bucket": entry_score_bucket(entry_score),
        "entry_score_label": score_label(entry_score),
        "hard_reject_reason": reject,
        "entry_score_inputs": ";".join(sorted(clean_row)),
        "compatibility_alias_source": "current_entry_score",
    }


def prior_key(row: dict[str, Any]) -> tuple[str, str]:
    ticker = clean(row.get("ticker")).upper()
    quarter = clean(row.get("quarter"))
    try:
        return ticker, prior_quarter(quarter)
    except (ValueError, IndexError):
        return ticker, ""
