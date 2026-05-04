import datetime as dt

from tradingagents.capital_allocator.contracts import (
    AllocationIntent,
    AssetClassId,
    ExecutionMode,
    FundingSourceStatus,
    IntentStatus,
    Lane,
    ValuationMethodology,
)
from tradingagents.capital_allocator.reporting import build_allocator_report_card
from tradingagents.capital_allocator.repository import SQLiteAllocatorRepository


def _intent(
    *,
    intent_id: str,
    lane: Lane,
    status: IntentStatus,
    created_at: dt.datetime,
    execution_mode: ExecutionMode,
    funding_source_status: FundingSourceStatus = FundingSourceStatus.SETTLED_CASH,
    reason_code: str = "",
    reason: str = "",
    target_notional_usd: float = 100000.0,
) -> AllocationIntent:
    return AllocationIntent(
        intent_id=intent_id,
        run_id="alpha-day7",
        lane=lane,
        symbol=f"SYM{intent_id[-1]}",
        asset_id=f"asset-{intent_id[-1]}",
        asset_class_id=AssetClassId.LISTED_EQUITY,
        valuation_methodology=ValuationMethodology.MARK_TO_MARKET,
        execution_mode=execution_mode,
        side="BUY",
        target_notional_usd=target_notional_usd,
        correlation_group_tag="TEST_GROUP",
        funding_source_status=funding_source_status,
        funding_available_at_utc=None,
        funding_reservation_id=f"reserve-{intent_id}",
        snapshot_id="snap-day7",
        snapshot_hash_canonical="hash-c",
        snapshot_hash_raw="hash-r",
        max_slippage_bps=150.0,
        created_at_utc=created_at,
        expires_at_utc=created_at + dt.timedelta(days=1),
        status=status,
        idempotency_key=f"idem-{intent_id}",
        reason_code=reason_code,
        reason=reason,
    )


def test_build_allocator_report_card_aggregates_statuses(tmp_path):
    repo = SQLiteAllocatorRepository(tmp_path / "allocator_day7.db")
    repo.initialize()
    now = dt.datetime(2026, 2, 8, 14, 0, tzinfo=dt.timezone.utc)

    repo.insert_intent(
        _intent(
            intent_id="intent-1",
            lane=Lane.CORE,
            status=IntentStatus.VALIDATED,
            created_at=now - dt.timedelta(hours=2),
            execution_mode=ExecutionMode.LIVE,
            target_notional_usd=250000.0,
        )
    )
    repo.insert_intent(
        _intent(
            intent_id="intent-2",
            lane=Lane.MOMENTUM,
            status=IntentStatus.REJECTED_IMPACT_VETO,
            created_at=now - dt.timedelta(hours=1),
            execution_mode=ExecutionMode.LIVE,
            reason_code=IntentStatus.REJECTED_IMPACT_VETO.value,
            reason="impact exceeds expected edge",
            target_notional_usd=700000.0,
        )
    )
    repo.insert_intent(
        _intent(
            intent_id="intent-3",
            lane=Lane.HEDGE,
            status=IntentStatus.VALIDATED_WAIT_FUNDING,
            created_at=now - dt.timedelta(minutes=30),
            execution_mode=ExecutionMode.SHADOW,
            funding_source_status=FundingSourceStatus.PENDING_SALE_PROCEEDS,
            target_notional_usd=50000.0,
        )
    )

    report = build_allocator_report_card(repo=repo, lookback_days=7, now_utc=now)

    assert report["total_intents"] == 3
    assert report["validated_count"] == 2
    assert report["rejected_count"] == 1
    assert report["pending_count"] == 2
    assert report["pending_funding_count"] == 1
    assert report["status_counts"][IntentStatus.REJECTED_IMPACT_VETO.value] == 1
    assert report["status_counts"][IntentStatus.VALIDATED.value] == 1
    assert report["status_counts"][IntentStatus.VALIDATED_WAIT_FUNDING.value] == 1
    assert report["by_execution_mode"]["LIVE"] == 2
    assert report["by_execution_mode"]["SHADOW"] == 1
    assert report["rejection_reason_counts"][0]["reason_code"] == IntentStatus.REJECTED_IMPACT_VETO.value
    assert report["rejection_reason_counts"][0]["count"] == 1
