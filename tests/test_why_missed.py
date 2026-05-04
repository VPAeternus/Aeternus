import json
from pathlib import Path

from tradingagents.dealflow.hypothesis_ledger import append_ledger_row, make_ledger_row


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))


def test_compute_why_missed_caps_lookback_and_classifies_root_causes(tmp_path):
    from tradingagents.dealflow.why_missed import compute_why_missed

    dealflow_root = tmp_path / "eval_results" / "deal_flow"
    x_feed_root = tmp_path / "eval_results" / "x_feed"
    plans_root = tmp_path / "eval_results" / "paper_execution" / "plans"

    # older than capped lookback; should not appear
    _write_json(
        x_feed_root / "2026-03-01" / "merged.json",
        {"MU": {"ticker": "MU"}},
    )

    # newest 5 runs
    _write_json(
        x_feed_root / "2026-03-06" / "merged.json",
        {"MU": {"ticker": "MU"}},
    )
    _write_json(
        dealflow_root / "2026-03-06" / "signals_raw.json",
        [{"symbol": "MU", "signal_family": "social_momentum", "raw_score": 88.0}],
    )
    _write_json(
        dealflow_root / "2026-03-06" / "all_scored_candidates.json",
        [{"symbol": "MU", "core_score": 72.0, "momentum_score": 81.0, "status": "ACTIVE"}],
    )

    _write_json(
        dealflow_root / "2026-03-05" / "research_queue.json",
        {
            "items": [
                {"symbol": "MU", "selected_for_deep": False, "deal_flow_score": 70.0, "lane": "CORE"}
            ]
        },
    )

    _write_json(
        dealflow_root / "2026-03-04" / "research_queue.json",
        {
            "items": [
                {"symbol": "MU", "selected_for_deep": True, "deal_flow_score": 74.0, "lane": "CORE"}
            ]
        },
    )
    _write_json(
        dealflow_root / "2026-03-04" / "batch_analyze_latest.json",
        {
            "items": [
                {
                    "symbol": "MU",
                    "status": "SUCCESS",
                    "aeternus_score": 58.0,
                    "recommendation": "BUY",
                    "rating": "Hold",
                    "confidence": 5,
                }
            ]
        },
    )

    _write_json(
        dealflow_root / "2026-03-03" / "signals_raw.json",
        [{"symbol": "NVDA", "signal_family": "social_momentum", "raw_score": 90.0}],
    )

    _write_json(
        dealflow_root / "2026-03-02" / "research_queue.json",
        {
            "items": [
                {"symbol": "MU", "selected_for_deep": True, "deal_flow_score": 80.0, "lane": "CORE"}
            ]
        },
    )
    _write_json(
        dealflow_root / "2026-03-02" / "batch_analyze_latest.json",
        {
            "items": [
                {
                    "symbol": "MU",
                    "status": "SUCCESS",
                    "aeternus_score": 67.0,
                    "recommendation": "BUY",
                    "rating": "Buy",
                    "confidence": 5,
                }
            ]
        },
    )
    _write_json(
        plans_root / "2026-03-02" / "portfolio_plan_120000.json",
        {"orders": [{"symbol": "MU"}]},
    )

    report = compute_why_missed(
        "MU",
        last=20,
        base_dir=dealflow_root,
        x_feed_base_dir=x_feed_root,
        plans_base_dir=plans_root,
        hurdle=62.0,
    )

    assert report["ticker"] == "MU"
    assert report["lookback_runs_requested"] == 20
    assert report["lookback_runs_used"] == 5
    assert [row["source_date"] for row in report["runs"]] == [
        "2026-03-06",
        "2026-03-05",
        "2026-03-04",
        "2026-03-03",
        "2026-03-02",
    ]
    assert "2026-03-01" not in {row["source_date"] for row in report["runs"]}

    cause_map = {row["source_date"]: row["root_cause"] for row in report["runs"]}
    assert cause_map["2026-03-06"] == "SHORTLIST_CUT"
    assert cause_map["2026-03-05"] == "DEEP_SELECTION_CUT"
    assert cause_map["2026-03-04"] == "V3_HURDLE_REJECTED"
    assert cause_map["2026-03-03"] == "NOT_FLAGGED"
    assert cause_map["2026-03-02"] == "DEPLOYED"


