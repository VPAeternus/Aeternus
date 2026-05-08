import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tradingagents.research.fundamental.backtests.pit_panel import (
    FORBIDDEN_SELECTION_COLUMNS,
    OUTCOME_LABEL_COLUMNS,
    SELECTION_FEATURE_COLUMNS,
    build_pit_panel,
)


def _write_csv(path: Path, rows, fieldnames=None):
    fieldnames = fieldnames or sorted({k for row in rows for k in row})
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _read_panel(path: Path):
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def test_output_contains_required_columns_when_input_missing_fields(tmp_path):
    input_csv = tmp_path / "scores.csv"
    _write_csv(input_csv, [{"ticker": "A", "quarter": "2025Q4", "tradable_date": "2026-01-05", "entry_open": "10", "return_90d_pct": "31"}])

    out = tmp_path / "out"
    build_pit_panel([input_csv], out, as_of_date="2026-01-06")

    rows = _read_panel(out / "pit_fundamental_panel.csv")
    assert rows[0]["ticker"] == "A"
    for column in SELECTION_FEATURE_COLUMNS + OUTCOME_LABEL_COLUMNS:
        assert column in rows[0]
    assert rows[0]["entry_qoq_pct"] == ""


def test_forbidden_label_columns_not_in_selection_schema(tmp_path):
    input_csv = tmp_path / "scores.csv"
    _write_csv(input_csv, [{"ticker": "A", "quarter": "2025Q4", "tradable_date": "2026-01-05", "entry_open": "10", "return_90d_pct": "10"}])

    out = tmp_path / "out"
    build_pit_panel([input_csv], out, as_of_date="2026-01-06")

    schema = json.loads((out / "feature_schema.json").read_text())
    assert set(schema["columns"]).isdisjoint(FORBIDDEN_SELECTION_COLUMNS)
    assert schema["forbidden_overlap"] == []


def test_invalid_as_of_date_fails_fast(tmp_path):
    input_csv = tmp_path / "scores.csv"
    _write_csv(input_csv, [{"ticker": "A", "quarter": "2025Q4", "tradable_date": "2099-01-05", "entry_open": "10", "return_90d_pct": "10"}])

    with pytest.raises(ValueError, match="Invalid --as-of-date"):
        build_pit_panel([input_csv], tmp_path / "out", as_of_date="not-a-date")


def test_cli_invalid_as_of_date_exits_cleanly(tmp_path):
    input_csv = tmp_path / "scores.csv"
    _write_csv(input_csv, [{"ticker": "A", "quarter": "2025Q4", "tradable_date": "2099-01-05", "entry_open": "10", "return_90d_pct": "10"}])

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tradingagents.research.fundamental.backtests.pit_panel",
            str(input_csv),
            "--output-dir",
            str(tmp_path / "out"),
            "--as-of-date",
            "bogus",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "Invalid --as-of-date" in result.stderr
    assert "Traceback" not in result.stderr


def test_no_header_csv_errors_by_default(tmp_path):
    input_csv = tmp_path / "empty.csv"
    input_csv.write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="no header row"):
        build_pit_panel([input_csv], tmp_path / "out", as_of_date="2026-01-06")


