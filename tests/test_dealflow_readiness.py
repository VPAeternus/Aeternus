import json
from pathlib import Path

from tradingagents.dealflow.readiness import evaluate_step1_readiness


def _write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))


def test_step1_readiness_passes_with_stable_cycles_and_samples(tmp_path):
    base = tmp_path / "eval_results" / "deal_flow"
    evidence = tmp_path / "eval_results" / "evidence"
    run_date = "2026-01-06"

    _write_json(
        base / run_date / "shortlist_top20.json",
        {
            "connector_health_summary": {
                "status_totals": {
                    "OK": 6,
                    "NO_DATA": 0,
                    "ERROR": 0,
                    "NOT_CONFIGURED": 1,
                }
            }
        },
    )
    _write_json(
        base / run_date / "connector_health.json",
        [
            {"connector": "social_news", "status": "OK"},
            {"connector": "price_momentum", "status": "OK"},
            {"connector": "macro", "status": "OK"},
            {"connector": "smart_money", "status": "OK"},
        ],
    )

    horizons_ready = {
        "5d": {"status": "READY"},
        "20d": {"status": "READY"},
    }
    for suffix, symbol in [("100000", "AAPL"), ("100500", "GOOGL"), ("101000", "NVDA")]:
        _write_json(
            base / run_date / f"batch_analyze_summary_{suffix}.json",
            {
                "run_id": f"{run_date}-{suffix}",
                "date": run_date,
                "processed": 1,
                "success_count": 1,
                "failure_count": 0,
                "skipped_count": 0,
                "finished_at": f"2026-02-06T{suffix[:2]}:{suffix[2:4]}:{suffix[4:6]}+00:00",
                "items": [
                    {
                        "symbol": symbol,
                        "status": "SUCCESS",
                        "realized_horizons": horizons_ready,
                    }
                ],
            },
        )

    _write_json(
        evidence / run_date / "evidence_pack.json",
        {
            "status": "COMPLETE",
            "to_date": run_date,
            "readiness_summary": {
                "walkforward_windows": 4,
                "regime_slices": 5,
                "edge_decay_5d_pct": 1.2,
                "edge_decay_20d_pct": 1.6,
            },
        },
    )

    config = {
        "dealflow_step1_lookback_days": 90,
        "dealflow_step1_required_stable_cycles": 3,
        "dealflow_step1_min_batch_executed_per_cycle": 1,
        "dealflow_step1_max_batch_failure_ratio": 0.20,
        "dealflow_step1_max_connector_errors_per_cycle": 0,
        "dealflow_step1_min_evaluated_5d": 2,
        "dealflow_step1_min_evaluated_20d": 2,
        "dealflow_step1_required_connectors": "social_news,price_momentum,macro,smart_money",
        "dealflow_step1_required_connector_statuses": "OK,NO_DATA",
        "dealflow_step1_optional_connectors": "",
    }

    snapshot = evaluate_step1_readiness(
        config=config,
        as_of_date="2026-02-06",
        base_dir=base,
    )

    assert snapshot["overall_ready"] is True
    assert snapshot["gates"]["stability"]["pass"] is True
    assert snapshot["gates"]["attribution_sample"]["pass"] is True
    assert snapshot["gates"]["connector_policy"]["pass"] is True
    assert snapshot["gates"]["evidence_quality"]["pass"] is True
    assert snapshot["gates"]["stability"]["consecutive_stable_cycles"] >= 3


