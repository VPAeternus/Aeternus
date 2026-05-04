import json
from pathlib import Path


def test_compute_needle_retro_uses_last_five_completed_cycles_and_excludes_pipeline_gaps(tmp_path, monkeypatch):
    from tradingagents.dealflow.needle_retro import compute_needle_retro

    dealflow_root = tmp_path / "eval_results" / "deal_flow"
    plans_root = tmp_path / "eval_results" / "paper_execution" / "plans"
    x_feed_root = tmp_path / "eval_results" / "x_feed"

    dates = [
        "2026-03-10",
        "2026-03-09",
        "2026-03-08",
        "2026-03-07",
        "2026-03-06",
        "2026-03-05",
        "2026-03-04",
    ]
    for date_str in dates:
        (dealflow_root / date_str).mkdir(parents=True, exist_ok=True)

    def _fake_hindsight(source_date: str, benchmark: str = "QQQ", db_path=None):
        if source_date in {"2026-03-10", "2026-03-09"}:
            return {"source_date": source_date, "error": "Insufficient T+5"}
        payloads = {
            "2026-03-08": {
                "source_date": source_date,
                "benchmark": benchmark,
                "benchmark_return_5d": 0.01,
                "ticker_returns": [
                    {"ticker": "MU", "cohort": "FILTERED", "return_5d": 0.23},
                    {"ticker": "AAPL", "cohort": "DEPLOYED", "return_5d": 0.05},
                ],
            },
            "2026-03-07": {
                "source_date": source_date,
                "benchmark": benchmark,
                "benchmark_return_5d": 0.02,
                "ticker_returns": [
                    {"ticker": "BE", "cohort": "FILTERED", "return_5d": 0.10},
                ],
            },
            "2026-03-06": {
                "source_date": source_date,
                "benchmark": benchmark,
                "benchmark_return_5d": 0.01,
                "ticker_returns": [
                    {"ticker": "TSM", "cohort": "QUEUED", "return_5d": 0.09},
                ],
            },
            "2026-03-05": {
                "source_date": source_date,
                "benchmark": benchmark,
                "benchmark_return_5d": 0.00,
                "ticker_returns": [
                    {"ticker": "OXY", "cohort": "ANALYZED", "return_5d": 0.08},
                ],
            },
            "2026-03-04": {
                "source_date": source_date,
                "benchmark": benchmark,
                "benchmark_return_5d": -0.01,
                "ticker_returns": [
                    {"ticker": "NVDA", "cohort": "FILTERED", "return_5d": 0.04},
                ],
            },
        }
        return payloads[source_date]

    def _fake_audit(ticker: str, source_date: str, **kwargs):
        mapping = {
            ("MU", "2026-03-08"): {
                "highest_stage": "SCORED",
                "root_cause": "SHORTLIST_CUT",
                "improvement_target": "shortlist_cut",
                "primary_stage_drop": "shortlist_cut",
                "stage_drops": [{"stage_id": "shortlist_cut"}],
            },
            ("BE", "2026-03-07"): {
                "highest_stage": "X_FEED",
                "root_cause": "PIPELINE_NOT_RUN",
                "improvement_target": "daily_run_completeness",
                "primary_stage_drop": None,
                "stage_drops": [],
            },
            ("TSM", "2026-03-06"): {
                "highest_stage": "QUEUED",
                "root_cause": "DEEP_SELECTION_CUT",
                "improvement_target": "deep_selection_cut",
                "primary_stage_drop": "deep_selection_cut",
                "stage_drops": [{"stage_id": "deep_selection_cut"}],
            },
            ("OXY", "2026-03-05"): {
                "highest_stage": "ANALYZED",
                "root_cause": "V3_HURDLE_REJECTED",
                "improvement_target": "portfolio_inclusion_cut",
                "primary_stage_drop": "portfolio_inclusion_cut",
                "stage_drops": [{"stage_id": "portfolio_inclusion_cut"}],
            },
            ("NVDA", "2026-03-04"): {
                "highest_stage": "SCORED",
                "root_cause": "SHORTLIST_CUT",
                "improvement_target": "shortlist_cut",
                "primary_stage_drop": "shortlist_cut",
                "stage_drops": [{"stage_id": "shortlist_cut"}],
            },
        }
        row = mapping[(ticker, source_date)].copy()
        row["source_date"] = source_date
        return row

    monkeypatch.setattr("tradingagents.dealflow.needle_retro.compute_hindsight", _fake_hindsight)
    monkeypatch.setattr("tradingagents.dealflow.needle_retro.audit_ticker_run", _fake_audit)

    report = compute_needle_retro(
        last=5,
        base_dir=dealflow_root,
        plans_base_dir=plans_root,
        x_feed_base_dir=x_feed_root,
        benchmark="QQQ",
        min_edge=0.03,
    )

    assert report["cycles_requested"] == 5
    assert report["cycles_completed"] == 5
    assert [row["source_date"] for row in report["cycles"]] == [
        "2026-03-08",
        "2026-03-07",
        "2026-03-06",
        "2026-03-05",
        "2026-03-04",
    ]
    assert [row["source_date"] for row in report["opportunities"]] == [
        "2026-03-08",
        "2026-03-06",
        "2026-03-05",
        "2026-03-04",
    ]
    assert [row["ticker"] for row in report["opportunities"]] == ["MU", "TSM", "OXY", "NVDA"]
    assert "BE" not in {row["ticker"] for row in report["opportunities"]}
    assert report["opportunities"][0]["edge_vs_benchmark_5d"] == 0.22

    summary = {row["improvement_target"]: row for row in report["stage_summary"]}
    assert summary["shortlist_cut"]["count"] == 2
    assert summary["deep_selection_cut"]["count"] == 1
    assert summary["portfolio_inclusion_cut"]["count"] == 1

