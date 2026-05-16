from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from tradingagents.research.fundamental.src.panel.schema import FLAG_FIELDS
from tradingagents.research.fundamental.src.selection.high_conviction_top10 import (
    select_top15_core_deterioration_refill_shadow_from_csv,
    select_top15_from_csv,
)

TOP15_METADATA_FIELDS = {
    "selection_rank": "top15_selection_rank",
    "selected_sleeve": "top15_selected_sleeve",
    "selected_sleeve_rank": "top15_selected_sleeve_rank",
    "variant": "top15_variant",
    "top15_bucket": "top15_bucket",
    "top15_bucket_order": "top15_bucket_order",
    "top15_role": "top15_role",
    "top15_model": "top15_model",
    "portfolio_treatment": "top15_portfolio_treatment",
    "top15_portfolio_treatment": "top15_portfolio_treatment",
    "operating_setting": "top15_operating_setting",
    "top15_operating_setting": "top15_operating_setting",
    "operating_setting_validation_status": "top15_operating_setting_validation_status",
    "top15_operating_setting_validation_status": "top15_operating_setting_validation_status",
    "reason_codes": "top15_reason_codes",
    "top15_reason_codes": "top15_reason_codes",
    "override_reason_codes": "top15_override_reason_codes",
    "top15_override_reason_codes": "top15_override_reason_codes",
    "right_tail_exception_score": "top15_right_tail_exception_score",
    "right_tail_exception_reason_codes": "top15_right_tail_exception_reason_codes",
    "right_tail_exception_warning_codes": "top15_right_tail_exception_warning_codes",
    "right_tail_exception_score_contributions": (
        "top15_right_tail_exception_score_contributions"
    ),
}

SHADOW_METADATA_FIELDS = {
    "selection_rank": "shadow_selection_rank",
    "selected_sleeve": "shadow_selected_sleeve",
    "selected_sleeve_rank": "shadow_selected_sleeve_rank",
    "variant": "shadow_variant",
    "top15_bucket": "shadow_top15_bucket",
    "top15_bucket_order": "shadow_top15_bucket_order",
    "top15_role": "shadow_top15_role",
    "top15_model": "shadow_top15_model",
    "portfolio_treatment": "shadow_portfolio_treatment",
    "core_refill_source": "shadow_core_refill_source",
    "demoted_replacement_for": "shadow_demoted_replacement_for",
    "shadow_refill_status": "shadow_refill_status",
    "right_tail_exception_score": "shadow_right_tail_exception_score",
    "right_tail_exception_reason_codes": "shadow_right_tail_exception_reason_codes",
    "right_tail_exception_warning_codes": "shadow_right_tail_exception_warning_codes",
    "right_tail_exception_score_contributions": (
        "shadow_right_tail_exception_score_contributions"
    ),
}

TOP15_FLAG_FIELDS = tuple(
    field for field in FLAG_FIELDS if field == "top15_selected" or field.startswith("top15_")
)
SHADOW_FLAG_FIELDS = tuple(
    field for field in FLAG_FIELDS if field == "shadow_selected" or field.startswith("shadow_")
)


