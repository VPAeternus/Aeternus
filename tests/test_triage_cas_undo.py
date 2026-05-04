import datetime as dt
from pathlib import Path

import pytest

from tradingagents.dealflow.triage_control import (
    TriageConflictError,
    create_intent,
    load_receipts,
    undo_intent,
)


def _config(tmp_path: Path) -> dict:
    return {
        "operator_gateway_triage_intents_path": str(tmp_path / "deal_flow" / "ui" / "triage_intents.json"),
        "operator_gateway_triage_receipts_path": str(tmp_path / "deal_flow" / "ui" / "triage_receipts.json"),
        "operator_gateway_negative_constraints_path": str(tmp_path / "deal_flow" / "ui" / "negative_constraints.json"),
        "operator_gateway_system_halt_path": str(tmp_path / "control" / "system_halt.json"),
        "operator_gateway_negative_constraint_ttl_days": 14,
    }


def test_triage_undo_requires_matching_record_hash(tmp_path: Path):
    config = _config(tmp_path)
    now = dt.datetime(2026, 2, 8, 15, 0, tzinfo=dt.timezone.utc)
    intent = create_intent(
        action="APPROVE",
        symbol="TSLA",
        queue_id="queue-1",
        target_queue_run_id="run-1",
        snapshot_id="snap-1",
        snapshot_hash_canonical="abc",
        snapshot_hash_raw="def",
        snapshot_validity="VALID",
        snapshot_price=100.0,
        thesis_tags=["momentum"],
        config=config,
        now=now,
    )

    canceled = undo_intent(
        intent_id=intent["intent_id"],
        last_known_record_hash=intent["record_hash"],
        actor="operator",
        config=config,
        now=now + dt.timedelta(seconds=1),
    )
    assert canceled["status"] == "CANCELED_BY_UNDO"

    with pytest.raises(TriageConflictError):
        undo_intent(
            intent_id=intent["intent_id"],
            last_known_record_hash=intent["record_hash"],
            actor="operator",
            config=config,
            now=now + dt.timedelta(seconds=2),
        )


def test_undo_writes_terminal_receipt(tmp_path: Path):
    config = _config(tmp_path)
    now = dt.datetime(2026, 2, 8, 15, 0, tzinfo=dt.timezone.utc)
    intent = create_intent(
        action="DEFER",
        symbol="AAPL",
        queue_id="queue-2",
        target_queue_run_id="run-2",
        snapshot_id="snap-2",
        snapshot_hash_canonical="abc2",
        snapshot_hash_raw="def2",
        snapshot_validity="VALID",
        snapshot_price=220.0,
        thesis_tags=["balanced"],
        config=config,
        now=now,
    )
    undo_intent(
        intent_id=intent["intent_id"],
        last_known_record_hash=intent["record_hash"],
        config=config,
        now=now + dt.timedelta(seconds=3),
    )
    receipts = load_receipts(config)
    rows = [row for row in receipts["items"] if row["intent_id"] == intent["intent_id"]]
    assert rows
    assert rows[-1]["decision_status"] == "CANCELED_BY_UNDO"
