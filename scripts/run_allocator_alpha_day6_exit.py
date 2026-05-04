#!/usr/bin/env python3
"""Run Day-6 roach-motel stress simulation (exit allowed, illiquid panic sell blocked)."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import uuid
from pathlib import Path

from tradingagents.capital_allocator.allocator import CapitalAllocator
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
from tradingagents.capital_allocator.liability_engine import AssetLiabilityProfile
from tradingagents.capital_allocator.market_snapshot_seed import seed_market_snapshot_cache
from tradingagents.capital_allocator.regime_override import write_regime_override
from tradingagents.capital_allocator.repository import SQLiteAllocatorRepository


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Day-6 exit/guillotine stress simulation.")
    parser.add_argument(
        "--db-path",
        default="eval_results/control/capital_allocator_alpha_day6.db",
        help="Allocator SQLite DB path for Day-6 run.",
    )
    parser.add_argument(
        "--override-path",
        default="eval_results/control/allocator_regime_override.json",
        help="Regime override artifact path.",
    )
    parser.add_argument(
        "--run-id",
        default="alpha-day6",
        help="Run id prefix.",
    )
    parser.add_argument(
        "--regime",
        default=RegimeShock.CRISIS.value,
        choices=[value.value for value in RegimeShock],
        help="Regime for this stress run.",
    )
    parser.add_argument(
        "--seed-snapshots",
        action="store_true",
        help="Seed default market snapshots before simulation.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero unless exit intent validates and illiquid panic sell is impact-vetoed.",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON output.")
    return parser.parse_args()


def _build_exit_intent(*, run_id: str, now_utc: dt.datetime) -> AllocationIntent:
    intent_id = f"{run_id}-nvda-sell-{uuid.uuid4().hex[:8]}"
    return AllocationIntent(
        intent_id=intent_id,
        run_id=run_id,
        lane=Lane.MOMENTUM,
        symbol="NVDA",
        asset_id="NVDA",
        asset_class_id=AssetClassId.LISTED_EQUITY,
        valuation_methodology=ValuationMethodology.MARK_TO_MARKET,
        execution_mode=ExecutionMode.LIVE,
        side="SELL",
        target_notional_usd=5_000_000.0,  # 15% -> 10% NAV group reduction in crisis
        correlation_group_tag="SEMIS",
        funding_source_status=FundingSourceStatus.SETTLED_CASH,
        funding_available_at_utc=None,
        funding_reservation_id=f"reserve-{intent_id}",
        snapshot_id=f"snap-{run_id}",
        snapshot_hash_canonical="alpha-day6-canonical",
        snapshot_hash_raw="alpha-day6-raw",
        max_slippage_bps=150.0,
        created_at_utc=now_utc,
        expires_at_utc=now_utc + dt.timedelta(hours=2),
        status=IntentStatus.PROPOSED,
        idempotency_key=f"idem-{intent_id}",
    )


def _build_panic_sell_intent(*, run_id: str, now_utc: dt.datetime) -> AllocationIntent:
    intent_id = f"{run_id}-illq-sell-{uuid.uuid4().hex[:8]}"
    return AllocationIntent(
        intent_id=intent_id,
        run_id=run_id,
        lane=Lane.MOMENTUM,
        symbol="ILLQ",
        asset_id="ILLQ",
        asset_class_id=AssetClassId.LISTED_EQUITY,
        valuation_methodology=ValuationMethodology.MARK_TO_MARKET,
        execution_mode=ExecutionMode.LIVE,
        side="SELL",
        target_notional_usd=8_000_000.0,  # intentionally illiquid for impact veto
        correlation_group_tag="MICRO_CAP",
        funding_source_status=FundingSourceStatus.SETTLED_CASH,
        funding_available_at_utc=None,
        funding_reservation_id=f"reserve-{intent_id}",
        snapshot_id=f"snap-{run_id}",
        snapshot_hash_canonical="alpha-day6-canonical",
        snapshot_hash_raw="alpha-day6-raw",
        max_slippage_bps=150.0,
        created_at_utc=now_utc,
        expires_at_utc=now_utc + dt.timedelta(hours=2),
        status=IntentStatus.PROPOSED,
        idempotency_key=f"idem-{intent_id}",
    )


def _build_portfolio() -> PortfolioSnapshot:
    return PortfolioSnapshot(
        symbols=["NVDA", "AVGO", "ILLQ", "XLE", "SPY"],
        weights=[0.15, 0.00, 0.03, 0.03, 0.20],
        covariance=[
            [0.030, 0.000, 0.000, 0.000, 0.000],
            [0.000, 0.030, 0.000, 0.000, 0.000],
            [0.000, 0.000, 0.040, 0.000, 0.000],
            [0.000, 0.000, 0.000, 0.030, 0.000],
            [0.000, 0.000, 0.000, 0.000, 0.030],
        ],
        group_tags={"NVDA": "SEMIS", "AVGO": "SEMIS", "ILLQ": "MICRO_CAP", "XLE": "ENERGY", "SPY": "INDEX"},
        nav_usd=100_000_000.0,
        margin_utilization=0.10,
        margin_cap=0.35,
    )


def _common_reliability_inputs() -> ReliabilityInputs:
    return ReliabilityInputs(
        e_raw_bps=35_000.0,  # keep liability gate non-binding for this stress purpose
        r_data=0.90,
        r_global=0.60,
        r_regime_raw=0.64,
        n_eff_regime=40.0,
    )


def _observations() -> list[DecisionObservation]:
    return [
        DecisionObservation(score=86.0, edge_bps=260.0, age_days=2.0, age_decisions=1.0),
        DecisionObservation(score=74.0, edge_bps=115.0, age_days=6.0, age_decisions=2.0),
        DecisionObservation(score=66.0, edge_bps=40.0, age_days=12.0, age_decisions=3.0),
    ]


def _profile() -> AssetLiabilityProfile:
    return AssetLiabilityProfile(
        asset_class_id=AssetClassId.LISTED_EQUITY.value,
        valuation_methodology=ValuationMethodology.MARK_TO_MARKET,
        liquidity_horizon_days=2,
        revaluation_interval_days=30,
        lockup_days=0,
    )


def _summary_row(intent: AllocationIntent, status: IntentStatus, reason_code: str, reason: str) -> dict[str, object]:
    return {
        "intent_id": intent.intent_id,
        "symbol": intent.symbol,
        "side": intent.side,
        "status": status.value,
        "reason_code": reason_code,
        "reason": reason,
        "target_notional_usd": float(intent.target_notional_usd),
        "group_tag": intent.correlation_group_tag,
    }


def main() -> None:
    args = _parse_args()
    now_utc = dt.datetime.now(dt.timezone.utc)
    run_id = f"{args.run_id}-{now_utc.strftime('%Y%m%d%H%M%S')}"
    db_path = Path(args.db_path)
    override_path = Path(args.override_path)

    repo = SQLiteAllocatorRepository(db_path)
    repo.initialize()
    if args.seed_snapshots:
        seed_market_snapshot_cache(db_path=db_path, as_of_utc=now_utc)

    regime = RegimeShock(str(args.regime).upper())
    write_regime_override(
        path=override_path,
        regime=regime,
        reason="alpha_protocol_day6_exit",
        source="operator",
        now=now_utc,
    )

    allocator = CapitalAllocator(repository=repo)
    portfolio = _build_portfolio()

    exit_intent = _build_exit_intent(run_id=run_id, now_utc=now_utc)
    repo.insert_intent(exit_intent)
    exit_status = allocator.evaluate_proposed_intent(
        intent=exit_intent,
        portfolio=portfolio,
        shock=regime,
        observations=_observations(),
        reliability_inputs=_common_reliability_inputs(),
        market_snapshot=MarketSnapshot(
            symbol="NVDA",
            snapshot_time_utc=now_utc,
            price=710.0,
            adv30_notional_usd=28_000_000_000.0,
            vol20d_bps=240.0,
            spread_bps=1.0,
            source_latency_ms=120,
        ),
        liability_profile=_profile(),
        tax_cost_bps=15.0,
        validation_price=710.0,
        price_source_latency_ms=120,
        now_utc=now_utc,
    )
    exit_row = repo.get_intent(exit_intent.intent_id)
    exit_reason_code = str(exit_row.reason_code if exit_row else "")
    exit_reason = str(exit_row.reason if exit_row else "")

    panic_intent = _build_panic_sell_intent(run_id=run_id, now_utc=now_utc)
    repo.insert_intent(panic_intent)
    panic_status = allocator.evaluate_proposed_intent(
        intent=panic_intent,
        portfolio=portfolio,
        shock=regime,
        observations=_observations(),
        reliability_inputs=_common_reliability_inputs(),
        market_snapshot=MarketSnapshot(
            symbol="ILLQ",
            snapshot_time_utc=now_utc,
            price=17.5,
            adv30_notional_usd=20_000_000.0,
            vol20d_bps=420.0,
            spread_bps=9.0,
            source_latency_ms=120,
        ),
        liability_profile=_profile(),
        tax_cost_bps=15.0,
        validation_price=17.5,
        price_source_latency_ms=120,
        now_utc=now_utc,
    )
    panic_row = repo.get_intent(panic_intent.intent_id)
    panic_reason_code = str(panic_row.reason_code if panic_row else "")
    panic_reason = str(panic_row.reason if panic_row else "")

    summary = {
        "run_id": run_id,
        "regime": regime.value,
        "checks": [
            _summary_row(exit_intent, exit_status, exit_reason_code, exit_reason),
            _summary_row(panic_intent, panic_status, panic_reason_code, panic_reason),
        ],
    }

    expected_ok = (
        exit_status == IntentStatus.VALIDATED
        and panic_status == IntentStatus.REJECTED_IMPACT_VETO
    )
    summary["strict_pass"] = bool(expected_ok)

    if args.strict and not expected_ok:
        if args.json:
            print(json.dumps(summary, indent=2, sort_keys=True))
        raise SystemExit(
            "Day-6 exit stress failed: expected exit VALIDATED and illiquid panic sell REJECTED_IMPACT_VETO."
        )

    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
        return

    print(
        "[alpha-day6] "
        f"run_id={run_id} regime={regime.value} "
        f"exit={exit_status.value} panic={panic_status.value}"
    )


if __name__ == "__main__":
    main()

