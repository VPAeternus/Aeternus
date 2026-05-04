import datetime as dt
import sqlite3
import threading
import time

import pytest

from tradingagents.capital_allocator.contracts import (
    AllocationIntent,
    AssetClassId,
    ExecutionMode,
    FundingSourceStatus,
    IntentStatus,
    Lane,
    MarketSnapshot,
    ValuationMethodology,
)
from tradingagents.capital_allocator.repository import MirrorIntentError, SQLiteAllocatorRepository


def _intent(intent_id: str, *, idempotency_key: str, **overrides) -> AllocationIntent:
    base = AllocationIntent(
        intent_id=intent_id,
        run_id="run-1",
        lane=Lane.CORE,
        symbol="AAPL",
        asset_id="AAPL",
        asset_class_id=AssetClassId.LISTED_EQUITY,
        valuation_methodology=ValuationMethodology.MARK_TO_MARKET,
        execution_mode=ExecutionMode.LIVE,
        side="BUY",
        target_notional_usd=5000.0,
        correlation_group_tag="MEGA_CAP",
        funding_source_status=FundingSourceStatus.SETTLED_CASH,
        funding_available_at_utc=None,
        funding_reservation_id=None,
        snapshot_id="snap-1",
        snapshot_hash_canonical="hash",
        snapshot_hash_raw="raw-hash",
        max_slippage_bps=150.0,
        created_at_utc=dt.datetime(2026, 2, 8, 15, 0, tzinfo=dt.timezone.utc),
        expires_at_utc=dt.datetime(2026, 2, 8, 16, 0, tzinfo=dt.timezone.utc),
        status=IntentStatus.PROPOSED,
        idempotency_key=idempotency_key,
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


def test_repository_initializes_wal_and_tables(tmp_path):
    db_path = tmp_path / "allocator.db"
    repo = SQLiteAllocatorRepository(db_path)
    repo.initialize()

    with repo.connection() as conn:
        mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
        assert str(mode).lower() == "wal"
        table_count = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name LIKE 'allocator_%'"
        ).fetchone()[0]
        assert table_count >= 5


def test_insert_intent_and_idempotency_return_existing(tmp_path):
    repo = SQLiteAllocatorRepository(tmp_path / "allocator.db")
    repo.initialize()

    created = repo.insert_intent(_intent("intent-1", idempotency_key="idem-1"))
    duplicate = repo.insert_intent(_intent("intent-2", idempotency_key="idem-1"))

    assert created.intent_id == "intent-1"
    assert duplicate.intent_id == "intent-1"
    assert len(repo.list_intents()) == 1


def test_funding_reservation_unique_for_active_states(tmp_path):
    repo = SQLiteAllocatorRepository(tmp_path / "allocator.db")
    repo.initialize()
    repo.insert_intent(
        _intent(
            "intent-1",
            idempotency_key="idem-1",
            funding_reservation_id="reserve-1",
        )
    )

    with pytest.raises(RuntimeError):
        repo.insert_intent(
            _intent(
                "intent-2",
                idempotency_key="idem-2",
                funding_reservation_id="reserve-1",
            )
        )


def test_concurrent_inserts_with_same_funding_reservation_are_race_safe(tmp_path):
    repo = SQLiteAllocatorRepository(tmp_path / "allocator.db")
    repo.initialize()

    barrier = threading.Barrier(2)
    results: list[str] = []
    errors: list[str] = []
    lock = threading.Lock()

    def _worker(intent_id: str, idem: str):
        try:
            barrier.wait(timeout=2)
            repo.insert_intent(
                _intent(
                    intent_id,
                    idempotency_key=idem,
                    funding_reservation_id="reserve-race-1",
                )
            )
            with lock:
                results.append(intent_id)
        except Exception as exc:  # expected for one writer on uniqueness.
            with lock:
                errors.append(str(exc))

    t1 = threading.Thread(target=_worker, args=("intent-race-1", "idem-race-1"))
    t2 = threading.Thread(target=_worker, args=("intent-race-2", "idem-race-2"))
    t1.start()
    t2.start()
    t1.join(timeout=5)
    t2.join(timeout=5)

    assert len(results) == 1
    assert len(errors) == 1
    assert "Unable to insert intent" in errors[0]
    rows = repo.list_intents(limit=10)
    assert len(rows) == 1
    assert rows[0].funding_reservation_id == "reserve-race-1"


