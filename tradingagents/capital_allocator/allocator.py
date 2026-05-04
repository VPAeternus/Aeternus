"""Capital Allocator v1 orchestration service."""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from typing import Callable

from .contracts import (
    AllocationIntent,
    DecisionObservation,
    ExecutionMode,
    IntentStatus,
    MarketSnapshot,
    PortfolioSnapshot,
    RegimeShock,
    ReliabilityInputs,
)
from .gates import CovarianceGate, FundingGate, ImpactGate, enforce_price_slip
from .liability_engine import AssetLiabilityProfile, LiabilityEngine, LiabilityInputs as LiabilityEvalInputs
from .reliability import ReliabilityEngine
from .repository import SQLiteAllocatorRepository

logger = logging.getLogger(__name__)


@dataclass
class AllocationContextProvider:
    """Runtime providers for heartbeat evaluation."""

    portfolio_provider: Callable[[AllocationIntent], PortfolioSnapshot]
    shock_provider: Callable[[AllocationIntent], RegimeShock]
    lane_history_provider: Callable[[AllocationIntent], list[DecisionObservation]]
    reliability_inputs_provider: Callable[[AllocationIntent], ReliabilityInputs]
    market_snapshot_provider: Callable[[AllocationIntent], MarketSnapshot]
    liability_profile_provider: Callable[[AllocationIntent], AssetLiabilityProfile]
    tax_cost_bps_provider: Callable[[AllocationIntent], float]


