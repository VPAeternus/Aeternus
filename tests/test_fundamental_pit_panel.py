import csv
import json
from pathlib import Path

from tradingagents.research.fundamental.backtests.pit_panel import (
    FORBIDDEN_SELECTION_COLUMNS,
    OUTCOME_LABEL_COLUMNS,
    SELECTION_FEATURE_COLUMNS,
    build_pit_panel,
)


def _write_csv(path: Path, rows):
    fieldnames = sorted({k for row in rows for k in row})
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
    assert by_ticker["WIN"]["loser_90d_minus30pct"] == "False"
    assert by_ticker["LOSE"]["winner_90d_30pct"] == "False"
    assert by_ticker["LOSE"]["loser_90d_minus30pct"] == "True"
    assert by_ticker["MID"]["winner_90d_30pct"] == "False"
    assert by_ticker["MID"]["loser_90d_minus30pct"] == "False"


def test_future_date_anomaly_and_eligibility_behavior(tmp_path):
    input_csv = tmp_path / "scores.csv"
    _write_csv(
        input_csv,
        [
            {"ticker": "FUT", "quarter": "2025Q4", "tradable_date": "2026-01-07", "entry_open": "10", "return_90d_pct": "40"},
            {"ticker": "MISS", "quarter": "2025Q4", "tradable_date": "2026-01-05", "entry_open": "", "return_90d_pct": "40"},
            {"ticker": "NOLABEL", "quarter": "2025Q4", "tradable_date": "2026-01-05", "entry_open": "10"},
            {"ticker": "OK", "quarter": "2025Q4", "tradable_date": "2026-01-05", "entry_open": "10", "return_90d_pct": "40"},
        ],
    )

    out = tmp_path / "out"
    build_pit_panel([input_csv], out, as_of_date="2026-01-06")

    by_ticker = {r["ticker"]: r for r in _read_panel(out / "pit_fundamental_panel.csv")}
    assert by_ticker["FUT"]["is_future_date_anomaly"] == "True"
    assert by_ticker["FUT"]["eligible_for_backtest"] == "False"
    assert by_ticker["MISS"]["eligible_for_backtest"] == "False"
    assert by_ticker["NOLABEL"]["eligible_for_backtest"] == "False"
    assert by_ticker["OK"]["eligible_for_backtest"] == "True"


def test_manifest_includes_input_hashes_and_missing_fields(tmp_path):
    input_csv = tmp_path / "scores.csv"
    _write_csv(input_csv, [{"ticker": "A", "quarter": "2025Q4", "tradable_date": "2026-01-05", "entry_open": "10", "return_90d_pct": "10"}])

    out = tmp_path / "out"
    build_pit_panel([input_csv], out, as_of_date="2026-01-06")

    manifest = json.loads((out / "run_manifest.json").read_text())
    assert manifest["input_files"][0]["path"] == str(input_csv)
    assert len(manifest["input_files"][0]["sha256"]) == 64
    assert "entry_qoq_pct" in manifest["missing_selection_fields_by_source"][str(input_csv)]
    assert "return_10d_pct" in manifest["missing_label_fields_by_source"][str(input_csv)]