def test_write_waits_for_lock_and_recovers_without_hanging(tmp_path):
    repo = SQLiteAllocatorRepository(tmp_path / "allocator.db")
    repo.initialize()

    # Seed one row so the table path exists before lock contention begins.
    repo.insert_intent(_intent("seed-intent", idempotency_key="idem-seed"))

    db_path = tmp_path / "allocator.db"
    locker = sqlite3.connect(str(db_path), timeout=5, isolation_level=None)
    locker.execute("PRAGMA journal_mode=WAL;")
    locker.execute("BEGIN IMMEDIATE;")
    locker.execute("UPDATE allocator_intents SET reason = reason WHERE intent_id = ?", ("seed-intent",))

    result: dict[str, str] = {}

    def _insert_under_lock():
        try:
            repo.insert_intent(_intent("intent-after-lock", idempotency_key="idem-after-lock"))
            result["status"] = "ok"
        except Exception as exc:  # pragma: no cover - should not happen
            result["status"] = f"error:{exc}"

    worker = threading.Thread(target=_insert_under_lock)
    worker.start()
    time.sleep(0.2)
    locker.execute("COMMIT;")
    locker.close()
    worker.join(timeout=5)

    assert result.get("status") == "ok"
    assert repo.get_intent("intent-after-lock") is not None


def test_fetch_validated_ready_excludes_pending_funding(tmp_path):
    repo = SQLiteAllocatorRepository(tmp_path / "allocator.db")
    repo.initialize()
    now = dt.datetime(2026, 2, 8, 15, 0, tzinfo=dt.timezone.utc)
    repo.insert_intent(
        _intent(
            "ready",
            idempotency_key="idem-ready",
            status=IntentStatus.VALIDATED,
        )
    )
    repo.insert_intent(
        _intent(
            "wait",
            idempotency_key="idem-wait",
            status=IntentStatus.VALIDATED,
            funding_source_status=FundingSourceStatus.PENDING_SALE_PROCEEDS,
            funding_available_at_utc=now + dt.timedelta(hours=1),
        )
    )
    ready = repo.fetch_validated_ready(now_utc=now)
    ids = {row.intent_id for row in ready}
    assert "ready" in ids
    assert "wait" not in ids


def test_receipt_persistence(tmp_path):
    repo = SQLiteAllocatorRepository(tmp_path / "allocator.db")
    repo.initialize()
    now = dt.datetime(2026, 2, 8, 15, 0, tzinfo=dt.timezone.utc)
    repo.insert_intent(_intent("intent-1", idempotency_key="idem-1"))
    receipt_id = repo.save_terminal_receipt(
        intent_id="intent-1",
        terminal_status=IntentStatus.REJECTED_PRICE_SLIP,
        reason_code="REJECTED_PRICE_SLIP",
        reason="delta exceeded",
        decided_at_utc=now,
        price_at_validation=100.0,
        price_at_submit=102.0,
        price_delta_bps=200.0,
        price_source_latency_ms=20,
    )
    rows = repo.list_receipts(intent_id="intent-1")
    assert rows
    assert rows[-1]["receipt_id"] == receipt_id
    assert rows[-1]["terminal_status"] == IntentStatus.REJECTED_PRICE_SLIP.value


def test_market_snapshot_roundtrip(tmp_path):
    repo = SQLiteAllocatorRepository(tmp_path / "allocator.db")
    repo.initialize()
    now = dt.datetime(2026, 2, 8, 15, 0, tzinfo=dt.timezone.utc)
    repo.upsert_market_snapshot(
        MarketSnapshot(
            symbol="AAPL",
            snapshot_time_utc=now,
            price=199.2,
            adv30_notional_usd=5_000_000.0,
            vol20d_bps=140.0,
            spread_bps=2.0,
            source_latency_ms=120,
        )
    )
    loaded = repo.get_market_snapshot("AAPL")
    assert loaded is not None
    assert loaded.price == 199.2
    assert loaded.adv30_notional_usd == 5_000_000.0


