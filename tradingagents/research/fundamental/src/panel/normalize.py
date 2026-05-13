from __future__ import annotations

from datetime import date
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
    out["source_run_root"] = out.get("source_run_root") or (source_run_root or "")
    out["source_artifact"] = out.get("source_artifact") or (source_artifact or "")
    out["source_artifact_sha256"] = out.get("source_artifact_sha256") or (
        source_artifact_sha256 or ""
    )
    out["field_population_status"] = (
        out.get("field_population_status") or "complete_schema_defaults_applied"
    )
    return out


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
