"""Point-in-time fundamental backtest panel exporter.

Builds one ticker-quarter signal row per input row. Selection-time features,
outcome labels, and audit metadata are kept in explicit, separate schemas.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

SELECTION_FEATURE_COLUMNS = [
    "ticker",
    "quarter",
    "tradable_date",
    "entry_open",
    "entry_qoq_pct",
    "prior_entry_qoq_pct",
    "score_change",
    "pre_llm_fundamental_score",
    "pre_llm_fundamental_bucket",
    "revenue_bucket",
    "tier_0_bucket",
    "tier_1_bucket",
    "tier_2_bucket",
    "tier_3_bucket",
    "tier_4_bucket",
    "hp0_high_price_broad",
    "hp1_quality_pullback",
    "hp2_dislocation_momentum_priority",
    "hp2_dislocation_momentum_watch",
    "hp3_large_quality_theme_exception",
    "hp4_score_reacceleration_watch",
    "hp_production_extension",
    "hp_research_extension",
    "hp_LLM_best",
    "rm1_low_price_dislocation_momentum",
    "rm2_weak_acceleration",
    "rm3_mid_price_dislocation_momentum",
    "rm4_persistent_repricing_wave",
    "repricing_momentum_extension",
    "repricing_momentum_priority",
    "market_repricing_score",
    "rm_buy_review_flag",
    "post_llm_candidate_flag",
    "post_llm_high_priority_flag",
    "post_llm_demote_flag",
    "causal_change",
    "negative_revision_risk",
    "narrative_delta_bucket",
    "operating_leverage_quality",
    "durability",
    "score_addition",
    "primary_theme",
    "secondary_themes",
    "theme_role",
    "theme_confidence",
    "theme_driver_type",
    "theme_momentum",
    "theme_acceleration_score",
    "theme_tailwind_score",
    "theme_acceleration_research_visibility",
    "theme_acceleration_rescan_flag",
    "akg_universe_tier",
    "macro_mode",
    "macro_spy",
    "macro_entry_action",
    "macro_position_size_multiplier",
    "tier_structure_score",
    "hp_structure_score",
    "total_structure_score",
    "llm_business_improvement_score",
    "fundamental_rerating_score",
    "risk_penalty_score",
    "entry_raw_score",
    "entry_score_0_100",
]

OUTCOME_LABEL_COLUMNS = [
    "return_10d_pct",
    "return_20d_pct",
    "return_30d_pct",
    "return_60d_pct",
    "return_90d_pct",
    "winner_90d_30pct",
    "loser_90d_minus30pct",
    "is_partial_live_quarter",
    "is_future_date_anomaly",
    "eligible_for_backtest",
]

METADATA_COLUMNS = [
    "pipeline_run_id",
    "scoring_formula_version",
    "tier_rule_version",
    "hp_rule_version",
    "rm_rule_version",
    "theme_rule_version",
    "macro_rule_version",
    "source_file_hash",
]

FORBIDDEN_SELECTION_COLUMNS = set(OUTCOME_LABEL_COLUMNS) | {
    "future_return_pct",
    "forward_return_pct",
    "max_forward_return_pct",
    "label",
    "target",
}

REQUIRED_ELIGIBILITY_COLUMNS = ["ticker", "quarter", "tradable_date", "entry_open"]
DEFAULT_OUTPUT_DIR = Path("outputs/fundamental_backtest")


def _assert_schema_guardrails() -> None:
    overlap = set(SELECTION_FEATURE_COLUMNS) & FORBIDDEN_SELECTION_COLUMNS
    if overlap:
        raise ValueError(f"Forbidden outcome columns in selection schema: {sorted(overlap)}")


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _parse_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _float_or_none(value: Any) -> float | None:
    text = str(value or "").strip()
    if text == "":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _bool_text(value: bool) -> str:
    return "True" if value else "False"


def _read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
        return rows, list(reader.fieldnames or [])


def _write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _schema(columns: Iterable[str], missing: dict[str, list[str]]) -> dict[str, Any]:
    return {
        "columns": list(columns),
        "missing_fields_by_source": missing,
        "guardrail": "Outcome labels are excluded from selection features.",
    }


def build_pit_panel(
    input_csvs: Iterable[str | Path],
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    as_of_date: str | date | None = None,
    pipeline_run_id: str | None = None,
) -> dict[str, Any]:
    """Build PIT fundamental panel and sidecar schemas/manifest."""
    _assert_schema_guardrails()
    paths = [Path(p) for p in input_csvs]
    if not paths:
        raise ValueError("At least one input CSV is required")

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    run_id = pipeline_run_id or f"pit-{uuid4()}"
    cutoff = as_of_date if isinstance(as_of_date, date) else _parse_date(as_of_date) if as_of_date else date.today()

    rows: list[dict[str, Any]] = []
    missing_selection: dict[str, list[str]] = {}
    missing_labels: dict[str, list[str]] = {}
    missing_metadata: dict[str, list[str]] = {}
    input_manifest: list[dict[str, Any]] = []

    for path in paths:
        source_rows, source_fieldnames = _read_csv(path)
        fieldnames = set(source_fieldnames)
        source_hash = _file_sha256(path)
        missing_selection[str(path)] = [c for c in SELECTION_FEATURE_COLUMNS if c not in fieldnames]
        missing_labels[str(path)] = [c for c in OUTCOME_LABEL_COLUMNS if c not in fieldnames and c not in {"winner_90d_30pct", "loser_90d_minus30pct", "is_future_date_anomaly", "eligible_for_backtest"}]
        missing_metadata[str(path)] = [c for c in METADATA_COLUMNS if c not in fieldnames and c not in {"pipeline_run_id", "source_file_hash"}]
        input_manifest.append({"path": str(path), "sha256": source_hash, "row_count": len(source_rows)})

        for raw in source_rows:
            row: dict[str, Any] = {c: raw.get(c, "") for c in SELECTION_FEATURE_COLUMNS}
            row.update({c: raw.get(c, "") for c in OUTCOME_LABEL_COLUMNS})
            row.update({c: raw.get(c, "") for c in METADATA_COLUMNS})

            tradable = _parse_date(row.get("tradable_date"))
            is_future = bool(tradable and cutoff and tradable > cutoff)
            ret90 = _float_or_none(row.get("return_90d_pct"))
            row["winner_90d_30pct"] = _bool_text(ret90 is not None and ret90 >= 30.0)
            row["loser_90d_minus30pct"] = _bool_text(ret90 is not None and ret90 <= -30.0)
            row["is_future_date_anomaly"] = _bool_text(is_future)
            missing_required = any(str(row.get(c, "")).strip() == "" for c in REQUIRED_ELIGIBILITY_COLUMNS)
            row["eligible_for_backtest"] = _bool_text(not missing_required and not is_future and ret90 is not None)
            row["pipeline_run_id"] = row.get("pipeline_run_id") or run_id
            row["source_file_hash"] = source_hash
            rows.append(row)

    columns = SELECTION_FEATURE_COLUMNS + OUTCOME_LABEL_COLUMNS + METADATA_COLUMNS
    panel_path = out / "pit_fundamental_panel.csv"
    _write_csv(panel_path, rows, columns)

    feature_schema = _schema(SELECTION_FEATURE_COLUMNS, missing_selection)
    label_schema = _schema(OUTCOME_LABEL_COLUMNS, missing_labels)
    feature_schema["forbidden_selection_columns"] = sorted(FORBIDDEN_SELECTION_COLUMNS)
    feature_schema["forbidden_overlap"] = sorted(set(SELECTION_FEATURE_COLUMNS) & FORBIDDEN_SELECTION_COLUMNS)
    label_schema["derived_labels"] = {"winner_90d_30pct": "return_90d_pct >= 30", "loser_90d_minus30pct": "return_90d_pct <= -30"}

    manifest = {
        "pipeline_run_id": run_id,
        "as_of_date": cutoff.isoformat() if cutoff else None,
        "row_count": len(rows),
        "input_files": input_manifest,
        "missing_selection_fields_by_source": missing_selection,
        "missing_label_fields_by_source": missing_labels,
        "missing_metadata_fields_by_source": missing_metadata,
        "selection_feature_columns": SELECTION_FEATURE_COLUMNS,
        "outcome_label_columns": OUTCOME_LABEL_COLUMNS,
        "metadata_columns": METADATA_COLUMNS,
        "forbidden_selection_columns": sorted(FORBIDDEN_SELECTION_COLUMNS),
    }

    (out / "feature_schema.json").write_text(json.dumps(feature_schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out / "label_schema.json").write_text(json.dumps(label_schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out / "run_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out / "README_ANALYSIS.md").write_text(_readme(), encoding="utf-8")
    return manifest


def _readme() -> str:
    return """# Fundamental PIT Backtest Panel

`pit_fundamental_panel.csv` separates selection-time features from outcome labels.

- Selection schema: `feature_schema.json`
- Outcome schema: `label_schema.json`
- Audit manifest: `run_manifest.json`

Guardrails:
- Outcome labels are not selection features.
- `winner_90d_30pct` and `loser_90d_minus30pct` derive only from `return_90d_pct`.
- `eligible_for_backtest` is false for missing key selection fields, future-date anomalies, or missing 90-day return labels.
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build PIT fundamental backtest panel")
    parser.add_argument("input_csvs", nargs="+", help="Final-score/candidate-score CSV path(s)")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--as-of-date", default=None, help="Run/as-of date for future-date anomaly checks")
    parser.add_argument("--pipeline-run-id", default=None)
    args = parser.parse_args(argv)
    manifest = build_pit_panel(args.input_csvs, args.output_dir, args.as_of_date, args.pipeline_run_id)
    print(json.dumps({"row_count": manifest["row_count"], "output_dir": args.output_dir}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