class CapitalAllocator:
    """Deterministic allocator applying reliability math and sovereign risk gates."""

    def __init__(
        self,
        *,
        repository: SQLiteAllocatorRepository,
        reliability_engine: ReliabilityEngine | None = None,
        covariance_gate: CovarianceGate | None = None,
        impact_gate: ImpactGate | None = None,
        funding_gate: FundingGate | None = None,
        liability_engine: LiabilityEngine | None = None,
        max_price_latency_ms: float = 2000.0,
    ):
        self.repository = repository
        self.reliability_engine = reliability_engine or ReliabilityEngine()
        self.covariance_gate = covariance_gate or CovarianceGate()
        self.impact_gate = impact_gate or ImpactGate()
        self.funding_gate = funding_gate or FundingGate()
        self.liability_engine = liability_engine or LiabilityEngine()
        self.max_price_latency_ms = float(max_price_latency_ms)

    def evaluate_proposed_intent(
        self,
        *,
        intent: AllocationIntent,
        portfolio: PortfolioSnapshot,
        shock: RegimeShock,
        observations: list[DecisionObservation],
        reliability_inputs: ReliabilityInputs,
        market_snapshot: MarketSnapshot,
        liability_profile: AssetLiabilityProfile,
        tax_cost_bps: float,
        validation_price: float,
        price_source_latency_ms: int,
        now_utc: dt.datetime,
    ) -> IntentStatus:
        # Reliability math is always computed and persisted for auditability.
        lane_reliability, _n_eff = self.reliability_engine.lane_family_reliability(
            intent.lane,
            shock,
            observations,
        )
        regime_reliability = self.reliability_engine.regime_reliability(
            reliability_inputs.r_global,
            reliability_inputs.r_regime_raw,
            reliability_inputs.n_eff_regime,
        )
        adjusted_edge_bps = self.reliability_engine.expected_adjusted_return_bps(
            reliability_inputs.e_raw_bps,
            lane_reliability,
            regime_reliability,
            reliability_inputs.r_data,
        )
        self.repository.update_expectations(
            intent.intent_id,
            expected_edge_bps=float(reliability_inputs.e_raw_bps),
            adjusted_edge_bps=float(adjusted_edge_bps),
        )

        impact_result = self.impact_gate.evaluate(intent=intent, market_snapshot=market_snapshot)
        if not impact_result.allowed:
            self.repository.update_status(
                intent.intent_id,
                status=IntentStatus.REJECTED_IMPACT_VETO,
                reason_code=impact_result.code,
                reason=impact_result.message,
            )
            self.repository.save_terminal_receipt(
                intent_id=intent.intent_id,
                terminal_status=IntentStatus.REJECTED_IMPACT_VETO,
                reason_code=impact_result.code,
                reason=impact_result.message,
                decided_at_utc=now_utc,
                price_at_validation=validation_price,
                price_source_latency_ms=int(price_source_latency_ms),
            )
            logger.warning(
                "Intent rejected IMPACT_VETO: intent_id=%s symbol=%s reason=%s",
                intent.intent_id,
                getattr(intent, "symbol", ""),
                impact_result.message,
            )
            return IntentStatus.REJECTED_IMPACT_VETO

        last_valuation = (
            intent.last_valuation_at_utc if intent.execution_mode == ExecutionMode.SHADOW else now_utc
        )
        liability_inputs = LiabilityEvalInputs(
            as_of_utc=now_utc,
            lane=intent.lane,
            regime=shock,
            notional_usd=float(intent.target_notional_usd),
            nav_usd=float(portfolio.nav_usd),
            adv30_notional_usd=market_snapshot.adv30_notional_usd,
            vol20d_bps=market_snapshot.vol20d_bps,
            spread_floor_bps=float(market_snapshot.spread_bps),
            tax_cost_bps=float(tax_cost_bps),
            expected_edge_bps=float(adjusted_edge_bps),
            last_valuation_at_utc=last_valuation,
        )
        liability = self.liability_engine.evaluate(
            profile=liability_profile,
            inputs=liability_inputs,
        )
        if liability.net_edge_bps <= 0.0:
            reason = (
                f"Net edge below hurdle ({liability.net_edge_bps:.2f}bps <= 0). "
                f"hurdle={liability.hurdle_bps:.2f}, impact={liability.impact_bps:.2f}, "
                f"tax={liability.tax_cost_bps:.2f}, stale={liability.stale_haircut_bps:.2f}."
            )
            self.repository.update_status(
                intent.intent_id,
                status=IntentStatus.REJECTED_LIABILITY_HURDLE,
                reason_code=IntentStatus.REJECTED_LIABILITY_HURDLE.value,
                reason=reason,
            )
            self.repository.save_terminal_receipt(
                intent_id=intent.intent_id,
                terminal_status=IntentStatus.REJECTED_LIABILITY_HURDLE,
                reason_code=IntentStatus.REJECTED_LIABILITY_HURDLE.value,
                reason=reason,
                decided_at_utc=now_utc,
                price_at_validation=validation_price,
                price_source_latency_ms=int(price_source_latency_ms),
            )
            logger.warning(
                "Intent rejected LIABILITY_HURDLE: intent_id=%s symbol=%s net_edge_bps=%.2f",
                intent.intent_id,
                getattr(intent, "symbol", ""),
                liability.net_edge_bps,
            )
            return IntentStatus.REJECTED_LIABILITY_HURDLE

        # Latency check at validation time.
        slip_probe = enforce_price_slip(
            snapshot_price=validation_price,
            execution_price=validation_price,
            price_source_latency_ms=float(price_source_latency_ms),
            max_slippage_bps=float(intent.max_slippage_bps),
            max_latency_ms=self.max_price_latency_ms,
        )
        if not slip_probe.allowed:
            self.repository.update_status(
                intent.intent_id,
                status=IntentStatus.REJECTED_PRICE_SLIP,
                reason_code=slip_probe.code,
                reason="Validation price source latency/slippage guard rejected.",
            )
            self.repository.save_terminal_receipt(
                intent_id=intent.intent_id,
                terminal_status=IntentStatus.REJECTED_PRICE_SLIP,
                reason_code=slip_probe.code,
                reason="Validation price source latency/slippage guard rejected.",
                decided_at_utc=now_utc,
                price_at_validation=validation_price,
                price_source_latency_ms=int(price_source_latency_ms),
            )
            return IntentStatus.REJECTED_PRICE_SLIP

        cov_result = self.covariance_gate.evaluate(intent, portfolio, shock)
        if not cov_result.allowed:
            status = IntentStatus(cov_result.code)
            self.repository.update_status(
                intent.intent_id,
                status=status,
                reason_code=cov_result.code,
                reason=cov_result.message,
            )
            self.repository.save_terminal_receipt(
                intent_id=intent.intent_id,
                terminal_status=status,
                reason_code=cov_result.code,
                reason=cov_result.message,
                decided_at_utc=now_utc,
                price_at_validation=validation_price,
                price_source_latency_ms=int(price_source_latency_ms),
            )
            return status

        funding_status, funding_code = self.funding_gate.evaluate(
            intent,
            now_utc=now_utc,
            margin_utilization_post=float(portfolio.margin_utilization),
            margin_cap=float(portfolio.margin_cap),
        )
        self.repository.update_status(
            intent.intent_id,
            status=funding_status,
            reason_code=funding_code,
            reason="",
        )

        if funding_status == IntentStatus.VALIDATED:
            self.repository.save_validation(
                intent_id=intent.intent_id,
                validated_at_utc=now_utc,
                max_slippage_bps=float(intent.max_slippage_bps),
                validation_price=float(validation_price),
                price_source_latency_ms=int(price_source_latency_ms),
            )
            self.repository.update_high_water_mark(float(portfolio.nav_usd))
            logger.info(
                "Intent VALIDATED: intent_id=%s symbol=%s notional_usd=%.2f adjusted_edge_bps=%.2f",
                intent.intent_id,
                getattr(intent, "symbol", ""),
                float(intent.target_notional_usd),
                float(adjusted_edge_bps),
            )
            return IntentStatus.VALIDATED

        if funding_status in {
            IntentStatus.REJECTED_FUNDING,
            IntentStatus.EXPIRED_INTENT,
            IntentStatus.EXPIRED_FUNDING_WINDOW,
        }:
            self.repository.save_terminal_receipt(
                intent_id=intent.intent_id,
                terminal_status=funding_status,
                reason_code=funding_code,
                reason="",
                decided_at_utc=now_utc,
                price_at_validation=validation_price,
                price_source_latency_ms=int(price_source_latency_ms),
            )
        return funding_status

    def heartbeat_validate(
        self,
        *,
        provider: AllocationContextProvider,
        now_utc: dt.datetime,
        limit: int = 500,
    ) -> list[tuple[str, IntentStatus]]:
        outcomes: list[tuple[str, IntentStatus]] = []
        intents = self.repository.fetch_proposed(now_utc=now_utc, limit=limit)
        for intent in intents:
            portfolio = provider.portfolio_provider(intent)
            shock = provider.shock_provider(intent)
            history = provider.lane_history_provider(intent)
            inputs = provider.reliability_inputs_provider(intent)
            market_snapshot = provider.market_snapshot_provider(intent)
            liability_profile = provider.liability_profile_provider(intent)
            tax_cost_bps = float(provider.tax_cost_bps_provider(intent))
            validation_price = float(market_snapshot.price)
            latency_ms = int(market_snapshot.source_latency_ms)
            status = self.evaluate_proposed_intent(
                intent=intent,
                portfolio=portfolio,
                shock=shock,
                observations=history,
                reliability_inputs=inputs,
                market_snapshot=market_snapshot,
                liability_profile=liability_profile,
                tax_cost_bps=tax_cost_bps,
                validation_price=float(validation_price),
                price_source_latency_ms=int(latency_ms),
                now_utc=now_utc,
            )
            outcomes.append((intent.intent_id, status))
        return outcomes