def test_step1_readiness_returns_blockers_when_gates_fail(tmp_path):
    base = tmp_path / "eval_results" / "deal_flow"
    run_date = "2026-02-06"

    _write_json(
        base / run_date / "shortlist_top20.json",
        {
            "connector_health_summary": {
                "status_totals": {
                    "OK": 4,
                    "NO_DATA": 0,
                    "ERROR": 2,
                    "NOT_CONFIGURED": 0,
                }
            }
        },
    )
    _write_json(
        base / run_date / "connector_health.json",
        [
            {"connector": "social_news", "status": "ERROR"},
            {"connector": "price_momentum", "status": "OK"},
        ],
    )
    _write_json(
        base / run_date / "batch_analyze_summary_090000.json",
        {
            "run_id": "2026-02-06-090000",
            "date": run_date,
            "processed": 3,
            "success_count": 0,
            "failure_count": 3,
            "skipped_count": 0,
            "finished_at": "2026-02-06T09:00:00+00:00",
            "items": [],
        },
    )

    config = {
        "dealflow_step1_required_stable_cycles": 3,
        "dealflow_step1_min_batch_executed_per_cycle": 1,
        "dealflow_step1_max_batch_failure_ratio": 0.25,
        "dealflow_step1_max_connector_errors_per_cycle": 0,
        "dealflow_step1_min_evaluated_5d": 2,
        "dealflow_step1_min_evaluated_20d": 2,
        "dealflow_step1_required_connectors": "social_news,price_momentum",
        "dealflow_step1_required_connector_statuses": "OK,NO_DATA",
    }

    snapshot = evaluate_step1_readiness(
        config=config,
        as_of_date="2026-02-06",
        base_dir=base,
    )

    assert snapshot["overall_ready"] is False
    assert snapshot["gates"]["stability"]["pass"] is False
    assert snapshot["gates"]["connector_policy"]["pass"] is False
    assert snapshot["blockers"]


def test_step1_readiness_blocks_partial_data_evidence_by_default(tmp_path):
    base = tmp_path / "eval_results" / "deal_flow"
    evidence = tmp_path / "eval_results" / "evidence"
    run_date = "2026-01-06"

    _write_json(
        base / run_date / "shortlist_top20.json",
        {
            "connector_health_summary": {
                "status_totals": {
                    "OK": 6,
                    "NO_DATA": 0,
                    "ERROR": 0,
                    "NOT_CONFIGURED": 0,
                }
            }
        },
    )
    _write_json(
        base / run_date / "connector_health.json",
        [
            {"connector": "social_news", "status": "OK"},
            {"connector": "price_momentum", "status": "OK"},
            {"connector": "macro", "status": "OK"},
            {"connector": "smart_money", "status": "OK"},
        ],
    )
    horizons_ready = {"5d": {"status": "READY"}, "20d": {"status": "READY"}}
    for suffix, symbol in [("100000", "AAPL"), ("100500", "GOOGL"), ("101000", "NVDA")]:
        _write_json(
            base / run_date / f"batch_analyze_summary_{suffix}.json",
            {
                "run_id": f"{run_date}-{suffix}",
                "date": run_date,
                "processed": 1,
                "success_count": 1,
                "failure_count": 0,
                "skipped_count": 0,
                "finished_at": f"2026-02-06T{suffix[:2]}:{suffix[2:4]}:{suffix[4:6]}+00:00",
                "items": [
                    {
                        "symbol": symbol,
                        "status": "SUCCESS",
                        "realized_horizons": horizons_ready,
                    }
                ],
            },
        )

    _write_json(
        evidence / run_date / "evidence_pack.json",
        {
            "status": "PARTIAL_DATA",
            "to_date": run_date,
            "readiness_summary": {
                "walkforward_windows": 4,
                "regime_slices": 5,
                "edge_decay_5d_pct": 1.2,
                "edge_decay_20d_pct": 1.6,
            },
        },
    )

    config = {
        "dealflow_step1_lookback_days": 90,
        "dealflow_step1_required_stable_cycles": 3,
        "dealflow_step1_min_batch_executed_per_cycle": 1,
        "dealflow_step1_max_batch_failure_ratio": 0.20,
        "dealflow_step1_max_connector_errors_per_cycle": 0,
        "dealflow_step1_min_evaluated_5d": 2,
        "dealflow_step1_min_evaluated_20d": 2,
        "dealflow_step1_required_connectors": "social_news,price_momentum,macro,smart_money",
        "dealflow_step1_required_connector_statuses": "OK,NO_DATA",
        "evidence_readiness_allow_partial_data": False,
    }

    blocked = evaluate_step1_readiness(
        config=config,
        as_of_date="2026-02-06",
        base_dir=base,
    )
    assert blocked["overall_ready"] is False
    assert blocked["gates"]["evidence_quality"]["pass"] is False

    config["evidence_readiness_allow_partial_data"] = True
    allowed = evaluate_step1_readiness(
        config=config,
        as_of_date="2026-02-06",
        base_dir=base,
    )
    assert allowed["gates"]["evidence_quality"]["pass"] is True
