#!/usr/bin/env python3
"""Run Day-5 concentration-wall stress simulation for allocator covariance veto."""

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
from tradingagents.default_config import DEFAULT_CONFIG


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Day-5 concentration wall simulation.")
    parser.add_argument(
        "--db-path",
        default="eval_results/control/capital_allocator_alpha_day5.db",
        help="Allocator SQLite DB path for Day-5 run.",
    )
    parser.add_argument(
        "--override-path",
        default="eval_results/control/allocator_regime_override.json",
        help="Regime override artifact path.",
    )
    parser.add_argument(
        "--run-id",
        default="alpha-day5",
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
        help="Exit non-zero unless status is REJECTED_COVARIANCE_VETO.",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON output.")
    return parser.parse_args()


def _build_intent(*, run_id: str, now_utc: dt.datetime) -> AllocationIntent:
    intent_id = f"{run_id}-avgo-{uuid.uuid4().hex[:8]}"
    return AllocationIntent(
        intent_id=intent_id,
        run_id=run_id,
        lane=Lane.MOMENTUM,
        symbol="AVGO",
        asset_id="AVGO",
        asset_class_id=AssetClassId.LISTED_EQUITY,
        valuation_methodology=ValuationMethodology.MARK_TO_MARKET,
        execution_mode=ExecutionMode.LIVE,
        side="BUY",
        target_notional_usd=2_000_000.0,
        correlation_group_tag="SEMIS",
        funding_source_status=FundingSourceStatus.SETTLED_CASH,
        funding_available_at_utc=None,
        funding_reservation_id=f"reserve-{intent_id}",
        snapshot_id=f"snap-{run_id}",
        snapshot_hash_canonical="alpha-day5-canonical",
        snapshot_hash_raw="alpha-day5-raw",
        max_slippage_bps=150.0,
        created_at_utc=now_utc,
        expires_at_utc=now_utc + dt.timedelta(hours=2),
        status=IntentStatus.PROPOSED,
        idempotency_key=f"idem-{intent_id}",
    )


def _build_portfolio() -> PortfolioSnapshot:
    # Crisis setup:
    # - Existing SEMIS exposure is already 9% NAV (NVDA)
    # - New AVGO intent adds 2% NAV
    # - Crisis cap for group is 10% => expected veto at 11%
    symbols = ["NVDA", "AVGO", "XLE", "SPY"]
    weights = [0.09, 0.00, 0.03, 0.20]
    covariance = [
        [0.030, 0.000, 0.000, 0.000],
        [0.000, 0.030, 0.000, 0.000],
        [0.000, 0.000, 0.030, 0.000],
        [0.000, 0.000, 0.000, 0.030],
    ]
    return PortfolioSnapshot(
        symbols=symbols,
        weights=weights,
        covariance=covariance,
        group_tags={"NVDA": "SEMIS", "AVGO": "SEMIS", "XLE": "ENERGY", "SPY": "INDEX"},
        nav_usd=100_000_000.0,
        margin_utilization=0.10,
        margin_cap=0.35,
    )


def _market_snapshot(now_utc: dt.datetime) -> MarketSnapshot:
    return MarketSnapshot(
        symbol="AVGO",
        snapshot_time_utc=now_utc,
        price=1_180.0,
        adv30_notional_usd=12_000_000_000.0,
        vol20d_bps=190.0,
        spread_bps=0.8,
        source_latency_ms=120,
    )


def _summary_payload(
    *,
    run_id: str,
    regime: RegimeShock,
    status: IntentStatus,
    reason_code: str,
    reason: str,
    group_weight_pre: float,
    intent_weight_delta: float,
    cap: float,
) -> dict[str, object]:
    return {
        "run_id": run_id,
        "regime": regime.value,
        "status": status.value,
        "reason_code": reason_code,
        "reason": reason,
        "group_weight_pre": group_weight_pre,
        "intent_weight_delta": intent_weight_delta,
        "group_weight_post": group_weight_pre + intent_weight_delta,
        "group_cap": cap,
        "expected_collision": (group_weight_pre + intent_weight_delta) > cap,
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
        reason="alpha_protocol_day5_concentration",
        source="operator",
        now=now_utc,
    )

    intent = _build_intent(run_id=run_id, now_utc=now_utc)
    repo.insert_intent(intent)
    portfolio = _build_portfolio()
    allocator = CapitalAllocator(repository=repo)

    status = allocator.evaluate_proposed_intent(
        intent=intent,
        portfolio=portfolio,
        shock=regime,
        observations=[
            DecisionObservation(score=84.0, edge_bps=210.0, age_days=2.0, age_decisions=1.0),
            DecisionObservation(score=73.0, edge_bps=95.0, age_days=6.0, age_decisions=2.0),
            DecisionObservation(score=62.0, edge_bps=30.0, age_days=12.0, age_decisions=3.0),
        ],
        reliability_inputs=ReliabilityInputs(
            e_raw_bps=30_000.0,  # intentionally high to bypass liability gate and isolate covariance behavior
            r_data=0.90,
            r_global=0.60,
            r_regime_raw=0.64,
            n_eff_regime=40.0,
        ),
        market_snapshot=_market_snapshot(now_utc),
        liability_profile=AssetLiabilityProfile(
            asset_class_id=AssetClassId.LISTED_EQUITY.value,
            valuation_methodology=ValuationMethodology.MARK_TO_MARKET,
            liquidity_horizon_days=2,
            revaluation_interval_days=30,
            lockup_days=0,
        ),
        tax_cost_bps=15.0,
        validation_price=1_180.0,
        price_source_latency_ms=120,
        now_utc=now_utc,
    )
    stored = repo.get_intent(intent.intent_id)
    reason_code = str(stored.reason_code if stored else "")
    reason = str(stored.reason if stored else "")

    summary = _summary_payload(
        run_id=run_id,
        regime=regime,
        status=status,
        reason_code=reason_code,
        reason=reason,
        group_weight_pre=0.09,
        intent_weight_delta=0.02,
        cap=0.10 if regime == RegimeShock.CRISIS else 0.25,
    )

    if args.strict and status != IntentStatus.REJECTED_COVARIANCE_VETO:
        if args.json:
            print(json.dumps(summary, indent=2, sort_keys=True))
        raise SystemExit("Day-5 concentration stress did not trigger REJECTED_COVARIANCE_VETO.")

    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
        return

    print(
        "[alpha-day5] "
        f"run_id={summary['run_id']} "
        f"regime={summary['regime']} "
        f"status={summary['status']} "
        f"group_post={summary['group_weight_post']:.4f} "
        f"cap={summary['group_cap']:.4f}"
    )
    if reason:
        print(f"  reason: {reason}")


if __name__ == "__main__":
    main()