def test_compute_why_missed_enriches_stage_drop_and_forward_edge(tmp_path, monkeypatch):
    from tradingagents.dealflow.why_missed import compute_why_missed

    dealflow_root = tmp_path / "eval_results" / "deal_flow"
    x_feed_root = tmp_path / "eval_results" / "x_feed"
    plans_root = tmp_path / "eval_results" / "paper_execution" / "plans"

    _write_json(
        x_feed_root / "2026-03-06" / "merged.json",
        {"MU": {"ticker": "MU"}},
    )
    _write_json(
        dealflow_root / "2026-03-06" / "signals_raw.json",
        [{"symbol": "MU", "signal_family": "social_momentum", "raw_score": 88.0}],
    )
    _write_json(
        dealflow_root / "2026-03-06" / "all_scored_candidates.json",
        [{"symbol": "MU", "core_score": 72.0, "momentum_score": 81.0, "status": "ACTIVE"}],
    )

    ledger_row = make_ledger_row(
        run_id="2026-03-06-120000-manual",
        source_date="2026-03-06",
        lane="shared",
        stage_id="shortlist_cut",
        rule_snapshot={"top_k": 30, "source": "unit-test"},
        kept_symbols=["NVDA", "TSM"],
        dropped_symbols=["MU"],
        base_dir=dealflow_root / "2026-03-06",
    )
    append_ledger_row(base_dir=dealflow_root / "2026-03-06", lane="shared", row=ledger_row)

    monkeypatch.setattr(
        "tradingagents.dealflow.why_missed._forward_return_summary",
        lambda symbol, source_date, benchmark="QQQ": {
            "eval_date": "2026-03-13",
            "return_5d": 0.23,
            "benchmark_return_5d": 0.01,
            "edge_vs_benchmark_5d": 0.22,
            "status": "READY",
        },
    )

    report = compute_why_missed(
        "MU",
        last=5,
        base_dir=dealflow_root,
        x_feed_base_dir=x_feed_root,
        plans_base_dir=plans_root,
        hurdle=62.0,
    )

    row = report["runs"][0]
    assert row["root_cause"] == "SHORTLIST_CUT"
    assert row["primary_stage_drop"] == "shortlist_cut"
    assert row["improvement_target"] == "shortlist_cut"
    assert row["stage_drops"][0]["stage_id"] == "shortlist_cut"
    assert row["stage_drops"][0]["rule_snapshot"]["top_k"] == 30
    assert row["return_5d"] == 0.23
    assert row["benchmark_return_5d"] == 0.01
    assert row["edge_vs_benchmark_5d"] == 0.22
    assert row["review_recommended"] is True
    assert "shortlist_cut" in row["review_reason"]


def test_compute_why_missed_marks_pipeline_not_run_when_only_x_feed_exists(tmp_path):
    from tradingagents.dealflow.why_missed import compute_why_missed

    dealflow_root = tmp_path / "eval_results" / "deal_flow"
    x_feed_root = tmp_path / "eval_results" / "x_feed"
    plans_root = tmp_path / "eval_results" / "paper_execution" / "plans"

    _write_json(
        x_feed_root / "2026-03-06" / "merged.json",
        {"BE": {"ticker": "BE"}},
    )

    report = compute_why_missed(
        "BE",
        last=5,
        base_dir=dealflow_root,
        x_feed_base_dir=x_feed_root,
        plans_base_dir=plans_root,
    )

    row = report["runs"][0]
    assert row["source_date"] == "2026-03-06"
    assert row["dealflow_cycle_found"] is False
    assert row["root_cause"] == "PIPELINE_NOT_RUN"
    assert row["improvement_target"] == "daily_run_completeness"
