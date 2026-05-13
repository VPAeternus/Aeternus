from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

from tradingagents.research.fundamental.src.panel.normalize import normalize_complete_panel_rows
from tradingagents.research.fundamental.src.panel.schema import (
    COMPLETE_PANEL_SCHEMA_VERSION,
    REQUIRED_COMPLETE_PANEL_COLUMNS,
    REQUIRED_NONBLANK_FIELDS,
    default_for_field,
    missing_reason_field,
)
from tradingagents.research.fundamental.src.panel.selection_annotations import (
    attach_selection_annotations,
)
from tradingagents.research.fundamental.src.panel.validate import (
    FORBIDDEN_SELECTION_COLUMNS,
    validate_complete_panel,
)

REQUIRED_FINAL_SCORES_PATTERN = "fundamental_final_scores_*.csv"
OPTIONAL_ARTIFACT_NAMES = (
    "tier_classification.csv",
    "llm_eligibility.csv",
    "llm_quarantine.csv",
    "score_input_quarantine.csv",
    "post_llm_scores.csv",
    "high_conviction_top15.csv",
    "high_conviction_top15_core_deterioration_refill_shadow.csv",
)
RAW_PRIOR_FILENAMES = {
    "combined_all_tiers.csv",
    "combined_all_tiers_with_fundamentals.csv",
    "all_tiers.csv",
}


def build_complete_panel(
    run_root,
    output_root,
    quarter,
    as_of,
    prior_panel_path=None,
    allow_missing_financials=False,
    facts_by_ticker=None,
):
    """Build the canonical complete fundamental panel for one current quarter."""

    run_root = Path(run_root)
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    quarter = str(quarter).strip()
    as_of_date = _parse_date(as_of)

    final_scores_csv = _find_final_scores_csv(run_root)
    artifact_paths = _artifact_paths(run_root, final_scores_csv)
    final_rows = _read_csv(final_scores_csv)
    final_sha = _sha256_file(final_scores_csv)
    rows, normalize_summary = normalize_complete_panel_rows(
        final_rows,
        source_name="fundamental_final_scores",
        facts_by_ticker=facts_by_ticker,
        as_of=as_of_date if facts_by_ticker is not None else None,
        source_run_root=str(run_root),
        source_artifact=str(final_scores_csv),
        source_artifact_sha256=final_sha,
    )

    top15_path = run_root / "high_conviction_top15.csv"
    shadow_path = run_root / "high_conviction_top15_core_deterioration_refill_shadow.csv"
    rows, selection_summary = attach_selection_annotations(
        rows,
        quarter=quarter,
        top15_csv=top15_path if top15_path.exists() else None,
        shadow_csv=shadow_path if shadow_path.exists() else None,
        final_scores_csv=final_scores_csv if not top15_path.exists() or not shadow_path.exists() else None,
        output_root=output_root if not top15_path.exists() or not shadow_path.exists() else None,
        selection_date=as_of_date.isoformat(),
    )
    top15_path = _selection_source_path(selection_summary, "top15_csv")
    shadow_path = _selection_source_path(selection_summary, "shadow_csv")
    top15_rows = _read_csv(top15_path) if top15_path and top15_path.exists() else []
    shadow_rows = _read_csv(shadow_path) if shadow_path and shadow_path.exists() else []
    if top15_path and top15_path.exists():
        artifact_paths[top15_path.name] = top15_path
    if shadow_path and shadow_path.exists():
        artifact_paths[shadow_path.name] = shadow_path

    prior_errors: list[dict[str, Any]] = []
    prior_rows: list[dict[str, str]] = []
    if prior_panel_path is not None:
        prior_rows, prior_errors = _load_prior_panel(prior_panel_path)

    rows = _append_non_overlapping_prior_rows(rows, prior_rows)

    validation = validate_complete_panel(
        rows,
        required_columns=REQUIRED_COMPLETE_PANEL_COLUMNS,
        allowed_missing_reasons=_allowed_missing_reasons(allow_missing_financials),
        expected_quarters=_expected_quarters(rows),
        forbidden_selection_columns=FORBIDDEN_SELECTION_COLUMNS,
        quarter=quarter,
        top15_rows=top15_rows,
        shadow_rows=shadow_rows,
    )
    if prior_errors:
        validation = _with_extra_errors(validation, prior_errors)

    rows = [_ordered_row(row) for row in rows]

    stem = f"fundamental_complete_prellm_to_top15_{quarter}"
    csv_path = output_root / f"{stem}.csv"
    manifest_path = output_root / f"{stem}_manifest.json"
    columns_path = output_root / f"{stem}_columns.json"
    validation_path = output_root / f"{stem}_validation.json"

    _write_csv(csv_path, rows)
    output_sha = _sha256_file(csv_path)
    manifest = _build_manifest(
        rows,
        artifact_paths=artifact_paths,
        normalize_summary=normalize_summary,
        selection_summary=selection_summary,
        output_sha=output_sha,
    )
    _write_json(manifest_path, manifest)
    _write_json(
        columns_path,
        {
            "schema_version": COMPLETE_PANEL_SCHEMA_VERSION,
            "columns": list(REQUIRED_COMPLETE_PANEL_COLUMNS),
        },
    )
    _write_json(validation_path, validation)

    return {
        "csv_path": str(csv_path),
        "manifest_path": str(manifest_path),
        "columns_path": str(columns_path),
        "validation_path": str(validation_path),
        "validation": validation,
    }


