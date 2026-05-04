import datetime as dt

from tradingagents.capital_allocator.allocator import AllocationContextProvider, CapitalAllocator
from tradingagents.capital_allocator.contracts import (
    AllocationIntent,
    AssetClassId,
    DecisionObservation,
    ExecutionMode,
    FundingSourceStatus,
    IntentStatus,
    Lane,
    MarketSnapshot,
    PortfolioSnapshot,
    RegimeShock,
    ReliabilityInputs,
    ValuationMethodology,
)
from tradingagents.capital_allocator.liability_engine import (
    AssetLiabilityProfile,
    ConstantRegimePremiumProvider,
    ConstantRiskFreeRateProvider,
    LiabilityConfig,
    LiabilityEngine,
)
from tradingagents.capital_allocator.repository import SQLiteAllocatorRepository


def _intent(intent_id: str, *, symbol: str = "AAPL", **overrides) -> AllocationIntent:
    base = AllocationIntent(
        intent_id=intent_id,
        run_id="run-1",
        lane=Lane.CORE,
        symbol=symbol,
        asset_id=symbol,
        asset_class_id=AssetClassId.LISTED_EQUITY,
        valuation_methodology=ValuationMethodology.MARK_TO_MARKET,
        execution_mode=ExecutionMode.LIVE,
        side="BUY",
        target_notional_usd=5000.0,
        correlation_group_tag="AAPL_SINGLE",
        funding_source_status=FundingSourceStatus.SETTLED_CASH,
        funding_available_at_utc=None,
        funding_reservation_id=None,
        snapshot_id="snap-1",
        snapshot_hash_canonical="hash",
        max_slippage_bps=150.0,
        created_at_utc=dt.datetime(2026, 2, 8, 15, 0, tzinfo=dt.timezone.utc),
        expires_at_utc=dt.datetime(2026, 2, 8, 16, 0, tzinfo=dt.timezone.utc),
        status=IntentStatus.PROPOSED,
        idempotency_key=f"idem-{intent_id}",
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


def _portfolio() -> PortfolioSnapshot:
    return PortfolioSnapshot(
        symbols=["AAPL", "MSFT", "SPY"],
        weights=[0.10, 0.10, 0.30],
        covariance=[
            [0.04, 0.02, 0.01],
            [0.02, 0.03, 0.01],
            [0.01, 0.01, 0.02],
        ],
        group_tags={"AAPL": "AAPL_SINGLE", "MSFT": "MSFT_SINGLE", "SPY": "INDEX"},
        nav_usd=100_000.0,
        margin_utilization=0.20,
        margin_cap=0.35,
    )


def _history() -> list[DecisionObservation]:
    return [
        DecisionObservation(score=82.0, edge_bps=140.0, age_days=2.0, age_decisions=1.0),
        DecisionObservation(score=70.0, edge_bps=50.0, age_days=6.0, age_decisions=2.0),
        DecisionObservation(score=52.0, edge_bps=-10.0, age_days=10.0, age_decisions=3.0),
    ]


def _reliability_inputs(e_raw_bps: float = 2500.0) -> ReliabilityInputs:
    return ReliabilityInputs(
        e_raw_bps=e_raw_bps,
        r_data=0.9,
        r_global=0.55,
        r_regime_raw=0.60,
        n_eff_regime=30.0,
    )


def _market_snapshot(**overrides) -> MarketSnapshot:
    base = MarketSnapshot(
        symbol="AAPL",
        snapshot_time_utc=dt.datetime(2026, 2, 8, 15, 0, tzinfo=dt.timezone.utc),
        price=100.0,
        adv30_notional_usd=2_000_000.0,
        vol20d_bps=100.0,
        spread_bps=2.0,
        source_latency_ms=100,
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


def _liability_profile(**overrides) -> AssetLiabilityProfile:
    payload = dict(
        asset_class_id="LISTED_EQUITY",
        valuation_methodology=ValuationMethodology.MARK_TO_MARKET,
        liquidity_horizon_days=2,
        revaluation_interval_days=30,
        lockup_days=0,
    )
    payload.update(overrides)
    return AssetLiabilityProfile(**payload)


def _allocator(repo: SQLiteAllocatorRepository) -> CapitalAllocator:
    # Keep hurdle low in service tests so we can isolate each gate deterministically.
    liability_engine = LiabilityEngine(
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
    return CapitalAllocator(repository=repo, liability_engine=liability_engine)


def test_evaluate_proposed_intent_validates_and_persists_validation(tmp_path):
    repo = SQLiteAllocatorRepository(tmp_path / "allocator.db")
    repo.initialize()
    intent = _intent("intent-ok")
    repo.insert_intent(intent)
    allocator = _allocator(repo)

    status = allocator.evaluate_proposed_intent(
        intent=intent,
        portfolio=_portfolio(),
        shock=RegimeShock.NORMAL,
        observations=_history(),
        reliability_inputs=_reliability_inputs(),
        market_snapshot=_market_snapshot(),
        liability_profile=_liability_profile(),
        tax_cost_bps=0.0,
        validation_price=100.0,
        price_source_latency_ms=100,
        now_utc=dt.datetime(2026, 2, 8, 15, 5, tzinfo=dt.timezone.utc),
    )
    assert status == IntentStatus.VALIDATED
    stored = repo.get_intent("intent-ok")
    assert stored is not None
    assert stored.status == IntentStatus.VALIDATED
    assert stored.adjusted_edge_bps > 0


def test_evaluate_proposed_intent_rejects_covariance(tmp_path):
    repo = SQLiteAllocatorRepository(tmp_path / "allocator.db")
    repo.initialize()
    intent = _intent("intent-cov", target_notional_usd=30_000.0)
    repo.insert_intent(intent)
    allocator = _allocator(repo)

    status = allocator.evaluate_proposed_intent(
        intent=intent,
        portfolio=_portfolio(),
        shock=RegimeShock.STRESS,
        observations=_history(),
        reliability_inputs=_reliability_inputs(),
        market_snapshot=_market_snapshot(adv30_notional_usd=5_000_000.0),
        liability_profile=_liability_profile(),
        tax_cost_bps=0.0,
        validation_price=100.0,
        price_source_latency_ms=100,
        now_utc=dt.datetime(2026, 2, 8, 15, 5, tzinfo=dt.timezone.utc),
    )
    assert status == IntentStatus.REJECTED_COVARIANCE_VETO
    receipts = repo.list_receipts(intent_id="intent-cov")
    assert receipts


def test_evaluate_proposed_intent_waits_for_funding(tmp_path):
    repo = SQLiteAllocatorRepository(tmp_path / "allocator.db")
    repo.initialize()
    now = dt.datetime(2026, 2, 8, 15, 5, tzinfo=dt.timezone.utc)
    intent = _intent(
        "intent-wait",
        funding_source_status=FundingSourceStatus.PENDING_SALE_PROCEEDS,
        funding_available_at_utc=now + dt.timedelta(minutes=20),
    )
    repo.insert_intent(intent)
    allocator = _allocator(repo)

    status = allocator.evaluate_proposed_intent(
        intent=intent,
        portfolio=_portfolio(),
        shock=RegimeShock.NORMAL,
        observations=_history(),
        reliability_inputs=_reliability_inputs(),
        market_snapshot=_market_snapshot(),
        liability_profile=_liability_profile(),
        tax_cost_bps=0.0,
        validation_price=100.0,
        price_source_latency_ms=100,
        now_utc=now,
    )
    assert status == IntentStatus.VALIDATED_WAIT_FUNDING


def test_evaluate_proposed_intent_rejects_latency(tmp_path):
    repo = SQLiteAllocatorRepository(tmp_path / "allocator.db")
    repo.initialize()
    intent = _intent("intent-lat")
    repo.insert_intent(intent)
    allocator = _allocator(repo)

    status = allocator.evaluate_proposed_intent(
        intent=intent,
        portfolio=_portfolio(),
        shock=RegimeShock.NORMAL,
        observations=_history(),
        reliability_inputs=_reliability_inputs(),
        market_snapshot=_market_snapshot(source_latency_ms=2501),
        liability_profile=_liability_profile(),
        tax_cost_bps=0.0,
        validation_price=100.0,
        price_source_latency_ms=2501,
        now_utc=dt.datetime(2026, 2, 8, 15, 5, tzinfo=dt.timezone.utc),
    )
    assert status == IntentStatus.REJECTED_PRICE_SLIP


def test_evaluate_proposed_intent_rejects_impact_veto(tmp_path):
    repo = SQLiteAllocatorRepository(tmp_path / "allocator.db")
    repo.initialize()
    intent = _intent("intent-impact", target_notional_usd=50_000.0)
    repo.insert_intent(intent)
    allocator = _allocator(repo)

    status = allocator.evaluate_proposed_intent(
        intent=intent,
        portfolio=_portfolio(),
        shock=RegimeShock.NORMAL,
        observations=_history(),
        reliability_inputs=_reliability_inputs(),
        market_snapshot=_market_snapshot(adv30_notional_usd=2_000_000.0),
        liability_profile=_liability_profile(),
        tax_cost_bps=0.0,
        validation_price=100.0,
        price_source_latency_ms=100,
        now_utc=dt.datetime(2026, 2, 8, 15, 5, tzinfo=dt.timezone.utc),
    )
    assert status == IntentStatus.REJECTED_IMPACT_VETO


def test_evaluate_proposed_intent_rejects_liability_hurdle_for_shadow_stale(tmp_path):
    repo = SQLiteAllocatorRepository(tmp_path / "allocator.db")
    repo.initialize()
    now = dt.datetime(2026, 2, 8, 15, 5, tzinfo=dt.timezone.utc)
    intent = _intent(
        "intent-shadow",
        execution_mode=ExecutionMode.SHADOW,
        valuation_methodology=ValuationMethodology.MARK_TO_MODEL,
        asset_class_id=AssetClassId.PRIVATE_EQUITY,
        target_notional_usd=20_000.0,
        last_valuation_at_utc=now - dt.timedelta(days=120),
    )
    repo.insert_intent(intent)
    allocator = CapitalAllocator(repository=repo)  # default liability config includes stale haircut + hurdle

    status = allocator.evaluate_proposed_intent(
        intent=intent,
        portfolio=_portfolio(),
        shock=RegimeShock.NORMAL,
        observations=_history(),
        reliability_inputs=_reliability_inputs(e_raw_bps=80.0),
        market_snapshot=_market_snapshot(adv30_notional_usd=5_000_000.0, spread_bps=5.0, vol20d_bps=180.0),
        liability_profile=_liability_profile(
            asset_class_id="PRIVATE_EQUITY",
            valuation_methodology=ValuationMethodology.MARK_TO_MODEL,
            liquidity_horizon_days=720,
            revaluation_interval_days=30,
            lockup_days=365,
        ),
        tax_cost_bps=25.0,
        validation_price=100.0,
        price_source_latency_ms=100,
        now_utc=now,
    )
    assert status == IntentStatus.REJECTED_LIABILITY_HURDLE


def test_heartbeat_validate_processes_proposed_set(tmp_path):
    repo = SQLiteAllocatorRepository(tmp_path / "allocator.db")
    repo.initialize()
    repo.insert_intent(_intent("intent-hb-1", symbol="AAPL"))
    repo.insert_intent(_intent("intent-hb-2", symbol="MSFT", asset_id="MSFT"))
    allocator = _allocator(repo)
    now = dt.datetime(2026, 2, 8, 15, 5, tzinfo=dt.timezone.utc)

    provider = AllocationContextProvider(
        portfolio_provider=lambda _: _portfolio(),
        shock_provider=lambda _: RegimeShock.NORMAL,
        lane_history_provider=lambda _: _history(),
        reliability_inputs_provider=lambda _: _reliability_inputs(),
        market_snapshot_provider=lambda _: _market_snapshot(),
        liability_profile_provider=lambda _: _liability_profile(),
        tax_cost_bps_provider=lambda _: 0.0,
    )

    outcomes = allocator.heartbeat_validate(provider=provider, now_utc=now)
    assert len(outcomes) == 2
    assert {status for _intent_id, status in outcomes} == {IntentStatus.VALIDATED}


def test_regime_crossover_probe_validated_in_normal_rejected_in_crisis(tmp_path):
    repo = SQLiteAllocatorRepository(tmp_path / "allocator.db")
    repo.initialize()
    allocator = CapitalAllocator(repository=repo)
    now = dt.datetime(2026, 2, 8, 15, 5, tzinfo=dt.timezone.utc)

    portfolio = PortfolioSnapshot(
        symbols=["QQQ", "SPY", "AAPL"],
        weights=[0.005, 0.005, 0.005],
        covariance=[
            [0.035, 0.006, 0.006],
            [0.006, 0.035, 0.006],
            [0.006, 0.006, 0.035],
        ],
        group_tags={"QQQ": "CROSSOVER", "SPY": "INDEX", "AAPL": "MEGA"},
        nav_usd=100_000_000.0,
        margin_utilization=0.12,
        margin_cap=0.35,
    )
    observations = [
        DecisionObservation(score=71.0, edge_bps=85.0, age_days=5.0, age_decisions=1.0),
        DecisionObservation(score=62.0, edge_bps=45.0, age_days=14.0, age_decisions=2.0),
        DecisionObservation(score=58.0, edge_bps=10.0, age_days=21.0, age_decisions=3.0),
    ]
    reliability_inputs = ReliabilityInputs(
        e_raw_bps=4000.0,
        r_data=0.88,
        r_global=0.57,
        r_regime_raw=0.62,
        n_eff_regime=32.0,
    )
    market_snapshot = MarketSnapshot(
        symbol="QQQ",
        snapshot_time_utc=now,
        price=525.0,
        adv30_notional_usd=24_000_000_000.0,
        vol20d_bps=145.0,
        spread_bps=0.5,
        source_latency_ms=100,
    )
    profile = AssetLiabilityProfile(
        asset_class_id="LISTED_EQUITY",
        valuation_methodology=ValuationMethodology.MARK_TO_MARKET,
        liquidity_horizon_days=2,
        revaluation_interval_days=30,
        lockup_days=0,
    )

    normal_intent = _intent(
        "intent-cross-normal",
        symbol="QQQ",
        target_notional_usd=10_000.0,
        correlation_group_tag="CROSSOVER",
    )
    repo.insert_intent(normal_intent)
    normal_status = allocator.evaluate_proposed_intent(
        intent=normal_intent,
        portfolio=portfolio,
        shock=RegimeShock.NORMAL,
        observations=observations,
        reliability_inputs=reliability_inputs,
        market_snapshot=market_snapshot,
        liability_profile=profile,
        tax_cost_bps=15.0,
        validation_price=525.0,
        price_source_latency_ms=100,
        now_utc=now,
    )
    assert normal_status == IntentStatus.VALIDATED

    crisis_intent = _intent(
        "intent-cross-crisis",
        symbol="QQQ",
        target_notional_usd=10_000.0,
        correlation_group_tag="CROSSOVER",
    )
    repo.insert_intent(crisis_intent)
    crisis_status = allocator.evaluate_proposed_intent(
        intent=crisis_intent,
        portfolio=portfolio,
        shock=RegimeShock.CRISIS,
        observations=observations,
        reliability_inputs=reliability_inputs,
        market_snapshot=market_snapshot,
        liability_profile=profile,
        tax_cost_bps=15.0,
        validation_price=525.0,
        price_source_latency_ms=100,
        now_utc=now,
    )
    assert crisis_status == IntentStatus.REJECTED_LIABILITY_HURDLE


def test_crisis_concentration_wall_rejects_semis_additive_intent(tmp_path):
    repo = SQLiteAllocatorRepository(tmp_path / "allocator.db")
    repo.initialize()
    allocator = CapitalAllocator(repository=repo)
    now = dt.datetime(2026, 2, 8, 15, 5, tzinfo=dt.timezone.utc)

    portfolio = PortfolioSnapshot(
        symbols=["NVDA", "AVGO", "XLE", "SPY"],
        weights=[0.09, 0.00, 0.03, 0.20],
        covariance=[
            [0.030, 0.000, 0.000, 0.000],
            [0.000, 0.030, 0.000, 0.000],
            [0.000, 0.000, 0.030, 0.000],
            [0.000, 0.000, 0.000, 0.030],
        ],
        group_tags={"NVDA": "SEMIS", "AVGO": "SEMIS", "XLE": "ENERGY", "SPY": "INDEX"},
        nav_usd=100_000_000.0,
        margin_utilization=0.10,
        margin_cap=0.35,
    )
    intent = _intent(
        "intent-day5",
        symbol="AVGO",
        lane=Lane.MOMENTUM,
        target_notional_usd=2_000_000.0,
        correlation_group_tag="SEMIS",
    )
    repo.insert_intent(intent)
    status = allocator.evaluate_proposed_intent(
        intent=intent,
        portfolio=portfolio,
        shock=RegimeShock.CRISIS,
        observations=[
            DecisionObservation(score=84.0, edge_bps=210.0, age_days=2.0, age_decisions=1.0),
            DecisionObservation(score=73.0, edge_bps=95.0, age_days=6.0, age_decisions=2.0),
            DecisionObservation(score=62.0, edge_bps=30.0, age_days=12.0, age_decisions=3.0),
        ],
        reliability_inputs=ReliabilityInputs(
            e_raw_bps=30_000.0,  # high edge to avoid liability false positives; isolate covariance gate.
            r_data=0.90,
            r_global=0.60,
            r_regime_raw=0.64,
            n_eff_regime=40.0,
        ),
        market_snapshot=MarketSnapshot(
            symbol="AVGO",
            snapshot_time_utc=now,
            price=1_180.0,
            adv30_notional_usd=12_000_000_000.0,
            vol20d_bps=190.0,
            spread_bps=0.8,
            source_latency_ms=120,
        ),
        liability_profile=AssetLiabilityProfile(
            asset_class_id="LISTED_EQUITY",
            valuation_methodology=ValuationMethodology.MARK_TO_MARKET,
            liquidity_horizon_days=2,
            revaluation_interval_days=30,
            lockup_days=0,
        ),
        tax_cost_bps=15.0,
        validation_price=1_180.0,
        price_source_latency_ms=120,
        now_utc=now,
    )
    assert status == IntentStatus.REJECTED_COVARIANCE_VETO


def test_concentration_wall_same_vector_allows_in_normal_regime(tmp_path):
    repo = SQLiteAllocatorRepository(tmp_path / "allocator.db")
    repo.initialize()
    allocator = CapitalAllocator(repository=repo)
    now = dt.datetime(2026, 2, 8, 15, 5, tzinfo=dt.timezone.utc)

    portfolio = PortfolioSnapshot(
        symbols=["NVDA", "AVGO", "XLE", "SPY"],
        weights=[0.09, 0.00, 0.03, 0.20],
        covariance=[
            [0.030, 0.000, 0.000, 0.000],
            [0.000, 0.030, 0.000, 0.000],
            [0.000, 0.000, 0.030, 0.000],
            [0.000, 0.000, 0.000, 0.030],
        ],
        group_tags={"NVDA": "SEMIS", "AVGO": "SEMIS", "XLE": "ENERGY", "SPY": "INDEX"},
        nav_usd=100_000_000.0,
        margin_utilization=0.10,
        margin_cap=0.35,
    )
    intent = _intent(
        "intent-day5-normal",
        symbol="AVGO",
        lane=Lane.MOMENTUM,
        target_notional_usd=2_000_000.0,
        correlation_group_tag="SEMIS",
    )
    repo.insert_intent(intent)
    status = allocator.evaluate_proposed_intent(
        intent=intent,
        portfolio=portfolio,
        shock=RegimeShock.NORMAL,
        observations=[
            DecisionObservation(score=84.0, edge_bps=210.0, age_days=2.0, age_decisions=1.0),
            DecisionObservation(score=73.0, edge_bps=95.0, age_days=6.0, age_decisions=2.0),
            DecisionObservation(score=62.0, edge_bps=30.0, age_days=12.0, age_decisions=3.0),
        ],
        reliability_inputs=ReliabilityInputs(
            e_raw_bps=30_000.0,
            r_data=0.90,
            r_global=0.60,
            r_regime_raw=0.64,
            n_eff_regime=40.0,
        ),
        market_snapshot=MarketSnapshot(
            symbol="AVGO",
            snapshot_time_utc=now,
            price=1_180.0,
            adv30_notional_usd=12_000_000_000.0,
            vol20d_bps=190.0,
            spread_bps=0.8,
            source_latency_ms=120,
        ),
        liability_profile=AssetLiabilityProfile(
            asset_class_id="LISTED_EQUITY",
            valuation_methodology=ValuationMethodology.MARK_TO_MARKET,
            liquidity_horizon_days=2,
            revaluation_interval_days=30,
            lockup_days=0,
        ),
        tax_cost_bps=15.0,
        validation_price=1_180.0,
        price_source_latency_ms=120,
        now_utc=now,
    )
    assert status == IntentStatus.VALIDATED


def test_crisis_breached_group_allows_risk_reducing_sell_exit(tmp_path):
    repo = SQLiteAllocatorRepository(tmp_path / "allocator.db")
    repo.initialize()
    allocator = CapitalAllocator(repository=repo)
    now = dt.datetime(2026, 2, 8, 15, 5, tzinfo=dt.timezone.utc)

    # Existing SEMIS exposure is 15% in crisis (already above 10% cap).
    portfolio = PortfolioSnapshot(
        symbols=["NVDA", "AVGO", "XLE", "SPY"],
        weights=[0.15, 0.00, 0.03, 0.20],
        covariance=[
            [0.030, 0.000, 0.000, 0.000],
            [0.000, 0.030, 0.000, 0.000],
            [0.000, 0.000, 0.030, 0.000],
            [0.000, 0.000, 0.000, 0.030],
        ],
        group_tags={"NVDA": "SEMIS", "AVGO": "SEMIS", "XLE": "ENERGY", "SPY": "INDEX"},
        nav_usd=100_000_000.0,
        margin_utilization=0.10,
        margin_cap=0.35,
    )
    intent = _intent(
        "intent-day6-exit",
        symbol="NVDA",
        lane=Lane.MOMENTUM,
        side="SELL",
        target_notional_usd=5_000_000.0,  # 5% NAV sell from 15% -> 10%
        correlation_group_tag="SEMIS",
    )
    repo.insert_intent(intent)
    status = allocator.evaluate_proposed_intent(
        intent=intent,
        portfolio=portfolio,
        shock=RegimeShock.CRISIS,
        observations=[
            DecisionObservation(score=86.0, edge_bps=260.0, age_days=2.0, age_decisions=1.0),
            DecisionObservation(score=74.0, edge_bps=115.0, age_days=6.0, age_decisions=2.0),
            DecisionObservation(score=66.0, edge_bps=40.0, age_days=12.0, age_decisions=3.0),
        ],
        reliability_inputs=ReliabilityInputs(
            e_raw_bps=35_000.0,  # keep liability non-binding to isolate covariance directionality
            r_data=0.90,
            r_global=0.60,
            r_regime_raw=0.64,
            n_eff_regime=40.0,
        ),
        market_snapshot=MarketSnapshot(
            symbol="NVDA",
            snapshot_time_utc=now,
            price=710.0,
            adv30_notional_usd=28_000_000_000.0,
            vol20d_bps=240.0,
            spread_bps=1.0,
            source_latency_ms=120,
        ),
        liability_profile=AssetLiabilityProfile(
            asset_class_id="LISTED_EQUITY",
            valuation_methodology=ValuationMethodology.MARK_TO_MARKET,
            liquidity_horizon_days=2,
            revaluation_interval_days=30,
            lockup_days=0,
        ),
        tax_cost_bps=15.0,
        validation_price=710.0,
        price_source_latency_ms=120,
        now_utc=now,
    )
    assert status == IntentStatus.VALIDATED


def test_day6_illiquid_panic_sell_still_rejected_by_impact_gate(tmp_path):
    repo = SQLiteAllocatorRepository(tmp_path / "allocator.db")
    repo.initialize()
    allocator = CapitalAllocator(repository=repo)
    now = dt.datetime(2026, 2, 8, 15, 5, tzinfo=dt.timezone.utc)

    portfolio = PortfolioSnapshot(
        symbols=["ILLQ", "XLE", "SPY"],
        weights=[0.03, 0.03, 0.20],
        covariance=[
            [0.040, 0.000, 0.000],
            [0.000, 0.030, 0.000],
            [0.000, 0.000, 0.030],
        ],
        group_tags={"ILLQ": "MICRO_CAP", "XLE": "ENERGY", "SPY": "INDEX"},
        nav_usd=100_000_000.0,
        margin_utilization=0.10,
        margin_cap=0.35,
    )
    intent = _intent(
        "intent-day6-illiquid-sell",
        symbol="ILLQ",
        lane=Lane.MOMENTUM,
        side="SELL",
        target_notional_usd=8_000_000.0,  # 40% of 20M ADV30 -> impact veto
        correlation_group_tag="MICRO_CAP",
    )
    repo.insert_intent(intent)
    status = allocator.evaluate_proposed_intent(
        intent=intent,
        portfolio=portfolio,
        shock=RegimeShock.CRISIS,
        observations=[
            DecisionObservation(score=80.0, edge_bps=180.0, age_days=2.0, age_decisions=1.0),
            DecisionObservation(score=70.0, edge_bps=85.0, age_days=6.0, age_decisions=2.0),
            DecisionObservation(score=60.0, edge_bps=20.0, age_days=12.0, age_decisions=3.0),
        ],
        reliability_inputs=ReliabilityInputs(
            e_raw_bps=35_000.0,
            r_data=0.90,
            r_global=0.60,
            r_regime_raw=0.64,
            n_eff_regime=40.0,
        ),
        market_snapshot=MarketSnapshot(
            symbol="ILLQ",
            snapshot_time_utc=now,
            price=17.5,
            adv30_notional_usd=20_000_000.0,
            vol20d_bps=420.0,
            spread_bps=9.0,
            source_latency_ms=120,
        ),
        liability_profile=AssetLiabilityProfile(
            asset_class_id="LISTED_EQUITY",
            valuation_methodology=ValuationMethodology.MARK_TO_MARKET,
            liquidity_horizon_days=3,
            revaluation_interval_days=30,
            lockup_days=0,
        ),
        tax_cost_bps=15.0,
        validation_price=17.5,
        price_source_latency_ms=120,
        now_utc=now,
    )
    assert status == IntentStatus.REJECTED_IMPACT_VETO
