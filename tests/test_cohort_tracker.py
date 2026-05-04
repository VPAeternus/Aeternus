import json
from pathlib import Path

import pandas as pd


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))


def test_compute_cohort_returns_adds_v3_rejected_and_benchmark_decision_alpha(
    tmp_path, monkeypatch
):
    from tradingagents.dealflow import cohort_tracker

    dealflow_dir = tmp_path / "eval_results" / "deal_flow"
    results_dir = tmp_path / "results"

    _write_json(
        dealflow_dir / "2026-03-10" / "research_queue.json",
        {
            "date": "2026-03-10",
            "items": [
                {"symbol": "AAPL", "selected_for_deep": True, "deal_flow_score": 90.0},
                {"symbol": "MSFT", "selected_for_deep": True, "deal_flow_score": 85.0},
                {"symbol": "TSLA", "selected_for_deep": False, "deal_flow_score": 70.0},
            ],
        },
    )
    _write_json(
        results_dir / "AAPL" / "2026-03-10" / "analysis_report.json",
        {"aeternus_score": {"aeternus_score": 58.0}},
    )
    _write_json(
        results_dir / "MSFT" / "2026-03-10" / "analysis_report.json",
        {"aeternus_score": {"aeternus_score": 65.0}},
    )

    prices = pd.DataFrame(
        {
            "AAPL": [100.0, 120.0],
            "MSFT": [100.0, 105.0],
            "TSLA": [100.0, 102.0],
            "QQQ": [100.0, 110.0],
        },
        index=pd.to_datetime(["2026-03-10", "2026-03-17"]),
    )

    monkeypatch.setattr(cohort_tracker, "_DEAL_FLOW_DIR", dealflow_dir)
    monkeypatch.setattr(cohort_tracker, "_RESULTS_DIR", results_dir)
    monkeypatch.setattr(cohort_tracker, "_COHORT_DB", dealflow_dir / "cohort_tracker.db")
    monkeypatch.setattr(cohort_tracker.yf, "download", lambda *args, **kwargs: prices)

    result = cohort_tracker.compute_cohort_returns(
        "2026-03-10",
        eval_date="2026-03-17",
    )

    rejected = result["cohorts"]["V3_REJECTED"]
    cleared = result["cohorts"]["V3_CLEARED"]

    assert rejected["ticker_count"] == 1
    assert rejected["tickers"] == ["AAPL"]
    assert rejected["eq_weight_return"] == 0.2
    assert cleared["ticker_count"] == 1
    assert cleared["tickers"] == ["MSFT"]
    assert cleared["eq_weight_return"] == 0.05
    assert result["inter_stage_alpha"]["benchmark_to_v3_rejected"] == -0.1

