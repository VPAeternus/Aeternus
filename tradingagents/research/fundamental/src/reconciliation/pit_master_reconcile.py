from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from tradingagents.research.fundamental.src.ingest.period_context import normalize_accession
from tradingagents.research.fundamental.src.panel.validate import FORBIDDEN_SELECTION_COLUMNS


FINANCIAL_FIELDS = (
    "revenue_value",
    "net_income_value",
    "assets_value",
    "operating_cash_flow_value",
    "investing_cash_flow_value",
    "financing_cash_flow_value",
)

APPROVED_ENTRY_DRIFT_REASONS = {
    "ticker_halted",
    "ticker_not_listed_yet",
    "missing_price_vendor_row",
    "foreign_market_calendar_mismatch",
}


def validate_pit_master_rows(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    panel_rows = [dict(row) for row in rows]
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    for index, row in enumerate(panel_rows):
        _check_row(row, index, errors, warnings)
    return {
        "status": "valid" if not errors else "invalid",
        "passed": not errors,
        "row_count": len(panel_rows),
        "blocking_errors": errors,
        "warnings": warnings,
    }


def write_reconciliation_outputs(result: Mapping[str, Any], output_root: str | Path) -> dict[str, str]:
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    errors_path = root / "blocking_errors.csv"
    warnings_path = root / "warnings.csv"
    status_path = root / "reconciliation_status.json"
    _write_csv(errors_path, result.get("blocking_errors", []))
    _write_csv(warnings_path, result.get("warnings", []))
    status_path.write_text(json.dumps(dict(result), indent=2, sort_keys=True), encoding="utf-8")
    return {
        "blocking_errors_csv": str(errors_path),
        "warnings_csv": str(warnings_path),
        "reconciliation_status_json": str(status_path),
    }


def _check_row(row: Mapping[str, Any], index: int, errors: list[dict[str, Any]], warnings: list[dict[str, Any]]) -> None:
    if not _truthy(row.get("score_producing_flag")) and not _truthy(row.get("accepted_row_flag")):
        return
    decision_date = _date(row.get("decision_date"))
    source_available = _date(row.get("source_available_date") or row.get("decision_date"))
    target_end = _date(row.get("target_period_end"))
    strict_score_row = _strict_score_row(row)

    _require(row, index, "decision_date_rule", "blocking_missing_decision_date_rule", errors)
    _require(row, index, "entry_open_date", "blocking_missing_entry_open_date", errors)
    _require(row, index, "entry_open", "blocking_missing_entry_open", errors)
    if strict_score_row:
        _require(row, index, "target_period_end", "blocking_missing_target_period_end", errors)
        _require(row, index, "fiscal_period_start", "blocking_missing_fiscal_period_start", errors)
        _require(row, index, "fiscal_period_end", "blocking_missing_fiscal_period_end", errors)
        _require(row, index, "period_context_source", "blocking_missing_period_context_source", errors)
        if not _blank(row.get("period_context_missing_reason")):
            _error(
                errors,
                row,
                index,
                "blocking_period_context_missing_reason_present",
                reason=row.get("period_context_missing_reason", ""),
            )
    if _clean(row.get("tradable_date")) and _clean(row.get("entry_open_date")) and _clean(row.get("tradable_date")) != _clean(row.get("entry_open_date")):
        _error(errors, row, index, "blocking_tradable_date_mismatch", field="tradable_date")
    _check_entry_gap(row, index, errors)
    _check_price_basis(row, index, errors)
    _check_financials(row, index, source_available, target_end, errors, strict_score_row=strict_score_row)
    _check_score_recompute(row, index, errors)
    _check_llm(row, index, decision_date, errors)
    _check_theme(row, index, decision_date, errors)
    _check_selection_columns(row, index, errors)


def _check_financials(
    row: Mapping[str, Any],
    index: int,
    source_available: str,
    target_end: str,
    errors: list[dict[str, Any]],
    *,
    strict_score_row: bool,
) -> None:
    required_accession = normalize_accession(row.get("periodic_accession"))
    for field in FINANCIAL_FIELDS:
        if _blank(row.get(field)):
            _error(errors, row, index, "blocking_missing_required_input", field=field)
            continue
        filed = _date(row.get(f"{field}_fact_filed"))
        end = _date(row.get(f"{field}_fact_end"))
        accession = normalize_accession(row.get(f"{field}_fact_accession"))
        if not filed or not end or not accession:
            _error(errors, row, index, "blocking_missing_financial_provenance", field=field)
            continue
        if source_available and filed > source_available:
            _error(errors, row, index, "blocking_future_fact_leakage", field=field, fact_filed=filed, source_available_date=source_available)
        if target_end and end > target_end:
            _error(errors, row, index, "blocking_future_period_fact", field=field, fact_end=end, target_period_end=target_end)
        if strict_score_row and target_end and end != target_end:
            _error(errors, row, index, "blocking_fact_end_not_target_period", field=field, fact_end=end, target_period_end=target_end)
        if required_accession and accession != required_accession:
            _error(errors, row, index, "blocking_wrong_accession", field=field)
        if _clean(row.get(f"{field}_fact_is_consolidated")) not in {"1", "true", "True"}:
            _error(errors, row, index, "blocking_disallowed_segment_fact", field=field)
        period_type = _clean(row.get(f"{field}_fact_period_type"))
        if period_type == "derived_qtd_from_ytd" and _blank(row.get(f"{field}_derivation_source_facts_json")):
            _error(errors, row, index, "blocking_missing_qtd_derivation_provenance", field=field)


def _check_score_recompute(row: Mapping[str, Any], index: int, errors: list[dict[str, Any]]) -> None:
    if _truthy(row.get("score_recompute_required_flag")):
        _error(errors, row, index, "blocking_post_score_financial_rewrite", reason=row.get("score_recompute_reason", ""))


def _check_entry_gap(row: Mapping[str, Any], index: int, errors: list[dict[str, Any]]) -> None:
    try:
        gap = int(float(_clean(row.get("entry_open_gap_sessions")) or "0"))
    except ValueError:
        gap = 0
    reason = _clean(row.get("entry_date_adjustment_reason"))
    if gap > 0 and reason not in APPROVED_ENTRY_DRIFT_REASONS:
        _error(errors, row, index, "blocking_unapproved_entry_date_drift", reason=reason, entry_open_gap_sessions=gap)


def _check_price_basis(row: Mapping[str, Any], index: int, errors: list[dict[str, Any]]) -> None:
    entry_basis = _clean(row.get("entry_open_price_basis"))
    return_basis = _clean(row.get("return_price_basis"))
    if return_basis and entry_basis and return_basis == "adjusted_close" and entry_basis == "raw_open":
        _error(errors, row, index, "blocking_mixed_price_basis")


def _check_llm(row: Mapping[str, Any], index: int, decision_date: str, errors: list[dict[str, Any]]) -> None:
    if _clean(row.get("llm_status")).lower() == "complete":
        if _clean(row.get("llm_prompt_input_allowed_docs_only")) not in {"", "1", "true", "True"}:
            _error(errors, row, index, "blocking_llm_disallowed_source_document")
        for doc_date in _split_values(row.get("llm_source_document_dates")):
            if decision_date and doc_date[:10] > decision_date:
                _error(errors, row, index, "blocking_late_llm_source", llm_source_document_date=doc_date[:10], decision_date=decision_date)


def _check_theme(row: Mapping[str, Any], index: int, decision_date: str, errors: list[dict[str, Any]]) -> None:
    if not _truthy(row.get("theme_pit_valid_flag")) and _to_float(row.get("theme_tailwind_score")) not in (None, 0.0):
        source_available = _date(row.get("theme_source_available_date"))
        if decision_date and source_available and source_available > decision_date:
            _error(errors, row, index, "blocking_late_theme_source", theme_source_available_date=source_available, decision_date=decision_date)
        if _clean(row.get("theme_source_type")).lower() == "static_taxonomy" and not _truthy(row.get("theme_score_allowed_for_historical_scoring")):
            _error(errors, row, index, "blocking_static_theme_source_not_pit_valid")


def _check_selection_columns(row: Mapping[str, Any], index: int, errors: list[dict[str, Any]]) -> None:
    used = set()
    for field in ("selection_ranking_source_columns", "ranking_source_columns", "selector_source_columns"):
        used.update(_split_values(row.get(field)))
    leaked = sorted(FORBIDDEN_SELECTION_COLUMNS.intersection(used))
    for column in leaked:
        _error(errors, row, index, "blocking_selection_uses_future_field", column=column)


def _require(row: Mapping[str, Any], index: int, field: str, code: str, errors: list[dict[str, Any]]) -> None:
    if _blank(row.get(field)):
        _error(errors, row, index, code, field=field)


def _strict_score_row(row: Mapping[str, Any]) -> bool:
    return (
        _truthy(row.get("score_producing_flag"))
        and _truthy(row.get("accepted_row_flag"))
        and not _truthy(row.get("diagnostic_only_flag"))
    )


def _error(errors: list[dict[str, Any]], row: Mapping[str, Any], index: int, code: str, **extra: Any) -> None:
    errors.append(
        {
            "code": code,
            "row_index": index,
            "quarter": row.get("quarter", ""),
            "ticker": row.get("ticker", ""),
            **extra,
        }
    )


def _write_csv(path: Path, rows: Any) -> None:
    records = [dict(row) for row in rows or []]
    fields: list[str] = []
    for row in records:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields or ["code"])
        writer.writeheader()
        writer.writerows(records)


def _split_values(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, (list, tuple, set)):
        return {str(item).strip() for item in value if str(item).strip()}
    text = str(value)
    return {part.strip() for chunk in text.split(",") for part in chunk.split(";") if part.strip()}


def _date(value: Any) -> str:
    return str(value or "").strip()[:10]


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _blank(value: Any) -> bool:
    return _clean(value) == ""


def _truthy(value: Any) -> bool:
    return _clean(value).lower() in {"1", "true", "yes", "y"}


def _to_float(value: Any) -> float | None:
    try:
        return float(_clean(value))
    except ValueError:
        return None