def test_cli_no_header_csv_exits_cleanly(tmp_path):
    input_csv = tmp_path / "empty.csv"
    input_csv.write_text("", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tradingagents.research.fundamental.backtests.pit_panel",
            str(input_csv),
            "--output-dir",
            str(tmp_path / "out"),
            "--as-of-date",
            "2026-01-06",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "no header row" in result.stderr
    assert "Traceback" not in result.stderr


def test_header_only_csv_preserves_manifest_fieldnames(tmp_path):
    input_csv = tmp_path / "scores.csv"
    _write_csv(input_csv, [], fieldnames=["ticker", "quarter", "tradable_date", "entry_open", "return_90d_pct"])

    out = tmp_path / "out"
    build_pit_panel([input_csv], out, as_of_date="2026-01-06")

    manifest = json.loads((out / "run_manifest.json").read_text())
    missing_selection = manifest["missing_selection_fields_by_source"][str(input_csv)]
    missing_labels = manifest["missing_label_fields_by_source"][str(input_csv)]
    assert "ticker" not in missing_selection
    assert "quarter" not in missing_selection
    assert "tradable_date" not in missing_selection
    assert "entry_open" not in missing_selection
    assert "return_90d_pct" not in missing_labels
    assert manifest["input_files"][0]["row_count"] == 0


def test_future_date_anomaly_and_eligibility_behavior(tmp_path):
    input_csv = tmp_path / "scores.csv"
    _write_csv(
        input_csv,
        [
            {"ticker": "FUT", "quarter": "2025Q4", "tradable_date": "2026-01-07", "entry_open": "10", "return_90d_pct": "40"},
            {"ticker": "OK", "quarter": "2025Q4", "tradable_date": "2026-01-05", "entry_open": "10", "return_90d_pct": "40"},
        ],
    )

    out = tmp_path / "out"
    build_pit_panel([input_csv], out, as_of_date="2026-01-06")

    by_ticker = {r["ticker"]: r for r in _read_panel(out / "pit_fundamental_panel.csv")}
    assert by_ticker["FUT"]["is_future_date_anomaly"] == "True"
    assert by_ticker["FUT"]["eligible_for_backtest"] == "False"
    assert by_ticker["OK"]["eligible_for_backtest"] == "True"


def test_winner_loser_labels_derive_from_return_90d_pct(tmp_path):
    input_csv = tmp_path / "scores.csv"
    _write_csv(
        input_csv,
        [
            {"ticker": "WIN", "quarter": "2025Q4", "tradable_date": "2026-01-05", "entry_open": "10", "return_90d_pct": "30"},
            {"ticker": "LOSE", "quarter": "2025Q4", "tradable_date": "2026-01-05", "entry_open": "10", "return_90d_pct": "-30"},
            {"ticker": "MID", "quarter": "2025Q4", "tradable_date": "2026-01-05", "entry_open": "10", "return_90d_pct": "5"},
        ],
    )

    out = tmp_path / "out"
    build_pit_panel([input_csv], out, as_of_date="2026-01-06")

    by_ticker = {r["ticker"]: r for r in _read_panel(out / "pit_fundamental_panel.csv")}
    assert by_ticker["WIN"]["winner_90d_30pct"] == "True"
    assert by_ticker["LOSE"]["loser_90d_minus30pct"] == "True"
    assert by_ticker["MID"]["winner_90d_30pct"] == "False"
    assert by_ticker["MID"]["loser_90d_minus30pct"] == "False"


def test_manifest_includes_hashes_versions_and_missing_fields(tmp_path):
    input_csv = tmp_path / "scores.csv"
    _write_csv(input_csv, [{"ticker": "A", "quarter": "2025Q4", "tradable_date": "2026-01-05", "entry_open": "10", "return_90d_pct": "10"}])

    out = tmp_path / "out"
    build_pit_panel([input_csv], out, as_of_date="2026-01-06")

    manifest = json.loads((out / "run_manifest.json").read_text())
    assert manifest["panel_version"] == "fundamental_pit_panel_v1"
    assert manifest["schema_version"] == "fundamental_pit_schema_v1"
    assert manifest["input_files"][0]["path"] == str(input_csv)
    assert len(manifest["input_files"][0]["sha256"]) == 64
    assert {p["path"] for p in manifest["output_files"]} == {str(out / name) for name in {"pit_fundamental_panel.csv", "feature_schema.json", "label_schema.json", "README_ANALYSIS.md"}}
    assert all(len(p["sha256"]) == 64 for p in manifest["output_files"])
    assert "entry_qoq_pct" in manifest["missing_selection_fields_by_source"][str(input_csv)]
    assert "return_10d_pct" in manifest["missing_label_fields_by_source"][str(input_csv)]


def test_module_cli_smoke_writes_exact_sidecars(tmp_path):
    input_csv = tmp_path / "scores.csv"
    _write_csv(input_csv, [{"ticker": "A", "quarter": "2025Q4", "tradable_date": "2026-01-05", "entry_open": "10", "return_90d_pct": "10"}])
    out = tmp_path / "out"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tradingagents.research.fundamental.backtests.pit_panel",
            str(input_csv),
            "--output-dir",
            str(out),
            "--as-of-date",
            "2026-01-06",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(result.stdout)["row_count"] == 1
    assert {p.name for p in out.iterdir()} == {
        "pit_fundamental_panel.csv",
        "feature_schema.json",
        "label_schema.json",
        "run_manifest.json",
        "README_ANALYSIS.md",
    }


def test_multiple_input_files_append_rows_deterministically(tmp_path):
    first = tmp_path / "first.csv"
    second = tmp_path / "second.csv"
    _write_csv(first, [{"ticker": "A", "quarter": "2025Q4", "tradable_date": "2026-01-05", "entry_open": "10", "return_90d_pct": "10"}])
    _write_csv(second, [{"ticker": "B", "quarter": "2025Q4", "tradable_date": "2026-01-05", "entry_open": "20", "return_90d_pct": "20"}])

    out = tmp_path / "out"
    build_pit_panel([first, second], out, as_of_date="2026-01-06")

    rows = _read_panel(out / "pit_fundamental_panel.csv")
    assert [r["ticker"] for r in rows] == ["A", "B"]


def test_metadata_columns_exist_in_output(tmp_path):
    input_csv = tmp_path / "scores.csv"
    _write_csv(input_csv, [{"ticker": "A", "quarter": "2025Q4", "tradable_date": "2026-01-05", "entry_open": "10", "return_90d_pct": "10"}])

    out = tmp_path / "out"
    build_pit_panel([input_csv], out, as_of_date="2026-01-06", pipeline_run_id="run-1")

    with (out / "pit_fundamental_panel.csv").open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        metadata = {"pipeline_run_id", "scoring_formula_version", "tier_rule_version", "hp_rule_version", "rm_rule_version", "theme_rule_version", "macro_rule_version", "source_file_hash"}
        assert metadata.issubset(reader.fieldnames or [])
        row = next(reader)
    assert row["pipeline_run_id"] == "run-1"
    assert len(row["source_file_hash"]) == 64


def test_missing_required_eligibility_fields_are_not_backtest_eligible(tmp_path):
    input_csv = tmp_path / "scores.csv"
    _write_csv(
        input_csv,
        [
            {"ticker": "", "quarter": "2025Q4", "tradable_date": "2026-01-05", "entry_open": "10", "return_90d_pct": "10"},
            {"ticker": "MISSQ", "quarter": "", "tradable_date": "2026-01-05", "entry_open": "10", "return_90d_pct": "10"},
            {"ticker": "MISSD", "quarter": "2025Q4", "tradable_date": "", "entry_open": "10", "return_90d_pct": "10"},
            {"ticker": "MISSO", "quarter": "2025Q4", "tradable_date": "2026-01-05", "entry_open": "", "return_90d_pct": "10"},
        ],
    )

    out = tmp_path / "out"
    build_pit_panel([input_csv], out, as_of_date="2026-01-06")

    rows = _read_panel(out / "pit_fundamental_panel.csv")
    assert [r["eligible_for_backtest"] for r in rows] == ["False", "False", "False", "False"]


def test_readme_and_schemas_separate_selection_features_and_labels(tmp_path):
    input_csv = tmp_path / "scores.csv"
    _write_csv(input_csv, [{"ticker": "A", "quarter": "2025Q4", "tradable_date": "2026-01-05", "entry_open": "10", "return_90d_pct": "10"}])

    out = tmp_path / "out"
    build_pit_panel([input_csv], out, as_of_date="2026-01-06")

    feature_schema = json.loads((out / "feature_schema.json").read_text())
    label_schema = json.loads((out / "label_schema.json").read_text())
    readme = (out / "README_ANALYSIS.md").read_text()
    assert "return_10d_pct" in label_schema["columns"]
    assert "return_10d_pct" not in feature_schema["columns"]
    assert "selection-time features" in readme
    assert "outcome labels" in readme
