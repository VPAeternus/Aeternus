from __future__ import annotations

from typing import Any

from src.features.common import clean


REQUIRED_LLM_FIELDS = [
    "post_llm_candidate_flag",
    "post_llm_high_priority_flag",
    "post_llm_demote_flag",
    "causal_change",
    "negative_revision_risk",
    "narrative_delta_bucket",
    "operating_leverage_quality",
    "durability",
    "proof_alignment",
]


def needs_llm(row: dict[str, Any]) -> bool:
    return any(
        clean(row.get(key))
        for key in [
            "tier_1_bucket",
            "tier_2_bucket",
            "tier_3_bucket",
            "tier_4_bucket",
            "hp_production_extension",
            "hp_research_extension",
            "repricing_momentum_extension",
        ]
    )


def missing_llm_fields(row: dict[str, Any]) -> list[str]:
    return [field for field in REQUIRED_LLM_FIELDS if clean(row.get(field)) == ""]


def _truthy_demote(value: Any) -> bool:
    return clean(value).lower() not in {"", "0", "0.0", "false", "no", "none", "null"}


def _with_demote_defaults(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    if clean(out.get("post_llm_demote_severity")) == "":
        out["post_llm_demote_severity"] = "unknown" if _truthy_demote(out.get("post_llm_demote_flag")) else "none"
    out.setdefault("post_llm_demote_reason_code", "")
    out.setdefault("post_llm_demote_overrideable", 0)
    out.setdefault("post_llm_demote_evidence", "")
    return out


def classify_llm_status(row: dict[str, Any], llm_row: dict[str, Any] | None = None) -> dict[str, Any]:
    merged = _with_demote_defaults({**row, **(llm_row or {})})
    if not needs_llm(row):
        return _with_demote_defaults({
            **merged,
            "llm_status": "not_required",
            "entry_score_is_provisional": 0,
            "llm_required_for_full_buy_flag": 0,
        })
    missing = missing_llm_fields(merged)
    if missing:
        research_priority = "repricing_momentum_watch" if clean(merged.get("repricing_momentum_extension")) else "pre_llm_watchlist"
        return _with_demote_defaults({
            **merged,
            "llm_status": clean(merged.get("llm_status")) or "pending",
            "candidate_state": "llm_pending",
            "entry_score_is_provisional": 1,
            "llm_required_for_full_buy_flag": 1,
            "research_priority": research_priority,
            "missing_critical_llm_fields": ";".join(missing),
        })
    return _with_demote_defaults({
        **merged,
        "llm_status": "complete",
        "entry_score_is_provisional": 0,
        "llm_required_for_full_buy_flag": 0,
        "missing_critical_llm_fields": "",
    })