def attach_selection_annotations(
    rows: list[dict[str, Any]],
    *,
    quarter: str,
    top15_csv: str | Path | None = None,
    shadow_csv: str | Path | None = None,
    final_scores_csv: str | Path | None = None,
    output_root: str | Path | None = None,
    coverage_manifest: str | Path | None = None,
    selection_date: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Attach canonical Top15 and shadow-refill annotations to panel rows."""

    top15_path = _resolve_top15_path(
        top15_csv=top15_csv,
        final_scores_csv=final_scores_csv,
        output_root=output_root,
        coverage_manifest=coverage_manifest,
        selection_date=selection_date,
    )
    shadow_path = _resolve_shadow_path(
        shadow_csv=shadow_csv,
        final_scores_csv=final_scores_csv,
        output_root=output_root,
        coverage_manifest=coverage_manifest,
        selection_date=selection_date,
    )

    output_rows = [dict(row) for row in rows]
    panel_keys = {
        (_normalize_quarter(row.get("quarter")), _normalize_ticker(row.get("ticker")))
        for row in output_rows
        if _normalize_quarter(row.get("quarter")) == quarter
    }

    top15_by_key = _selection_rows_by_key(top15_path, quarter) if top15_path else {}
    shadow_by_key = _selection_rows_by_key(shadow_path, quarter) if shadow_path else {}
    top15_missing = _missing_tickers(top15_by_key, panel_keys)
    shadow_missing = _missing_tickers(shadow_by_key, panel_keys)
    if top15_missing or shadow_missing:
        parts = []
        if top15_missing:
            parts.append(f"top15 missing selected tickers: {', '.join(top15_missing)}")
        if shadow_missing:
            parts.append(f"shadow missing selected tickers: {', '.join(shadow_missing)}")
        raise ValueError(
            f"Selection annotations reference tickers absent from {quarter} panel rows: "
            + "; ".join(parts)
        )

    annotated = [
        _annotate_row(
            row,
            quarter=quarter,
            top15_selection=top15_by_key.get(
                (_normalize_quarter(row.get("quarter")), _normalize_ticker(row.get("ticker")))
            ),
            shadow_selection=shadow_by_key.get(
                (_normalize_quarter(row.get("quarter")), _normalize_ticker(row.get("ticker")))
            ),
        )
        for row in output_rows
    ]

    summary = {
        "quarter": quarter,
        "official_selected_count": len(top15_by_key),
        "top15_selected_count": len(top15_by_key),
        "shadow_selected_count": len(shadow_by_key),
        "top15_missing_selected_tickers": top15_missing,
        "shadow_missing_selected_tickers": shadow_missing,
        "top15_source_path": str(top15_path) if top15_path else "",
        "shadow_source_path": str(shadow_path) if shadow_path else "",
        "source_paths": {
            "top15_csv": str(top15_path) if top15_path else "",
            "shadow_csv": str(shadow_path) if shadow_path else "",
        },
    }
    return annotated, summary


def _resolve_top15_path(
    *,
    top15_csv: str | Path | None,
    final_scores_csv: str | Path | None,
    output_root: str | Path | None,
    coverage_manifest: str | Path | None,
    selection_date: str | None,
) -> Path | None:
    if top15_csv:
        return Path(top15_csv)
    if final_scores_csv and output_root:
        result = select_top15_from_csv(
            final_scores_csv,
            output_root,
            _top15_config(selection_date),
            coverage_manifest,
        )
        return _path_from_result(result, "high_conviction_top15.csv", output_root)
    return None


def _resolve_shadow_path(
    *,
    shadow_csv: str | Path | None,
    final_scores_csv: str | Path | None,
    output_root: str | Path | None,
    coverage_manifest: str | Path | None,
    selection_date: str | None,
) -> Path | None:
    if shadow_csv:
        return Path(shadow_csv)
    if final_scores_csv and output_root:
        result = select_top15_core_deterioration_refill_shadow_from_csv(
            final_scores_csv,
            output_root,
            _shadow_config(selection_date),
            coverage_manifest,
        )
        return _path_from_result(
            result,
            "high_conviction_top15_core_deterioration_refill_shadow.csv",
            output_root,
        )
    return None


def _top15_config(selection_date: str | None) -> dict[str, Any]:
    config: dict[str, Any] = {
        "enabled": True,
        "core_n": 10,
        "exception_slots": 5,
    }
    if selection_date:
        config["selection_date"] = selection_date
    return config


def _shadow_config(selection_date: str | None) -> dict[str, Any]:
    config = _top15_config(selection_date)
    config["core_deterioration_refill"] = {"enabled": True, "mode": "strict"}
    return config


def _path_from_result(result: dict[str, Any], fallback_name: str, output_root: str | Path) -> Path:
    output_paths = result.get("output_paths") or {}
    csv_path = output_paths.get("csv")
    return Path(csv_path) if csv_path else Path(output_root) / fallback_name


def _selection_rows_by_key(path: Path, quarter: str) -> dict[tuple[str, str], dict[str, str]]:
    by_key: dict[tuple[str, str], dict[str, str]] = {}
    for row in _read_csv(path):
        ticker = _normalize_ticker(row.get("ticker") or row.get("symbol"))
        if not ticker:
            continue
        row_quarter = _normalize_quarter(row.get("quarter")) or quarter
        if row_quarter != quarter:
            continue
        row = dict(row)
        if not _has_value(row.get("selection_rank")):
            row["selection_rank"] = str(len(by_key) + 1)
        by_key[(quarter, ticker)] = row
    return by_key


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"Selection annotation source not found: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        return [{key: value for key, value in row.items()} for row in csv.DictReader(handle)]


def _missing_tickers(
    selected_by_key: dict[tuple[str, str], dict[str, str]],
    panel_keys: set[tuple[str, str]],
) -> list[str]:
    return sorted(
        ticker
        for (_quarter, ticker) in selected_by_key
        if (_quarter, ticker) not in panel_keys
    )


def _annotate_row(
    row: dict[str, Any],
    *,
    quarter: str,
    top15_selection: dict[str, str] | None,
    shadow_selection: dict[str, str] | None,
) -> dict[str, Any]:
    out = dict(row)
    is_requested_quarter = _normalize_quarter(out.get("quarter")) == quarter

    if is_requested_quarter:
        if top15_selection:
            out["top15_selected"] = "1"
            out["top15_any_variant_selected"] = "1"
            _copy_metadata(out, top15_selection, TOP15_METADATA_FIELDS, "top15_")
            _fill_default_variant(
                out,
                variant_field="top15_variant",
                variants_field="top15_variants_selected",
                variant=f"high_conviction_top15_current_operating_{quarter}",
            )
            _fill_if_blank(out, "top15_reason_codes", "[]")
            _fill_if_blank(out, "top15_override_reason_codes", "[]")
        else:
            for field in TOP15_FLAG_FIELDS:
                out[field] = "0"

        if shadow_selection:
            out["shadow_selected"] = "1"
            out["shadow_any_variant_selected"] = "1"
            _copy_metadata(out, shadow_selection, SHADOW_METADATA_FIELDS, "shadow_")
            _fill_default_variant(
                out,
                variant_field="shadow_variant",
                variants_field="shadow_variants_selected",
                variant=(
                    "high_conviction_top15_v4_core_deterioration_refill_shadow"
                    f"_current_{quarter}"
                ),
            )
        else:
            for field in SHADOW_FLAG_FIELDS:
                out[field] = "0"

    return out


def _copy_metadata(
    out: dict[str, Any],
    selection: dict[str, str],
    field_map: dict[str, str],
    prefix: str,
) -> None:
    for source, target in field_map.items():
        value = selection.get(source)
        if _has_value(value):
            out[target] = value
    for source, value in selection.items():
        if source in {f"{prefix}selected", f"{prefix}any_variant_selected"}:
            continue
        if source.startswith(prefix) and _has_value(value):
            out[source] = value


def _fill_default_variant(
    out: dict[str, Any],
    *,
    variant_field: str,
    variants_field: str,
    variant: str,
) -> None:
    if not _has_value(out.get(variant_field)):
        out[variant_field] = variant
    if not _has_value(out.get(variants_field)):
        out[variants_field] = out[variant_field]


def _fill_if_blank(out: dict[str, Any], field: str, value: str) -> None:
    if not _has_value(out.get(field)):
        out[field] = value


def _normalize_ticker(value: Any) -> str:
    return "" if value is None else str(value).strip().upper()


def _normalize_quarter(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _has_value(value: Any) -> bool:
    return value is not None and str(value).strip() != ""
