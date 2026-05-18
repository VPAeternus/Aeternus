from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from tradingagents.research.fundamental.src.features.post_llm_subtiers import add_post_llm_subtiers
from tradingagents.research.fundamental.src.panel.financial_values import (
    FINANCIAL_VALUE_FIELDS,
    fill_financial_values,
)
from tradingagents.research.fundamental.src.panel.schema import (
    COMPLETE_PANEL_SCHEMA_VERSION,
    FLAG_FIELDS,
    REQUIRED_COMPLETE_PANEL_COLUMNS,
    REQUIRED_NONBLANK_FIELDS,
    default_for_field,
    missing_reason_field,
)

FEATURE_SCHEMA_PATH = "tradingagents/research/fundamental/src/panel/schema.py"


def normalize_complete_panel_rows(
    rows: list[dict[str, Any]],
    *,
    source_name: str,
    facts_by_ticker: dict[str, dict[str, Any]] | None = None,
    as_of: date | None = None,
    source_run_root: str | None = None,
    source_artifact: str | None = None,
    source_artifact_sha256: str | None = None,
    allow_relaxed_filed_date: bool = False,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Normalize source rows into canonical complete-panel rows."""
    normalized = [_copy_string_row(row) for row in rows]
    normalized = [_normalize_identity(row, facts_by_ticker or {}) for row in normalized]
    normalized = [
        _normalize_provenance(
            row,
            source_name=source_name,
            source_run_root=source_run_root,
            source_artifact=source_artifact,
            source_artifact_sha256=source_artifact_sha256,
        )
        for row in normalized
    ]

    financial_summary: dict[str, int] | None = None
    if facts_by_ticker is not None and as_of is not None:
        normalized, financial_summary = fill_financial_values(
            normalized,
            facts_by_ticker=facts_by_ticker,
            as_of=as_of,
            allow_relaxed_filed_date=allow_relaxed_filed_date,
        )
    else:
        normalized = [_fill_financial_defaults(row) for row in normalized]

    normalized = _derive_post_llm_subtiers(normalized)
    normalized = [_derive_pre_llm_flags(row) for row in normalized]
    normalized = [_derive_llm_flags(row) for row in normalized]
    normalized = _derive_quarter_ranks(normalized)
    out = [_complete_schema_row(row) for row in normalized]
    summary: dict[str, Any] = {
        "rows": len(out),
        "source_name": source_name,
        "field_population_status": "complete_schema_defaults_applied",
    }
    if financial_summary is not None:
        summary["financial_values"] = financial_summary
    return out, summary


def _copy_string_row(row: dict[str, Any]) -> dict[str, str]:
    return {str(key): _stringify(value) for key, value in row.items()}


def _normalize_identity(
    row: dict[str, str],
    facts_by_ticker: dict[str, dict[str, Any]],
) -> dict[str, str]:
    out = dict(row)
    raw_ticker = out.get("ticker") or out.get("symbol")
    ticker = raw_ticker.strip().upper()
    facts = facts_by_ticker.get(ticker) or facts_by_ticker.get(raw_ticker.strip()) or {}

    out["ticker"] = ticker
    out["symbol"] = (out.get("symbol") or ticker).strip().upper()
    out["cik"] = out.get("cik") or _stringify(facts.get("cik"))
    out["company_title"] = out.get("company_title") or _stringify(facts.get("entityName"))
    if not out.get("cik_status"):
        out["cik_status"] = "provided" if out.get("cik") else ""
    return out


def _normalize_provenance(
    row: dict[str, str],
    *,
    source_name: str,
    source_run_root: str | None,
    source_artifact: str | None,
    source_artifact_sha256: str | None,
) -> dict[str, str]:
    out = dict(row)
    out["panel_row_source"] = out.get("panel_row_source") or source_name
    out["source_file"] = out.get("source_file") or (source_artifact or "")
    out["feature_schema_version"] = out.get("feature_schema_version") or COMPLETE_PANEL_SCHEMA_VERSION
    out["feature_schema_path"] = out.get("feature_schema_path") or FEATURE_SCHEMA_PATH
    out["source_run_root"] = out.get("source_run_root") or (source_run_root or "")
    out["source_artifact"] = out.get("source_artifact") or (source_artifact or "")
    out["source_artifact_sha256"] = out.get("source_artifact_sha256") or (
        source_artifact_sha256 or ""
    )
    out["panel_build_id"] = out.get("panel_build_id") or _panel_build_id(
        source_artifact_sha256=source_artifact_sha256,
        source_artifact=source_artifact,
        source_name=source_name,
    )
    out["panel_build_timestamp"] = out.get("panel_build_timestamp") or _utc_timestamp()
    out["field_population_status"] = (
        out.get("field_population_status") or "complete_schema_defaults_applied"
    )
    return out


def _panel_build_id(
    *,
    source_artifact_sha256: str | None,
    source_artifact: str | None,
    source_name: str,
) -> str:
    if source_artifact_sha256:
        return f"panel_{source_artifact_sha256[:12]}"
    if source_artifact:
        return f"panel_{Path(source_artifact).stem}"
    return f"panel_{source_name}"


def _utc_timestamp() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _fill_financial_defaults(row: dict[str, str]) -> dict[str, str]:
    out = dict(row)
    missing = []
    for field in FINANCIAL_VALUE_FIELDS:
        if not out.get(field):
            out[field] = default_for_field(field)
            out[f"{field}_missing_reason"] = (
                out.get(f"{field}_missing_reason") or "companyfacts_not_supplied"
            )
            missing.append(field)
    out["financial_values_missing_fields"] = out.get("financial_values_missing_fields") or ",".join(
        missing
    )
    return out


def _derive_post_llm_subtiers(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    if not rows:
        return []
    df = pd.DataFrame(rows)
    df = add_post_llm_subtiers(df)
    return [_copy_string_row(row) for row in df.to_dict(orient="records")]


_TIER_0_TO_4_FIELDS = (
    "tier_bucket",
    "tier_0_bucket",
    "tier_1_bucket",
    "tier_2_bucket",
    "tier_3_bucket",
    "tier_4_bucket",
)

_TIER_1_TO_4_FIELDS = (
    "tier_1_bucket",
    "tier_2_bucket",
    "tier_3_bucket",
    "tier_4_bucket",
)

_HP_FIELDS = (
    "hp0_high_price_broad",
    "hp1_quality_pullback",
    "hp2_dislocation_momentum_priority",
    "hp2_dislocation_momentum_watch",
    "hp3_large_quality_theme_exception",
    "hp4_score_reacceleration_watch",
    "hp_production_extension",
    "hp_research_extension",
    "hp1_LLM_best",
    "hp2_LLM_best",
    "hp2_watch_LLM_best",
    "hp3_theme_confirmed",
    "hp4_LLM_supported",
    "hp_LLM_best",
)

_RM_FIELDS = (
    "rm1_low_price_dislocation_momentum",
    "rm2_weak_acceleration",
    "rm3_mid_price_dislocation_momentum",
    "rm4_persistent_repricing_wave",
    "repricing_momentum_priority",
    "repricing_momentum_extension",
    "rm_buy_review_flag",
)

_PRE_LLM_CANDIDATE_FIELDS = (
    "tier_1_bucket",
    "tier_2_bucket",
    "tier_3_bucket",
    "tier_4_bucket",
    "hp_production_extension",
    "hp_research_extension",
    "repricing_momentum_extension",
)

_POST_LLM_ANY_FIELDS = (
    "post_llm_candidate_flag",
    "post_llm_high_priority_flag",
    "post_llm_demote_flag",
    "causal_change",
    "negative_revision_risk",
    "narrative_delta_bucket",
    "operating_leverage_quality",
    "durability",
    "proof_alignment",
)


def _derive_pre_llm_flags(row: dict[str, str]) -> dict[str, str]:
    out = dict(row)
    out["tier_0_to_4_any_flag"] = _derived_flag(out, _TIER_0_TO_4_FIELDS)
    out["tier_1_to_4_any_flag"] = _derived_flag(out, _TIER_1_TO_4_FIELDS)
    out["hp_any_flag"] = _derived_flag(out, _HP_FIELDS)
    out["rm_any_flag"] = _derived_flag(out, _RM_FIELDS)
    out["pre_llm_candidate_flag"] = _derived_flag(out, _PRE_LLM_CANDIDATE_FIELDS)
    return out


def _derive_llm_flags(row: dict[str, str]) -> dict[str, str]:
    out = dict(row)
    llm_status = str(out.get("llm_status") or "").strip().lower()
    llm_complete = llm_status == "complete" or _truthy_marker(out.get("has_post_llm"))
    out["llm_required_derived_flag"] = out.get("pre_llm_candidate_flag") or _derived_flag(
        out, _PRE_LLM_CANDIDATE_FIELDS
    )
    out["llm_complete_derived_flag"] = "1" if llm_complete else "0"
    out["has_post_llm"] = "1" if llm_complete or _truthy_marker(out.get("has_post_llm")) else "0"
    out["post_llm_any_flag"] = "1" if llm_complete or any(
        _truthy_marker(out.get(field)) for field in _POST_LLM_ANY_FIELDS
    ) else "0"
    return out


def _derive_quarter_ranks(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    out = [dict(row) for row in rows]
    pre_indexes = [
        idx
        for idx, row in enumerate(out)
        if _truthy_marker(row.get("pre_llm_candidate_flag"))
        and _to_float(row.get("pre_llm_fundamental_score")) is not None
    ]
    entry_indexes = [
        idx for idx, row in enumerate(out) if _to_float(row.get("entry_score_0_100")) is not None
    ]
    _assign_rank(out, pre_indexes, score_field="pre_llm_fundamental_score", rank_field="pre_llm_rank_by_score_quarter")
    _assign_rank(out, entry_indexes, score_field="entry_score_0_100", rank_field="entry_score_rank_by_quarter")
    return out


def _assign_rank(rows: list[dict[str, str]], indexes: list[int], *, score_field: str, rank_field: str) -> None:
    by_quarter: dict[str, list[int]] = {}
    for idx in indexes:
        by_quarter.setdefault(str(rows[idx].get("quarter") or "").strip(), []).append(idx)
    for quarter_indexes in by_quarter.values():
        quarter_indexes.sort(
            key=lambda idx: (
                -(_to_float(rows[idx].get(score_field)) or 0.0),
                str(rows[idx].get("ticker") or ""),
            )
        )
        for rank, idx in enumerate(quarter_indexes, start=1):
            rows[idx][rank_field] = str(rank)


def _to_float(value: Any) -> float | None:
    if _is_blank(value):
        return None
    try:
        return float(str(value).strip())
    except ValueError:
        return None


def _derived_flag(row: dict[str, str], fields: tuple[str, ...]) -> str:
    return "1" if any(_truthy_marker(row.get(field)) for field in fields) else "0"


def _truthy_marker(value: Any) -> bool:
    if _is_blank(value):
        return False
    cleaned = str(value).strip().lower()
    return cleaned not in {"0", "0.0", "false", "no", "n", "none", "null"}


def _complete_schema_row(row: dict[str, str]) -> dict[str, str]:
    out = dict(row)
    for field in REQUIRED_COMPLETE_PANEL_COLUMNS:
        if _is_blank(out.get(field)):
            out[field] = "0" if field in FLAG_FIELDS else default_for_field(field)

    for field in REQUIRED_NONBLANK_FIELDS:
        if _is_blank(out.get(field)):
            out[missing_reason_field(field)] = (
                out.get(missing_reason_field(field)) or "not_populated_by_normalize"
            )

    for field in FLAG_FIELDS:
        if _is_blank(out.get(field)):
            out[field] = "0"
        else:
            out[field] = _normalize_flag(out[field])
    return out


def _normalize_flag(value: str) -> str:
    cleaned = value.strip().lower()
    if cleaned in {"1", "1.0", "true", "yes", "y"}:
        return "1"
    if cleaned in {"", "0", "0.0", "false", "no", "n"}:
        return "0"
    return "1"


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if pd.isna(value):
        return True
    return str(value).strip() == ""


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if pd.isna(value):
        return ""
    return str(value)
