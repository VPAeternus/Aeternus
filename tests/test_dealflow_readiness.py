import json
from pathlib import Path

from tradingagents.dealflow.readiness import evaluate_step1_readiness


def _write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))


def _write_handoff(base: Path, run_date: str, tickers: list[str], *, connector_error: bool = False):
    _write_json(
        base / run_date / "final_dealflow_tickers.json",
        {
            "date": run_date,
            "source_stage": "scout_ticker_summary",
            "tickers": [
                {"ticker": ticker, "mention_count": idx + 1}
                for idx, ticker in enumerate(tickers)
            ],
        },
    )
    _write_json(
        base / run_date / "connector_health.json",
        [
            {"connector": "social_news", "status": "ERROR" if connector_error else "OK"},
            {"connector": "price_momentum", "status": "OK"},
            {"connector": "macro", "status": "OK"},
            {"connector": "smart_money", "status": "OK"},
        ],
    )


def _write_evidence(evidence: Path, run_date: str, status: str = "COMPLETE"):
    _write_json(
        evidence / run_date / "evidence_pack.json",
        {
            "status": status,
            "to_date": run_date,
            "readiness_summary": {
                "walkforward_windows": 4,
                "regime_slices": 5,
                "edge_decay_5d_pct": 1.2,
                "edge_decay_20d_pct": 1.6,
            },
        },
    )


def test_step1_readiness_passes_with_stable_scout_handoffs(tmp_path):
    base = tmp_path / "eval_results" / "deal_flow"
    evidence = tmp_path / "eval_results" / "evidence"

    for run_date in ["2026-02-04", "2026-02-05", "2026-02-06"]:
        _write_handoff(base, run_date, ["AAPL", "GOOGL", "NVDA"])
    _write_evidence(evidence, "2026-02-06")

    snapshot = evaluate_step1_readiness(
        config={
            "dealflow_step1_lookback_days": 90,
            "dealflow_step1_required_stable_cycles": 3,
            "dealflow_step1_min_handoff_tickers_per_cycle": 1,
            "dealflow_step1_min_unique_handoff_tickers": 2,
            "dealflow_step1_max_connector_errors_per_cycle": 0,
            "dealflow_step1_required_connectors": "social_news,price_momentum,macro,smart_money",
            "dealflow_step1_required_connector_statuses": "OK,NO_DATA",
        },
        as_of_date="2026-02-06",
        base_dir=base,
    )

    assert snapshot["overall_ready"] is True
    assert snapshot["gates"]["stability"]["pass"] is True
    assert snapshot["gates"]["handoff_sample"]["pass"] is True
    assert snapshot["gates"]["connector_policy"]["pass"] is True
    assert snapshot["gates"]["evidence_quality"]["pass"] is True


def test_step1_readiness_returns_blockers_when_handoff_gates_fail(tmp_path):
    base = tmp_path / "eval_results" / "deal_flow"
    _write_handoff(base, "2026-02-06", [], connector_error=True)

    snapshot = evaluate_step1_readiness(
        config={
            "dealflow_step1_required_stable_cycles": 3,
            "dealflow_step1_min_handoff_tickers_per_cycle": 1,
            "dealflow_step1_min_unique_handoff_tickers": 2,
            "dealflow_step1_max_connector_errors_per_cycle": 0,
            "dealflow_step1_required_connectors": "social_news,price_momentum",
            "dealflow_step1_required_connector_statuses": "OK,NO_DATA",
        },
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
    _write_handoff(base, "2026-02-06", ["AAPL", "MSFT"])
    _write_evidence(evidence, "2026-02-06", status="PARTIAL_DATA")

    config = {
        "dealflow_step1_required_stable_cycles": 1,
        "dealflow_step1_min_handoff_tickers_per_cycle": 1,
        "dealflow_step1_min_unique_handoff_tickers": 1,
        "dealflow_step1_max_connector_errors_per_cycle": 0,
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
