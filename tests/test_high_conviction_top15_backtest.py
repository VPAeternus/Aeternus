import csv
import json
from pathlib import Path

from tradingagents.research.fundamental.backtests.high_conviction_top15_exception_sleeve import (
    TARGET_RIGHT_TAIL_NAMES,
    run_high_conviction_top15_exception_sleeve_backtest,
)


def _row(ticker, quarter="2025Q1", score=80, ret90=10, **extra):
    row = {
        "ticker": ticker,
        "quarter": quarter,
        "tradable_date": "2025-01-02",
        "entry_open": "10",
        "entry_score_0_100": str(score),
        "eligible_for_backtest": "True",
        "return_10d_pct": "1",
        "return_20d_pct": "2",
        "return_30d_pct": "3",
        "return_60d_pct": "4",
        "return_90d_pct": str(ret90),
        "winner_90d_30pct": str(ret90 >= 30),
        "loser_90d_minus30pct": str(ret90 <= -30),
        "confidence": "4",
        "cik": "123",
        "cik_status": "resolved",
        "document_status": "CACHED_READY",
    }
    row.update(extra)
    return row


def _write_csv(path: Path, rows):
    fieldnames = sorted({k for r in rows for k in r})
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _fixture(tmp_path):
    pit = tmp_path / "pit.csv"
    prior = tmp_path / "prior.csv"
    out = tmp_path / "out"
    rows = [_row(f"C{i}", score=100 - i, ret90=5 + i) for i in range(10)]
    rows += [_row("CRNC", score=30, ret90=120, rm1_low_price_dislocation_momentum="1", primary_theme="ai")]
    rows += [_row("MISS", score=10, ret90=150)]
    for ticker in TARGET_RIGHT_TAIL_NAMES[1:]:
        rows.append(_row(ticker, score=30, ret90=0, eligible_for_backtest="False"))
    _write_csv(pit, rows)
    baseline = [dict(r, variant="high_conviction_top10_v2_final", selection_rank=i + 1) for i, r in enumerate(rows[:10])]
    _write_csv(prior, baseline)
    manifest = run_high_conviction_top15_exception_sleeve_backtest(pit, prior, out)
    return out, manifest


def _read_rows(path: Path):
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def test_top15_backtest_outputs_exist(tmp_path):
    out, _ = _fixture(tmp_path)
    for name in [
        "selected_names_by_quarter_top15.csv",
        "strategy_summary_top15.csv",
        "strategy_by_quarter_top15.csv",
        "core_vs_exception_contribution.csv",
        "exception_slot_diagnostics.csv",
        "right_tail_capture_comparison.csv",
        "left_tail_penalty_comparison.csv",
        "missed_right_tail_after_top15.csv",
        "run_manifest.json",
        "README_ANALYSIS.md",
    ]:
        assert (out / name).exists()


def test_core_vs_exception_contribution_present(tmp_path):
    out, _ = _fixture(tmp_path)
    rows = _read_rows(out / "core_vs_exception_contribution.csv")
    assert {r["sleeve"] for r in rows} >= {"core", "right_tail_exception"}


def test_right_tail_capture_comparison_includes_target_miss_names(tmp_path):
    out, _ = _fixture(tmp_path)
    rows = _read_rows(out / "right_tail_capture_comparison.csv")
    assert set(TARGET_RIGHT_TAIL_NAMES) <= {r["ticker"] for r in rows}
    assert any(r["ticker"] == "CRNC" and r["top15_status"] == "selected" for r in rows)


def test_left_tail_penalty_comparison_present(tmp_path):
    out, _ = _fixture(tmp_path)
    rows = _read_rows(out / "left_tail_penalty_comparison.csv")
    assert "delta_loser_rate_vs_top10" in rows[0]
    assert {r["variant"] for r in rows} >= {"high_conviction_top10_v2_final", "high_conviction_top15_v3_exception_sleeve"}


def test_selection_forbidden_columns_excluded(tmp_path):
    out, manifest = _fixture(tmp_path)
    data = json.loads((out / "run_manifest.json").read_text(encoding="utf-8"))
    forbidden = set(data["forbidden_selection_columns_removed_excluded"])
    assert "return_90d_pct" in forbidden
    assert "return_90d_pct" not in data["feature_columns_used_for_selection"]
    assert manifest["no_leakage_statement"]
