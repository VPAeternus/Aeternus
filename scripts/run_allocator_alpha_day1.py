#!/usr/bin/env python3
"""Run deterministic Day-1 allocator alpha simulation and print audit summary."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import uuid
from pathlib import Path
from typing import Any

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
from tradingagents.capital_allocator.liability_engine import AssetLiabilityProfile
from tradingagents.capital_allocator.market_snapshot_seed import seed_market_snapshot_cache
from tradingagents.capital_allocator.regime_override import resolve_regime
from tradingagents.capital_allocator.repository import SQLiteAllocatorRepository
from tradingagents.default_config import DEFAULT_CONFIG


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Day-1 allocator alpha simulation.")
    parser.add_argument(
        "--db-path",
        default=str(DEFAULT_CONFIG.get("operator_gateway_allocator_db_path", "eval_results/control/capital_allocator.db")),
        help="Allocator SQLite DB path.",
    )
    parser.add_argument(
        "--override-path",
        default="eval_results/control/allocator_regime_override.json",
        help="Regime override artifact path.",
    )
    parser.add_argument(
        "--run-id",
        default="alpha-day1",
        help="Simulation run id prefix.",
    )
    parser.add_argument(
        "--seed-snapshots",
        action="store_true",
        help="Seed default market snapshots before simulation.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON summary.")
    return parser.parse_args()


def _build_intents(run_id: str, now: dt.datetime) -> list[AllocationIntent]:
    hour = now.replace(minute=0, second=0, microsecond=0)

    def _intent(
        *,
        lane: Lane,
        symbol: str,
        side: str,
        notional: float,
        group: str,
        funding: FundingSourceStatus,
        asset_class: AssetClassId = AssetClassId.LISTED_EQUITY,
        execution_mode: ExecutionMode = ExecutionMode.LIVE,
        valuation: ValuationMethodology = ValuationMethodology.MARK_TO_MARKET,
        funding_eta_minutes: int | None = None,
    ) -> AllocationIntent:
        intent_id = f"{run_id}-{symbol.lower()}-{uuid.uuid4().hex[:8]}"
        funding_available = None
        if funding_eta_minutes is not None:
            funding_available = now + dt.timedelta(minutes=funding_eta_minutes)
        return AllocationIntent(
            intent_id=intent_id,
            run_id=run_id,
            lane=lane,
            symbol=symbol,
            asset_id=symbol,
            asset_class_id=asset_class,
            valuation_methodology=valuation,
            execution_mode=execution_mode,
            side=side,
            target_notional_usd=notional,
            correlation_group_tag=group,
            funding_source_status=funding,
            funding_available_at_utc=funding_available,
            funding_reservation_id=f"reserve-{intent_id}",
            snapshot_id=f"snap-{run_id}",
            snapshot_hash_canonical="alpha-day1-canonical",
            snapshot_hash_raw="alpha-day1-raw",
            max_slippage_bps=150.0,
            created_at_utc=hour,
            expires_at_utc=hour + dt.timedelta(hours=4),
            idempotency_key=f"idem-{intent_id}",
            status=IntentStatus.PROPOSED,
            last_valuation_at_utc=(
                now - dt.timedelta(days=120)
                if execution_mode == ExecutionMode.SHADOW
                else now
            ),
        )

    return [
        _intent(lane=Lane.CORE, symbol="SPY", side="BUY", notional=220_000.0, group="INDEX", funding=FundingSourceStatus.SETTLED_CASH),
        _intent(lane=Lane.CORE, symbol="AAPL", side="BUY", notional=180_000.0, group="MEGA_CAP", funding=FundingSourceStatus.SETTLED_CASH),
        # Stress-vector crossover probe: expected to pass NORMAL and fail CRISIS via liability hurdle.
        _intent(lane=Lane.CORE, symbol="QQQ", side="BUY", notional=10_000.0, group="CROSSOVER_PROBE", funding=FundingSourceStatus.SETTLED_CASH),
        _intent(lane=Lane.MOMENTUM, symbol="NVDA", side="BUY", notional=420_000.0, group="SEMIS", funding=FundingSourceStatus.SETTLED_CASH),
        _intent(lane=Lane.MOMENTUM, symbol="REMX", side="BUY", notional=1_200_000.0, group="RARE_EARTHS", funding=FundingSourceStatus.SETTLED_CASH),
        _intent(lane=Lane.MOMENTUM, symbol="LIT", side="BUY", notional=900_000.0, group="BATTERY", funding=FundingSourceStatus.SETTLED_CASH),
        _intent(lane=Lane.HEDGE, symbol="XLE", side="BUY", notional=150_000.0, group="ENERGY", funding=FundingSourceStatus.PENDING_SALE_PROCEEDS, funding_eta_minutes=90),
        _intent(
            lane=Lane.CORE,
            symbol="PEV1",
            side="BUY",
            notional=350_000.0,
            group="PRIVATE_VENTURE",
            funding=FundingSourceStatus.SETTLED_CASH,
            asset_class=AssetClassId.PRIVATE_EQUITY,
            execution_mode=ExecutionMode.SHADOW,
            valuation=ValuationMethodology.MARK_TO_MODEL,
        ),
        _intent(
            lane=Lane.MOMENTUM,
            symbol="DARK1",
            side="BUY",
            notional=200_000.0,
            group="UNKNOWN",
            funding=FundingSourceStatus.SETTLED_CASH,
        ),
    ]


def _lane_history(intent: AllocationIntent) -> list[DecisionObservation]:
    if intent.lane == Lane.CORE:
        return [
            DecisionObservation(score=71.0, edge_bps=85.0, age_days=5.0, age_decisions=1.0),
            DecisionObservation(score=62.0, edge_bps=45.0, age_days=14.0, age_decisions=2.0),
            DecisionObservation(score=58.0, edge_bps=10.0, age_days=21.0, age_decisions=3.0),
        ]
    if intent.lane == Lane.MOMENTUM:
        return [
            DecisionObservation(score=83.0, edge_bps=170.0, age_days=2.0, age_decisions=1.0),
            DecisionObservation(score=72.0, edge_bps=55.0, age_days=6.0, age_decisions=2.0),
            DecisionObservation(score=44.0, edge_bps=-25.0, age_days=10.0, age_decisions=3.0),
        ]
    return [
        DecisionObservation(score=68.0, edge_bps=40.0, age_days=2.0, age_decisions=1.0),
        DecisionObservation(score=64.0, edge_bps=32.0, age_days=6.0, age_decisions=2.0),
        DecisionObservation(score=55.0, edge_bps=5.0, age_days=9.0, age_decisions=3.0),
    ]


def _reliability_inputs(intent: AllocationIntent) -> ReliabilityInputs:
    symbol_raw = {
        "SPY": 9_000.0,
        "AAPL": 8_500.0,
        "QQQ": 4_000.0,
        "NVDA": 8_200.0,
        "XLE": 8_500.0,
        "REMX": 700.0,
        "LIT": 650.0,
        "DARK1": 500.0,
        "PEV1": 1_200.0,
    }
    lane_fallback = {
        Lane.CORE: 2_200.0,
        Lane.MOMENTUM: 2_400.0,
        Lane.HEDGE: 2_000.0,
    }
    raw = float(symbol_raw.get(intent.symbol, lane_fallback[intent.lane]))
    return ReliabilityInputs(
        e_raw_bps=float(raw),
        r_data=0.88,
        r_global=0.57,
        r_regime_raw=0.62,
        n_eff_regime=32.0,
    )


def _build_portfolio(intents: list[AllocationIntent]) -> PortfolioSnapshot:
    symbols = sorted({intent.symbol for intent in intents})
    size = len(symbols)
    weights = [0.03 for _ in symbols]
    covariance = []
    for i in range(size):
        row = []
        for j in range(size):
            if i == j:
                row.append(0.035)
            else:
                row.append(0.006)
        covariance.append(row)
    groups = {intent.symbol: intent.correlation_group_tag for intent in intents}
    return PortfolioSnapshot(
        symbols=symbols,
        weights=weights,
        covariance=covariance,
        group_tags=groups,
        nav_usd=100_000_000.0,
        margin_utilization=0.12,
        margin_cap=0.35,
    )


def _liability_profile(intent: AllocationIntent) -> AssetLiabilityProfile:
    if intent.execution_mode == ExecutionMode.SHADOW and intent.asset_class_id == AssetClassId.PRIVATE_EQUITY:
        return AssetLiabilityProfile(
            asset_class_id=intent.asset_class_id.value,
            valuation_methodology=intent.valuation_methodology,
            liquidity_horizon_days=720,
            revaluation_interval_days=45,
            lockup_days=540,
        )
    return AssetLiabilityProfile(
        asset_class_id=intent.asset_class_id.value,
        valuation_methodology=intent.valuation_methodology,
        liquidity_horizon_days=2,
        revaluation_interval_days=30,
        lockup_days=0,
    )


def _market_snapshot(repo: SQLiteAllocatorRepository, intent: AllocationIntent, now: dt.datetime) -> MarketSnapshot:
    snap = repo.get_market_snapshot(intent.symbol)
    if snap is not None:
        return snap
    # Missing ADV path for dark symbols to validate hard veto behavior.
    return MarketSnapshot(
        symbol=intent.symbol,
        snapshot_time_utc=now,
        price=100.0,
        adv30_notional_usd=None,
        vol20d_bps=220.0,
        spread_bps=8.0,
        source_latency_ms=180,
    )


def _status_rows(repo: SQLiteAllocatorRepository, *, run_id: str) -> list[dict[str, Any]]:
    with repo.connection() as conn:
        rows = conn.execute(
            """
            SELECT lane, status, COUNT(*) AS count, AVG(target_notional_usd) AS avg_size
            FROM allocator_intents
            WHERE run_id = ?
            GROUP BY lane, status
            ORDER BY lane, status
            """
            ,
            (run_id,),
        ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "lane": str(row["lane"]),
                "status": str(row["status"]),
                "count": int(row["count"]),
                "avg_size": float(row["avg_size"] or 0.0),
            }
        )
    return out


def _symbol_rows(repo: SQLiteAllocatorRepository, *, run_id: str) -> list[dict[str, Any]]:
    with repo.connection() as conn:
        rows = conn.execute(
            """
            SELECT symbol, lane, status, reason_code, reason
            FROM allocator_intents
            WHERE run_id = ?
            ORDER BY symbol ASC
            """,
            (run_id,),
        ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "symbol": str(row["symbol"] or ""),
                "lane": str(row["lane"] or ""),
                "status": str(row["status"] or ""),
                "reason_code": str(row["reason_code"] or ""),
                "reason": str(row["reason"] or ""),
            }
        )
    return out


def main() -> None:
    args = _parse_args()
    now = dt.datetime.now(dt.timezone.utc)
    db_path = Path(args.db_path)
    run_id = f"{args.run_id}-{now.strftime('%Y%m%d%H%M%S')}"

    repo = SQLiteAllocatorRepository(db_path)
    repo.initialize()
    if args.seed_snapshots:
        seed_market_snapshot_cache(db_path=db_path, as_of_utc=now)

    intents = _build_intents(run_id=run_id, now=now)
    for intent in intents:
        repo.insert_intent(intent)

    portfolio = _build_portfolio(intents)
    active_regime = resolve_regime(path=Path(args.override_path), default=RegimeShock.NORMAL)
    allocator = CapitalAllocator(repository=repo)
    provider = AllocationContextProvider(
        portfolio_provider=lambda _intent: portfolio,
        shock_provider=lambda _intent: active_regime,
        lane_history_provider=_lane_history,
        reliability_inputs_provider=_reliability_inputs,
        market_snapshot_provider=lambda intent: _market_snapshot(repo, intent, now),
        liability_profile_provider=_liability_profile,
        tax_cost_bps_provider=lambda _intent: 15.0,
    )
    outcomes = allocator.heartbeat_validate(provider=provider, now_utc=now, limit=500)
    counts = _status_rows(repo, run_id=run_id)

    summary = {
        "run_id": run_id,
        "db_path": str(db_path),
        "active_regime": active_regime.value,
        "intent_count": len(intents),
        "evaluated_count": len(outcomes),
        "status_counts": counts,
        "symbol_statuses": _symbol_rows(repo, run_id=run_id),
    }
    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
        return

    print(
        "[alpha-day1] "
        f"run_id={run_id} "
        f"regime={active_regime.value} "
        f"intents={len(intents)} "
        f"evaluated={len(outcomes)}"
    )
    for row in counts:
        print(
            f"  lane={row['lane']:<8} status={row['status']:<32} "
            f"count={row['count']:<3} avg_size={row['avg_size']:.2f}"
        )


if __name__ == "__main__":
    main()
