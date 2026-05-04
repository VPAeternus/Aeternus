import json
from pathlib import Path

from tradingagents.dealflow.hypothesis_ledger import (
    append_ledger_row,
    compute_stage_metrics,
    enrich_ledger_rows,
    make_ledger_row,
)


def test_compute_stage_metrics_returns_kept_vs_dropped_edge():
    metrics = compute_stage_metrics(
        kept_symbols=["AAPL", "NVDA"],
        dropped_symbols=["MU", "TSLA"],
        forward_returns_by_symbol={
            "AAPL": 0.10,
            "NVDA": 0.06,
            "MU": 0.02,
            "TSLA": 0.04,
        },
        winner_threshold=0.05,
    )

    assert metrics["kept_mean_return"] == 0.08
    assert metrics["dropped_mean_return"] == 0.03
    assert metrics["edge"] == 0.05
    assert metrics["future_winner_recall"] == 1.0
    assert metrics["false_negative_cost"] == 0.0
    assert metrics["sample_size"] == 4


def test_compute_stage_metrics_captures_false_negative_cost():
    metrics = compute_stage_metrics(
        kept_symbols=["AAPL"],
        dropped_symbols=["NVDA", "MU", "TSLA"],
        forward_returns_by_symbol={
            "AAPL": 0.08,
            "NVDA": 0.25,
            "MU": 0.30,
            "TSLA": -0.10,
        },
        winner_threshold=0.20,
    )

    assert metrics["kept_mean_return"] == 0.08
    assert metrics["dropped_mean_return"] == 0.15
    assert metrics["edge"] == -0.07
    assert metrics["future_winner_recall"] == 0.0
    assert metrics["false_negative_cost"] == 0.55
    assert metrics["sample_size"] == 4


def test_enrich_ledger_rows_populates_horizon_fields(tmp_path: Path):
    row = make_ledger_row(
        run_id="2026-03-06-123000-manual",
        source_date="2026-03-06",
        lane="shared",
        stage_id="shortlist_cut",
        rule_snapshot={"top_k": 2},
        kept_symbols=["AAPL", "NVDA"],
        dropped_symbols=["MU", "TSLA"],
        base_dir=tmp_path,
    )
    append_ledger_row(base_dir=tmp_path, lane="shared", row=row)

    rows = enrich_ledger_rows(
        base_dir=tmp_path,
        lane="shared",
        forward_returns_by_horizon={
            "5d": {"AAPL": 0.10, "NVDA": 0.06, "MU": 0.02, "TSLA": 0.04},
            "20d": {"AAPL": 0.14, "NVDA": 0.08, "MU": 0.03, "TSLA": 0.10},
        },
        winner_horizon="20d",
        winner_threshold=0.10,
    )

    updated = rows[0]
    assert updated["kept_mean_return_5d"] == 0.08
    assert updated["dropped_mean_return_5d"] == 0.03
    assert updated["edge_5d"] == 0.05
    assert updated["edge_20d"] == 0.045
    assert updated["edge_3m"] is None
    assert updated["future_winner_recall"] == 0.5
    assert updated["false_negative_cost"] == 0.1
    assert updated["sample_size"] == 4

    rows_on_disk = json.loads((tmp_path / "hypothesis_ledger" / "shared" / "rows.json").read_text())
    assert rows_on_disk[0]["edge_20d"] == 0.045