def _find_final_scores_csv(run_root: Path) -> Path:
    matches = sorted(run_root.glob(REQUIRED_FINAL_SCORES_PATTERN))
    if not matches:
        raise FileNotFoundError(f"Missing required artifact: {REQUIRED_FINAL_SCORES_PATTERN}")
    return matches[-1]


def _artifact_paths(run_root: Path, final_scores_csv: Path) -> dict[str, Path]:
    paths = {final_scores_csv.name: final_scores_csv}
    for name in OPTIONAL_ARTIFACT_NAMES:
        path = run_root / name
        if path.exists():
            paths[name] = path
    return paths


def _selection_source_path(selection_summary: dict[str, Any], key: str) -> Path | None:
    source_paths = selection_summary.get("source_paths") or {}
    value = source_paths.get(key)
    return Path(value) if value else None


def _allowed_missing_reasons(allow_missing_financials: bool) -> set[str]:
    reasons = {
        "source_fact_unavailable_as_of",
        "not_populated_by_normalize",
        "not_applicable",
    }
    if allow_missing_financials:
        reasons.add("companyfacts_not_supplied")
    return reasons


def _load_prior_panel(prior_panel_path) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    path = Path(prior_panel_path)
    if _is_raw_legacy_prior(path):
        return [], [{"code": "prior_panel_not_canonical", "path": str(path)}]

    manifest_path = path.with_name(f"{path.stem}_manifest.json")
    validation_path = path.with_name(f"{path.stem}_validation.json")
    if not manifest_path.exists():
        return [], [{"code": "prior_panel_manifest_missing", "path": str(manifest_path)}]
    if not validation_path.exists():
        return [], [{"code": "prior_panel_validation_missing", "path": str(validation_path)}]

    manifest = _read_json(manifest_path)
    validation = _read_json(validation_path)
    if manifest.get("schema_version") != COMPLETE_PANEL_SCHEMA_VERSION:
        return [], [
            {
                "code": "prior_panel_schema_mismatch",
                "path": str(manifest_path),
                "expected": COMPLETE_PANEL_SCHEMA_VERSION,
                "actual": manifest.get("schema_version"),
            }
        ]
    if validation.get("passed") is not True:
        return [], [{"code": "prior_panel_validation_failed", "path": str(validation_path)}]
    return _read_csv(path), []


def _is_raw_legacy_prior(path: Path) -> bool:
    parts = {part.lower() for part in path.parts}
    name = path.name.lower()
    return "growth" in parts or name in RAW_PRIOR_FILENAMES or name.startswith("combined_all_tiers")


def _append_non_overlapping_prior_rows(
    current_rows: list[dict[str, Any]],
    prior_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    current_keys = {_key(row) for row in current_rows}
    out = [dict(row) for row in current_rows]
    for row in prior_rows:
        key = _key(row)
        if not all(key) or key in current_keys:
            continue
        out.append(dict(row))
        current_keys.add(key)
    return out


def _expected_quarters(rows: list[dict[str, Any]]) -> list[str]:
    return sorted({str(row.get("quarter", "")).strip() for row in rows if row.get("quarter")})


def _ordered_row(row: dict[str, Any]) -> dict[str, str]:
    return {
        field: _stringify(row.get(field, default_for_field(field)))
        for field in REQUIRED_COMPLETE_PANEL_COLUMNS
    }


def _build_manifest(
    rows: list[dict[str, str]],
    *,
    artifact_paths: dict[str, Path],
    normalize_summary: dict[str, Any],
    selection_summary: dict[str, Any],
    output_sha: str,
) -> dict[str, Any]:
    blank_counts = {
        field: sum(1 for row in rows if _is_blank(row.get(field)))
        for field in REQUIRED_NONBLANK_FIELDS
    }
    missing_reasons: dict[str, dict[str, int]] = {}
    for field in REQUIRED_NONBLANK_FIELDS:
        reason_field = missing_reason_field(field)
        counts = Counter(
            str(row.get(reason_field, "")).strip()
            for row in rows
            if _is_blank(row.get(field)) and str(row.get(reason_field, "")).strip()
        )
        if counts:
            missing_reasons[field] = dict(sorted(counts.items()))

    return {
        "schema_version": COMPLETE_PANEL_SCHEMA_VERSION,
        "source_artifact_hashes": {
            name: _sha256_file(path) for name, path in sorted(artifact_paths.items())
        },
        "row_count": len(rows),
        "row_counts_by_quarter": dict(sorted(Counter(row["quarter"] for row in rows).items())),
        "blank_counts_by_required_field": blank_counts,
        "missing_reasons_by_field": missing_reasons,
        "top15_selected_count": sum(1 for row in rows if row.get("top15_selected") == "1"),
        "shadow_selected_count": sum(1 for row in rows if row.get("shadow_selected") == "1"),
        "selection_summary": selection_summary,
        "normalize_summary": normalize_summary,
        "output_sha256": output_sha,
    }


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return [{key: value for key, value in row.items()} for row in csv.DictReader(handle)]


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=REQUIRED_COMPLETE_PANEL_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def _read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _with_extra_errors(validation: dict[str, Any], errors: list[dict[str, Any]]) -> dict[str, Any]:
    out = dict(validation)
    out["errors"] = list(out.get("errors", [])) + errors
    out["passed"] = False
    return out


def _key(row: dict[str, Any]) -> tuple[str, str]:
    return (
        str(row.get("quarter", "")).strip().upper(),
        str(row.get("ticker", "")).strip().upper(),
    )


def _parse_date(value) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _is_blank(value: Any) -> bool:
    return value is None or str(value).strip() == ""


def _stringify(value: Any) -> str:
    return "" if value is None else str(value)
