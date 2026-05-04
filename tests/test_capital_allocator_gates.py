import datetime as dt

from tradingagents.capital_allocator.contracts import (
    AllocationIntent,
    AssetClassId,
    ExecutionMode,
    FundingSourceStatus,
    IntentStatus,
    Lane,
    MarketSnapshot,
    PortfolioSnapshot,
    RegimeShock,
    ValuationMethodology,
)
from tradingagents.capital_allocator.gates import CovarianceGate, FundingGate, ImpactGate, enforce_price_slip


def _sample_intent(**overrides):
    base = AllocationIntent(
        intent_id="intent-1",
        run_id="run-1",
        lane=Lane.MOMENTUM,
        symbol="NVDA",
        asset_id="NVDA",
        asset_class_id=AssetClassId.LISTED_EQUITY,
        valuation_methodology=ValuationMethodology.MARK_TO_MARKET,
        execution_mode=ExecutionMode.LIVE,
        side="BUY",
        target_notional_usd=10_000.0,
        correlation_group_tag="SEMIS",
        funding_source_status=FundingSourceStatus.SETTLED_CASH,
        funding_available_at_utc=None,
        funding_reservation_id=None,
        snapshot_id="snap-1",
        snapshot_hash_canonical="hash",
        max_slippage_bps=150.0,
        created_at_utc=dt.datetime(2026, 2, 8, 15, 0, tzinfo=dt.timezone.utc),
        expires_at_utc=dt.datetime(2026, 2, 8, 16, 0, tzinfo=dt.timezone.utc),
        status=IntentStatus.PROPOSED,
        idempotency_key="idem-1",
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


def _sample_market_snapshot(**overrides) -> MarketSnapshot:
    base = MarketSnapshot(
        symbol="NVDA",
        snapshot_time_utc=dt.datetime(2026, 2, 8, 15, 0, tzinfo=dt.timezone.utc),
        price=100.0,
        adv30_notional_usd=2_000_000.0,
        vol20d_bps=250.0,
        spread_bps=4.0,
        source_latency_ms=200,
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


def _sample_portfolio():
    return PortfolioSnapshot(
        symbols=["NVDA", "MSFT", "SPY"],
        weights=[0.10, 0.10, 0.30],
        covariance=[
            [0.04, 0.02, 0.01],
            [0.02, 0.03, 0.01],
            [0.01, 0.01, 0.02],
        ],
        group_tags={"NVDA": "SEMIS", "MSFT": "SOFTWARE", "SPY": "INDEX"},
        nav_usd=100_000.0,
        margin_utilization=0.20,
        margin_cap=0.35,
    )


def test_covariance_gate_rejects_group_cap_breach():
    gate = CovarianceGate()
    intent = _sample_intent(target_notional_usd=20_000.0)
    portfolio = _sample_portfolio()
    result = gate.evaluate(intent, portfolio, RegimeShock.STRESS)
    assert result.allowed is False
    assert result.code == IntentStatus.REJECTED_COVARIANCE_VETO.value


def test_covariance_gate_accepts_safe_trade():
    gate = CovarianceGate()
    intent = _sample_intent(target_notional_usd=5_000.0)
    portfolio = _sample_portfolio()
    result = gate.evaluate(intent, portfolio, RegimeShock.NORMAL)
    assert result.allowed is True
    assert result.code == "OK"


def test_funding_gate_waits_for_pending_proceeds():
    gate = FundingGate()
    now = dt.datetime(2026, 2, 8, 15, 0, tzinfo=dt.timezone.utc)
    intent = _sample_intent(
        funding_source_status=FundingSourceStatus.PENDING_SALE_PROCEEDS,
        funding_available_at_utc=now + dt.timedelta(minutes=10),
    )
    status, code = gate.evaluate(
        intent,
        now_utc=now,
        margin_utilization_post=0.1,
        margin_cap=0.35,
    )
    assert status == IntentStatus.VALIDATED_WAIT_FUNDING
    assert code == IntentStatus.VALIDATED_WAIT_FUNDING.value


def test_funding_gate_rejects_margin_over_cap():
    gate = FundingGate()
    now = dt.datetime(2026, 2, 8, 15, 0, tzinfo=dt.timezone.utc)
    intent = _sample_intent(funding_source_status=FundingSourceStatus.MARGIN_UTILIZED)
    status, code = gate.evaluate(
        intent,
        now_utc=now,
        margin_utilization_post=0.50,
        margin_cap=0.35,
    )
    assert status == IntentStatus.REJECTED_FUNDING
    assert code == "REJECTED_MARGIN_CAP"


def test_price_slip_rejects_latency_and_bps():
    latency_reject = enforce_price_slip(
        snapshot_price=100.0,
        execution_price=100.0,
        price_source_latency_ms=2500,
        max_slippage_bps=150.0,
    )
    assert latency_reject.allowed is False
    assert latency_reject.code == IntentStatus.REJECTED_PRICE_SLIP.value

    bps_reject = enforce_price_slip(
        snapshot_price=100.0,
        execution_price=102.0,
        price_source_latency_ms=20,
        max_slippage_bps=150.0,
    )
    assert bps_reject.allowed is False
    assert bps_reject.delta_bps is not None
    assert abs(bps_reject.delta_bps) > 150.0


def test_impact_gate_rejects_participation_above_one_percent():
    gate = ImpactGate()
    intent = _sample_intent(target_notional_usd=50_000.0)  # 2.5% participation on 2M ADV notional
    result = gate.evaluate(intent=intent, market_snapshot=_sample_market_snapshot())
    assert result.allowed is False
    assert result.code == IntentStatus.REJECTED_IMPACT_VETO.value
    assert result.participation > 0.01


def test_impact_gate_accepts_low_participation_and_returns_impact_estimate():
    gate = ImpactGate()
    intent = _sample_intent(target_notional_usd=10_000.0)  # 0.5%
    result = gate.evaluate(intent=intent, market_snapshot=_sample_market_snapshot())
    assert result.allowed is True
    assert result.code == "OK"
    assert result.impact_bps is not None
    assert result.impact_bps > 0


def test_impact_gate_rejects_missing_adv_with_infinite_participation():
    gate = ImpactGate()
    intent = _sample_intent(
        execution_mode=ExecutionMode.LIVE,
        asset_class_id=AssetClassId.LISTED_EQUITY,
    )
    result = gate.evaluate(intent=intent, market_snapshot=_sample_market_snapshot(adv30_notional_usd=None))
    assert result.allowed is False
    assert result.code == IntentStatus.REJECTED_IMPACT_VETO.value
    assert result.participation == float("inf")
    assert result.impact_bps is None


def test_impact_gate_allows_private_equity_shadow_without_adv():
    gate = ImpactGate()
    intent = _sample_intent(
        execution_mode=ExecutionMode.SHADOW,
        asset_class_id=AssetClassId.PRIVATE_EQUITY,
        valuation_methodology=ValuationMethodology.MARK_TO_MODEL,
    )
    result = gate.evaluate(intent=intent, market_snapshot=_sample_market_snapshot(adv30_notional_usd=None))
    assert result.allowed is True
    assert result.code == "OK"
    assert result.participation == 0.0
    assert result.impact_bps is not None
