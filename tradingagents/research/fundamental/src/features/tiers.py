from __future__ import annotations

from typing import Any

from src.features.common import clean, flag, to_float
from src.features.hp_subtiers import HP_LABELS, hp_bool_from_row
from src.features.pre_llm_scores import REVENUE_BUCKETS
from src.features.repricing_momentum import RM_LABELS, rm_bool_from_row


TIER_LABELS = {
    "tier_0_bucket": "Tier 0 - Broad right-tail scouting universe",
    "tier_1_bucket": "Tier 1 - Balanced priority feed",
    "tier_2_bucket": "Tier 2 - High-priority compact feed",
    "tier_3_bucket": "Tier 3 - Revised dislocation feed",
    "tier_4_bucket": "Tier 4 - Ultra-distressed tag, not a production tier",
    **HP_LABELS,
    **RM_LABELS,
    "extended_candidate_universe": "Extended candidate universe",
    "extended_research_universe": "Extended research universe",
}


def is_scored(row: dict[str, Any]) -> bool:
    return clean(row.get("pre_llm_fundamental_bucket")) != "not_scored"


def assign_tiers(row: dict[str, Any]) -> dict[str, str]:
    entry_open = to_float(row.get("entry_open"))
    revenue_bucket = clean(row.get("revenue_bucket"))
    out = {key: "" for key in TIER_LABELS}
    if not is_scored(row) or entry_open is None:
        return out
    for key, enabled in hp_bool_from_row(row).items():
        if key in HP_LABELS and enabled:
            out[key] = HP_LABELS[key]
    for key, enabled in rm_bool_from_row(row).items():
        if key in RM_LABELS and enabled:
            out[key] = RM_LABELS[key]
    if revenue_bucket not in REVENUE_BUCKETS:
        if out["hp1_quality_pullback"] or out["hp2_dislocation_momentum_priority"] or out["hp3_large_quality_theme_exception"]:
            out["extended_candidate_universe"] = TIER_LABELS["extended_candidate_universe"]
        if out["hp_research_extension"]:
            out["extended_research_universe"] = TIER_LABELS["extended_research_universe"]
        return out
    if entry_open < 25:
        out["tier_0_bucket"] = TIER_LABELS["tier_0_bucket"]
    if entry_open < 15:
        out["tier_1_bucket"] = TIER_LABELS["tier_1_bucket"]
    if entry_open < 10:
        out["tier_2_bucket"] = TIER_LABELS["tier_2_bucket"]
    pre_score = to_float(row.get("pre_llm_fundamental_score"))
    if entry_open < 15 and pre_score is not None and pre_score <= 0:
        out["tier_3_bucket"] = TIER_LABELS["tier_3_bucket"]
    if entry_open < 5:
        out["tier_4_bucket"] = TIER_LABELS["tier_4_bucket"]
    if out["tier_0_bucket"] or out["hp1_quality_pullback"] or out["hp2_dislocation_momentum_priority"] or out["hp3_large_quality_theme_exception"]:
        out["extended_candidate_universe"] = TIER_LABELS["extended_candidate_universe"]
    if out["tier_0_bucket"] or out["hp_research_extension"]:
        out["extended_research_universe"] = TIER_LABELS["extended_research_universe"]
    return out


def assign_subtiers(row: dict[str, Any], prior_row: dict[str, Any] | None = None) -> dict[str, int]:
    prior = prior_row or {}
    tier1 = bool(clean(row.get("tier_1_bucket")))
    tier2 = bool(clean(row.get("tier_2_bucket")))
    tier3 = bool(clean(row.get("tier_3_bucket")))
    tier4 = bool(clean(row.get("tier_4_bucket")))
    candidate = flag(row.get("post_llm_candidate_flag"))
    high_priority = flag(row.get("post_llm_high_priority_flag"))
    causal3 = to_float(row.get("causal_change")) == 3
    neg_ok = (to_float(row.get("negative_revision_risk")) or 0) <= 2
    inflecting = clean(row.get("narrative_delta_bucket")) == "inflecting"
    current_add = (to_float(row.get("score_addition")) or 0) > 0
    prior_add = (to_float(prior.get("score_addition")) or 0) > 0
    pre_score = to_float(row.get("pre_llm_fundamental_score"))
    llm_best = candidate and causal3 and neg_ok
    theme_confirmed = (
        flag(row.get("theme_active"))
        or flag(row.get("theme_cohort_strength"))
        or flag(row.get("theme_leader_or_direct_beneficiary"))
    )

    return {
        "tier1_L1_llm_supported": int(tier1 and candidate),
        "tier1_L2_causal_rerating": int(tier1 and causal3),
        "tier1_L3_best_balanced": int(tier1 and candidate and causal3 and neg_ok),
        "tier1_L4_clean_high_priority": int(tier1 and high_priority),
        "tier1_L5_inflecting": int(tier1 and inflecting),
        "tier1_L6_mid_price_rerater": int(tier1 and not tier2 and candidate and causal3 and neg_ok),
        "tier1_L7_clean_non_distressed_rerater": int(tier1 and not tier2 and pre_score is not None and pre_score > 0 and candidate and causal3 and neg_ok),
        "tier2_L1_llm_supported": int(tier2 and candidate),
        "tier2_L2_causal_rerating": int(tier2 and causal3),
        "tier2_L3_best_balanced": int(tier2 and candidate and causal3 and neg_ok),
        "tier3_L1_llm_supported": int(tier3 and candidate),
        "tier3_L2_inflecting": int(tier3 and inflecting),
        "tier3_L3_persistent_positive": int(tier3 and current_add and prior_add),
        "tier3_L4_persistent_high_priority": int(tier3 and high_priority and prior_add),
        "tier4_L1_llm_supported": int(tier4 and candidate),
        "tier4_L2_causal_rerating": int(tier4 and causal3),
        "tier4_L3_clean_high_priority": int(tier4 and candidate and causal3 and neg_ok),
        "hp1_LLM_best": int(bool(clean(row.get("hp1_quality_pullback"))) and llm_best),
        "hp2_LLM_best": int(bool(clean(row.get("hp2_dislocation_momentum_priority"))) and llm_best),
        "hp3_theme_confirmed": int(bool(clean(row.get("hp3_large_quality_theme_exception"))) and (llm_best or theme_confirmed)),
        "hp4_LLM_supported": int(bool(clean(row.get("hp4_score_reacceleration_watch"))) and llm_best),
        "hp_LLM_best": int(bool(clean(row.get("hp_production_extension"))) and llm_best),
        "demote_risk_flag": int(flag(row.get("post_llm_demote_flag"))),
        "deteriorating_risk_flag": int(clean(row.get("narrative_delta_bucket")) == "deteriorating"),
        "negative_revision_risk_flag": int((to_float(row.get("negative_revision_risk")) or 0) >= 3),
    }
