from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from tradingagents.research.fundamental.src.panel.schema import (
    FLAG_FIELDS,
    REQUIRED_NONBLANK_FIELDS,
    missing_reason_field,
)

ALLOWED_MISSING_REASONS = {
    "source_fact_unavailable_as_of",
    "companyfacts_not_supplied",
    "not_populated_by_normalize",
    "not_applicable",
}

RANKING_SOURCE_METADATA_FIELDS = (
    "selection_ranking_source_columns",
    "ranking_source_columns",
    "selector_source_columns",
)

FORBIDDEN_SELECTION_COLUMNS = frozenset(
    {
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
)


def validate_complete_panel(
    rows,
    *,
    required_columns=None,
    required_nonblank_fields=None,
    flag_fields=None,
    allowed_missing_reasons=None,
    expected_quarters=None,
    top15_rows=None,
    shadow_rows=None,
    forbidden_selection_columns=None,
    quarter: str | None = None,
):
    """Validate complete-panel rows for hard-fail data quality issues."""

    panel_rows = list(rows or [])
    required_nonblank = (
        tuple(REQUIRED_NONBLANK_FIELDS)
        if required_nonblank_fields is None
        else tuple(required_nonblank_fields)
    )
    flags = tuple(FLAG_FIELDS) if flag_fields is None else tuple(flag_fields)
    allowed_reasons = (
        set(ALLOWED_MISSING_REASONS)
        if allowed_missing_reasons is None
        else set(allowed_missing_reasons)
    )
    forbidden_columns = set(forbidden_selection_columns or ())
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    present_columns = _present_columns(panel_rows)
    required_columns_missing: list[str] = []
    if required_columns is not None:
        required_columns_missing = [
            column for column in required_columns if column not in present_columns
        ]
        for column in required_columns_missing:
            errors.append({"code": "missing_required_column", "column": column})

    duplicate_count = _add_duplicate_errors(panel_rows, errors)
    _add_required_blank_errors(panel_rows, required_nonblank, allowed_reasons, errors)
    _add_flag_errors(panel_rows, flags, errors)
    _add_quarter_coverage_error(panel_rows, expected_quarters, errors)
    _add_identity_mismatch_error(panel_rows, top15_rows, "top15", errors, quarter)
    _add_identity_mismatch_error(panel_rows, shadow_rows, "shadow", errors, quarter)
    _add_forbidden_selection_errors(panel_rows, forbidden_columns, errors)

    top15_selected_count = sum(
        1 for row in panel_rows if _is_selected(row.get("top15_selected"))
    )
    shadow_selected_count = sum(
        1 for row in panel_rows if _is_selected(row.get("shadow_selected"))
    )

    return {
        "passed": not errors,
        "errors": errors,
        "warnings": warnings,
        "row_count": len(panel_rows),
        "duplicate_ticker_quarter_count": duplicate_count,
        "required_columns_missing": required_columns_missing,
        "top15_selected_count": top15_selected_count,
        "shadow_selected_count": shadow_selected_count,
    }


def _present_columns(rows: list[Mapping[str, Any]]) -> set[str]:
    columns: set[str] = set()
    for row in rows:
        columns.update(row.keys())
    return columns


def _add_duplicate_errors(rows: list[Mapping[str, Any]], errors: list[dict[str, Any]]) -> int:
    seen: set[tuple[str, str]] = set()
    duplicates: set[tuple[str, str]] = set()
    for index, row in enumerate(rows):
        key = (_normalize_quarter(row.get("quarter")), _normalize_ticker(row.get("ticker")))
        if not all(key):
            continue
        if key in seen:
            duplicates.add(key)
            errors.append(
                {
                    "code": "duplicate_ticker_quarter",
                    "row_index": index,
                    "quarter": key[0],
                    "ticker": key[1],
                }
            )
        seen.add(key)
    return len(duplicates)


def _add_required_blank_errors(
    rows: list[Mapping[str, Any]],
    required_nonblank: Iterable[str],
    allowed_reasons: set[str],
    errors: list[dict[str, Any]],
) -> None:
    for index, row in enumerate(rows):
        for field in required_nonblank:
            if field not in row or not _is_blank(row.get(field)):
                continue
            reason_field = missing_reason_field(field)
            reason = str(row.get(reason_field, "")).strip()
            if reason in allowed_reasons:
                continue
            errors.append(
                {
                    "code": "required_blank_without_reason",
                    "row_index": index,
                    "quarter": row.get("quarter", ""),
                    "ticker": row.get("ticker", ""),
                    "field": field,
                    "missing_reason_field": reason_field,
                    "missing_reason": reason,
                }
            )


def _add_flag_errors(
    rows: list[Mapping[str, Any]],
    flag_fields: Iterable[str],
    errors: list[dict[str, Any]],
) -> None:
    for index, row in enumerate(rows):
        for field in flag_fields:
            if field not in row:
                continue
            value = row.get(field)
            if str(value).strip() not in {"0", "1"}:
                errors.append(
                    {
                        "code": "invalid_flag_value",
                        "row_index": index,
                        "quarter": row.get("quarter", ""),
                        "ticker": row.get("ticker", ""),
                        "field": field,
                        "value": value,
                    }
                )


def _add_quarter_coverage_error(
    rows: list[Mapping[str, Any]],
    expected_quarters,
    errors: list[dict[str, Any]],
) -> None:
    if expected_quarters is None:
        return
    actual = sorted({_normalize_quarter(row.get("quarter")) for row in rows if row.get("quarter")})
    expected = sorted(_normalize_quarter(quarter) for quarter in expected_quarters)
    if actual != expected:
        errors.append(
            {
                "code": "quarter_coverage_mismatch",
                "expected_quarters": expected,
                "actual_quarters": actual,
            }
        )


def _add_identity_mismatch_error(
    panel_rows: list[Mapping[str, Any]],
    selected_rows,
    prefix: str,
    errors: list[dict[str, Any]],
    quarter: str | None,
) -> None:
    if selected_rows is None:
        return
    requested_quarter = _normalize_quarter(quarter) if quarter is not None else None
    panel_selected = {
        (_normalize_quarter(row.get("quarter")), _normalize_ticker(row.get("ticker")))
        for row in panel_rows
        if _is_selected(row.get(f"{prefix}_selected"))
        and (requested_quarter is None or _normalize_quarter(row.get("quarter")) == requested_quarter)
    }
    normalized_selected = list(selected_rows)
    expected_selected = set()
    stale_quarters: set[str] = set()
    for row in normalized_selected:
        row_quarter = _normalize_quarter(row.get("quarter") or quarter)
        ticker = _normalize_ticker(row.get("ticker"))
        if requested_quarter is not None and row_quarter != requested_quarter:
            if row_quarter:
                stale_quarters.add(row_quarter)
            continue
        expected_selected.add((row_quarter, ticker))
    panel_selected.discard(("", ""))
    expected_selected.discard(("", ""))
    if requested_quarter is not None and normalized_selected and not expected_selected:
        errors.append(
            {
                "code": f"{prefix}_selector_quarter_mismatch",
                "quarter": requested_quarter,
                "selector_quarters": sorted(stale_quarters),
            }
        )
        return
    if panel_selected != expected_selected:
        errors.append(
            {
                "code": f"{prefix}_identity_mismatch",
                "expected": sorted(expected_selected),
                "actual": sorted(panel_selected),
            }
        )


def _add_forbidden_selection_errors(
    rows: list[Mapping[str, Any]],
    forbidden_columns: set[str],
    errors: list[dict[str, Any]],
) -> None:
    if not forbidden_columns:
        return
    used_columns: set[str] = set()
    for row in rows:
        for field in RANKING_SOURCE_METADATA_FIELDS:
            used_columns.update(_split_columns(row.get(field)))
        metadata = row.get("selection_metadata")
        if isinstance(metadata, Mapping):
            used_columns.update(_split_columns(metadata.get("ranking_source_columns")))
    leaked = sorted(forbidden_columns.intersection(used_columns))
    for column in leaked:
        errors.append({"code": "forbidden_selection_column", "column": column})


def _split_columns(value) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        return {part.strip() for part in value.split(",") if part.strip()}
    if isinstance(value, Iterable):
        return {str(part).strip() for part in value if str(part).strip()}
    return set()


def _is_selected(value) -> bool:
    return str(value).strip() == "1"


def _is_blank(value) -> bool:
    return value is None or str(value).strip() == ""


def _normalize_ticker(value) -> str:
    return str(value or "").strip().upper()


def _normalize_quarter(value) -> str:
    return str(value or "").strip().upper()
