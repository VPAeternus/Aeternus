import datetime as dt
from pathlib import Path

from tradingagents.dealflow.triage_control import create_intent, load_intents, resolve_intents_for_run


def _config(tmp_path: Path) -> dict:
    return {
        "operator_gateway_triage_intents_path": str(tmp_path / "deal_flow" / "ui" / "triage_intents.json"),
        "operator_gateway_triage_receipts_path": str(tmp_path / "deal_flow" / "ui" / "triage_receipts.json"),
        "operator_gateway_negative_constraints_path": str(tmp_path / "deal_flow" / "ui" / "negative_constraints.json"),
        "operator_gateway_system_halt_path": str(tmp_path / "control" / "system_halt.json"),
        "operator_gateway_intent_maturity_seconds": 5.0,
        "operator_gateway_price_slip_max_bps": 150.0,
        "operator_gateway_price_latency_max_ms": 2000.0,
    }


def test_resolve_intent_expires_when_price_slip_exceeds_threshold(tmp_path: Path):
    config = _config(tmp_path)
    run_started = dt.datetime(2026, 2, 8, 14, 0, tzinfo=dt.timezone.utc)
    create_intent(
        action="APPROVE",
        symbol="TSLA",
        queue_id="q1",
        target_queue_run_id="run-1",
        snapshot_id="snap",
        snapshot_hash_canonical="h1",
        snapshot_hash_raw="h2",
        snapshot_validity="VALID",
        snapshot_price=100.0,
        thesis_tags=["momentum"],
        config=config,
        now=run_started - dt.timedelta(seconds=10),
    )

    result = resolve_intents_for_run(
        active_run_id="run-1",
        run_started_at_utc=run_started.isoformat(),
        consumption_prices={"TSLA": 102.0},
        price_source_latency_ms={"TSLA": 1000},
        config=config,
        now=run_started,
    )
    assert result["expired_price_slip_count"] == 1
    intents = load_intents(config)["items"]
    assert intents[-1]["status"] == "EXPIRED_PRICE_SLIP"


def test_resolve_intent_expires_when_latency_too_high(tmp_path: Path):
    config = _config(tmp_path)
    run_started = dt.datetime(2026, 2, 8, 14, 0, tzinfo=dt.timezone.utc)
    create_intent(
        action="APPROVE",
        symbol="AAPL",
        queue_id="q2",
        target_queue_run_id="run-2",
        snapshot_id="snap2",
        snapshot_hash_canonical="h1",
        snapshot_hash_raw="h2",
        snapshot_validity="VALID",
        snapshot_price=200.0,
        thesis_tags=["momentum"],
        config=config,
        now=run_started - dt.timedelta(seconds=10),
    )

    result = resolve_intents_for_run(
        active_run_id="run-2",
        run_started_at_utc=run_started.isoformat(),
        consumption_prices={"AAPL": 200.5},
        price_source_latency_ms={"AAPL": 2501},
        config=config,
        now=run_started,
    )
    assert result["expired_price_slip_count"] == 1
    intents = load_intents(config)["items"]
    assert intents[-1]["status"] == "EXPIRED_PRICE_SLIP"
