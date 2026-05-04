import json
from pathlib import Path

from tradingagents.dealflow.learning_loop import run_learning_cycle


def test_run_learning_cycle_writes_ok_status(tmp_path, monkeypatch):
    monkeypatch.setattr("tradingagents.dealflow.learning_loop._DEAL_FLOW_DIR", tmp_path / "eval_results" / "deal_flow")
    monkeypatch.setattr(
        "tradingagents.dealflow.learning_loop.compute_hindsight",
        lambda source_date, benchmark="QQQ": {"source_date": source_date, "eval_date": "2026-02-12"},
    )
    monkeypatch.setattr(
        "tradingagents.dealflow.learning_loop.compute_performance_review",
        lambda source_date, benchmark="QQQ": {"source_date": source_date, "signal_family_ic": []},
    )
    monkeypatch.setattr(
        "tradingagents.dealflow.learning_loop.write_signal_weight_adjustments",
        lambda **kwargs: {"status": "UPDATED", "output_path": "weights.json"},
    )
    monkeypatch.setattr(
        "tradingagents.dealflow.learning_loop.update_observed_edges_for_cycle",
        lambda *args, **kwargs: {"status": "OK", "edges_added": 2},
    )
    monkeypatch.setattr(
        "tradingagents.dealflow.learning_loop.build_source_attribution",
        lambda *args, **kwargs: {"output_path": "source_attribution.json", "ticker_count": 3},
    )

    result = run_learning_cycle("2026-02-07")

    assert result["learning_status"] == "OK"
    assert result["weight_update_status"] == "UPDATED"
    assert result["observed_edges_added"] == 2
    assert Path(result["output_path"]).exists()


def test_run_learning_cycle_degrades_on_hindsight_error(tmp_path, monkeypatch):
    monkeypatch.setattr("tradingagents.dealflow.learning_loop._DEAL_FLOW_DIR", tmp_path / "eval_results" / "deal_flow")

    def _boom(*args, **kwargs):
        raise RuntimeError("hindsight failed")

    monkeypatch.setattr("tradingagents.dealflow.learning_loop.compute_hindsight", _boom)
    monkeypatch.setattr(
        "tradingagents.dealflow.learning_loop.compute_performance_review",
        lambda source_date, benchmark="QQQ": {"source_date": source_date},
    )
    monkeypatch.setattr(
        "tradingagents.dealflow.learning_loop.write_signal_weight_adjustments",
        lambda **kwargs: {"status": "SKIPPED", "reason": "no_ic"},
    )
    monkeypatch.setattr(
        "tradingagents.dealflow.learning_loop.update_observed_edges_for_cycle",
        lambda *args, **kwargs: {"status": "OK", "edges_added": 0},
    )
    monkeypatch.setattr(
        "tradingagents.dealflow.learning_loop.build_source_attribution",
        lambda *args, **kwargs: {"output_path": "source_attribution.json", "ticker_count": 0},
    )

    result = run_learning_cycle("2026-02-07")

    assert result["learning_status"] == "DEGRADED"
    assert result["hindsight_status"] == "ERROR"
    assert "hindsight failed" in " ".join(result["warnings"])


def test_run_learning_cycle_blocks_on_invalid_weight_payload(tmp_path, monkeypatch):
    monkeypatch.setattr("tradingagents.dealflow.learning_loop._DEAL_FLOW_DIR", tmp_path / "eval_results" / "deal_flow")
    monkeypatch.setattr(
        "tradingagents.dealflow.learning_loop.compute_hindsight",
        lambda source_date, benchmark="QQQ": {"source_date": source_date, "eval_date": "2026-02-12"},
    )
    monkeypatch.setattr(
        "tradingagents.dealflow.learning_loop.compute_performance_review",
        lambda source_date, benchmark="QQQ": {"source_date": source_date, "signal_family_ic": []},
    )
    monkeypatch.setattr(
        "tradingagents.dealflow.learning_loop.write_signal_weight_adjustments",
        lambda **kwargs: {"status": "UPDATED"},
    )
    monkeypatch.setattr(
        "tradingagents.dealflow.learning_loop.update_observed_edges_for_cycle",
        lambda *args, **kwargs: {"status": "OK", "edges_added": 0},
    )
    monkeypatch.setattr(
        "tradingagents.dealflow.learning_loop.build_source_attribution",
        lambda *args, **kwargs: {"output_path": "source_attribution.json", "ticker_count": 0},
    )

    result = run_learning_cycle("2026-02-07")

    assert result["learning_status"] == "BLOCKED"
    assert result["weight_update_status"] == "BLOCKED_INVALID_OUTPUT"