def test_fill_records_tax_lot_and_broker_fill_id(tmp_path):
    repo = SQLiteAllocatorRepository(tmp_path / "allocator.db")
    repo.initialize()
    repo.insert_intent(_intent("intent-fill", idempotency_key="idem-fill"))
    with repo.connection() as conn:
        conn.execute(
            "INSERT INTO allocator_orders (order_id, intent_id, status) VALUES (?, ?, ?)",
            ("order-1", "intent-fill", "SUBMITTED"),
        )
    repo.insert_fill(
        fill_id="fill-1",
        order_id="order-1",
        broker_fill_id="broker-fill-1",
        tax_lot_id="lot-1",
        fill_time_utc=dt.datetime(2026, 2, 8, 15, 1, tzinfo=dt.timezone.utc),
        qty=10.0,
        price=200.0,
        fee_usd=1.0,
    )
    with repo.connection() as conn:
        row = conn.execute(
            "SELECT broker_fill_id, tax_lot_id FROM allocator_fills WHERE fill_id = ?",
            ("fill-1",),
        ).fetchone()
    assert row is not None
    assert row["broker_fill_id"] == "broker-fill-1"
    assert row["tax_lot_id"] == "lot-1"


def test_mirror_challenge_and_confirm_moves_validated_to_submitted(tmp_path):
    repo = SQLiteAllocatorRepository(tmp_path / "allocator.db")
    repo.initialize()
    now = dt.datetime(2026, 2, 8, 15, 0, tzinfo=dt.timezone.utc)
    repo.insert_intent(
        _intent(
            "intent-mirror-1",
            idempotency_key="idem-mirror-1",
            status=IntentStatus.VALIDATED,
            funding_source_status=FundingSourceStatus.SETTLED_CASH,
        )
    )

    challenge = repo.create_mirror_challenge(
        intent_id="intent-mirror-1",
        now_utc=now,
        ttl_seconds=300,
        created_by="test",
    )
    assert challenge["intent_id"] == "intent-mirror-1"
    assert challenge["challenge_id"]
    assert challenge["preview_hash"]

    result = repo.confirm_mirror_intent(
        intent_id="intent-mirror-1",
        challenge_id=challenge["challenge_id"],
        client_preview_hash=challenge["preview_hash"],
        user_id="user-1",
        interaction_type="HOLD_TO_FOLLOW",
        legal_version="2026.02.08",
        now_utc=now + dt.timedelta(seconds=2),
    )
    assert result["status_before"] == IntentStatus.VALIDATED.value
    assert result["status_after"] == IntentStatus.SUBMITTED.value
    assert result["consent_id"]

    updated = repo.get_intent("intent-mirror-1")
    assert updated is not None
    assert updated.status == IntentStatus.SUBMITTED
    assert updated.reason_code == "MIRROR_CONFIRMED"

    with repo.connection() as conn:
        consent = conn.execute(
            "SELECT consent_id, intent_id FROM user_consent_log WHERE intent_id = ?",
            ("intent-mirror-1",),
        ).fetchone()
        assert consent is not None
        assert consent["consent_id"] == result["consent_id"]
        challenge_row = conn.execute(
            "SELECT used_at_utc FROM mirror_challenges WHERE challenge_id = ?",
            (challenge["challenge_id"],),
        ).fetchone()
        assert challenge_row is not None
        assert str(challenge_row["used_at_utc"] or "") != ""


def test_mirror_confirm_rejects_preview_hash_mismatch(tmp_path):
    repo = SQLiteAllocatorRepository(tmp_path / "allocator.db")
    repo.initialize()
    now = dt.datetime(2026, 2, 8, 15, 0, tzinfo=dt.timezone.utc)
    repo.insert_intent(
        _intent(
            "intent-mirror-2",
            idempotency_key="idem-mirror-2",
            status=IntentStatus.VALIDATED,
        )
    )
    challenge = repo.create_mirror_challenge(
        intent_id="intent-mirror-2",
        now_utc=now,
        ttl_seconds=300,
        created_by="test",
    )

    with pytest.raises(MirrorIntentError) as exc_info:
        repo.confirm_mirror_intent(
            intent_id="intent-mirror-2",
            challenge_id=challenge["challenge_id"],
            client_preview_hash="bad-hash",
            user_id="user-1",
            interaction_type="HOLD_TO_FOLLOW",
            legal_version="2026.02.08",
            now_utc=now + dt.timedelta(seconds=1),
        )

    assert exc_info.value.code == "CONFLICT_PREVIEW_HASH_MISMATCH"
    unchanged = repo.get_intent("intent-mirror-2")
    assert unchanged is not None
    assert unchanged.status == IntentStatus.VALIDATED
