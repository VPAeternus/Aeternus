import datetime as dt

from tradingagents.capital_allocator.contracts import Lane, RegimeShock, ValuationMethodology
from tradingagents.capital_allocator.liability_engine import (
    AssetLiabilityProfile,
    ConstantRegimePremiumProvider,
    ConstantRiskFreeRateProvider,
    LiabilityConfig,
    LiabilityEngine,
    LiabilityInputs,
)


def _profile(**overrides) -> AssetLiabilityProfile:
    payload = dict(
        asset_class_id="PRIVATE_EQUITY",
        valuation_methodology=ValuationMethodology.MARK_TO_MODEL,
        liquidity_horizon_days=365,
        revaluation_interval_days=30,
        lockup_days=365,
    )
    payload.update(overrides)
    return AssetLiabilityProfile(**payload)


def _inputs(**overrides) -> LiabilityInputs:
    payload = dict(
        as_of_utc=dt.datetime(2026, 2, 8, 15, 0, tzinfo=dt.timezone.utc),
        lane=Lane.MOMENTUM,
        regime=RegimeShock.STRESS,
        notional_usd=50_000.0,
        nav_usd=1_000_000.0,
        adv30_notional_usd=5_000_000.0,
        vol20d_bps=200.0,
        spread_floor_bps=3.0,
        tax_cost_bps=25.0,
        expected_edge_bps=300.0,
        last_valuation_at_utc=dt.datetime(2025, 12, 1, 15, 0, tzinfo=dt.timezone.utc),
    )
    payload.update(overrides)
    return LiabilityInputs(**payload)


def test_lane_specific_k_affects_impact():
    engine = LiabilityEngine(
        config=LiabilityConfig(internal_spread_bps=0.0),
        risk_free_provider=ConstantRiskFreeRateProvider(rf_bps=0.0),
        regime_provider=ConstantRegimePremiumProvider(
            premiums_bps={
                RegimeShock.NORMAL: 0.0,
                RegimeShock.STRESS: 0.0,
                RegimeShock.SHOCK: 0.0,
                RegimeShock.CRISIS: 0.0,
            }
        ),
    )
    participation = engine.participation(10_000.0, 2_000_000.0)
    core_impact = engine.impact_bps(
        lane=Lane.CORE,
        spread_floor_bps=2.0,
        vol20d_bps=200.0,
        participation=participation,
    )
    momentum_impact = engine.impact_bps(
        lane=Lane.MOMENTUM,
        spread_floor_bps=2.0,
        vol20d_bps=200.0,
        participation=participation,
    )
    assert momentum_impact > core_impact


def test_stale_haircut_applies_after_revaluation_interval():
    engine = LiabilityEngine()
    as_of = dt.datetime(2026, 2, 8, 15, 0, tzinfo=dt.timezone.utc)
    haircut = engine.stale_haircut_bps(
        as_of_utc=as_of,
        last_valuation_at_utc=as_of - dt.timedelta(days=100),
        revaluation_interval_days=30,
    )
    assert haircut > 0


def test_evaluate_returns_net_edge_breakdown():
    engine = LiabilityEngine(
        config=LiabilityConfig(internal_spread_bps=50.0, stale_daily_haircut_bps=0.0, stale_max_haircut_bps=0.0),
        risk_free_provider=ConstantRiskFreeRateProvider(rf_bps=100.0),
        regime_provider=ConstantRegimePremiumProvider(
            premiums_bps={
                RegimeShock.NORMAL: 0.0,
                RegimeShock.STRESS: 20.0,
                RegimeShock.SHOCK: 60.0,
                RegimeShock.CRISIS: 120.0,
            }
        ),
    )
    breakdown = engine.evaluate(profile=_profile(), inputs=_inputs(expected_edge_bps=500.0))
    assert breakdown.hurdle_bps > 0
    assert breakdown.impact_bps > 0
    assert breakdown.net_edge_bps != 0


def test_participation_missing_adv_returns_infinity():
    engine = LiabilityEngine()
    part = engine.participation(10_000.0, None)
    assert part == float("inf")
    impact = engine.impact_bps(
        lane=Lane.CORE,
        spread_floor_bps=2.0,
        vol20d_bps=100.0,
        participation=part,
    )
    assert impact == float("inf")


def test_liquidity_premium_can_reject_positive_edge_even_with_zero_other_costs():
    engine = LiabilityEngine(
        config=LiabilityConfig(internal_spread_bps=0.0, stale_daily_haircut_bps=0.0, stale_max_haircut_bps=0.0),
        risk_free_provider=ConstantRiskFreeRateProvider(rf_bps=0.0),
        regime_provider=ConstantRegimePremiumProvider(
            premiums_bps={
                RegimeShock.NORMAL: 0.0,
                RegimeShock.STRESS: 0.0,
                RegimeShock.SHOCK: 0.0,
                RegimeShock.CRISIS: 0.0,
            }
        ),
    )
    profile = _profile(liquidity_horizon_days=3650, lockup_days=3650)
    inputs = _inputs(
        expected_edge_bps=250.0,
        spread_floor_bps=0.0,
        vol20d_bps=0.0,
        tax_cost_bps=0.0,
        notional_usd=300_000.0,
        nav_usd=1_000_000.0,
    )
    breakdown = engine.evaluate(profile=profile, inputs=inputs)
    assert breakdown.hurdle_bps == breakdown.liquidity_premium_bps
    assert breakdown.liquidity_premium_bps > inputs.expected_edge_bps
    assert breakdown.net_edge_bps < 0.0
