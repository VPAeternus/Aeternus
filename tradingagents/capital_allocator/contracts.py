"""Core contracts and constants for Capital Allocator v1."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional


class Lane(str, Enum):
    """Allocation lane classification."""

    CORE = "CORE"
    MOMENTUM = "MOMENTUM"
    HEDGE = "HEDGE"


class AssetClassId(str, Enum):
    """High-level asset class classification for asset-agnostic allocator intents."""

    LISTED_EQUITY = "LISTED_EQUITY"
    ETF = "ETF"
    CRYPTO = "CRYPTO"
    PRIVATE_EQUITY = "PRIVATE_EQUITY"
    PRIVATE_CREDIT = "PRIVATE_CREDIT"
    COMMODITY = "COMMODITY"
    CASH_EQUIVALENT = "CASH_EQUIVALENT"
    OTHER = "OTHER"


class ValuationMethodology(str, Enum):
    """Valuation methodology for asset/intent accounting and shadow-mode review."""

    MARK_TO_MARKET = "MARK_TO_MARKET"
    MARK_TO_MODEL = "MARK_TO_MODEL"
    LAST_ROUND = "LAST_ROUND"
    APPRAISAL = "APPRAISAL"
    MANUAL = "MANUAL"


class ExecutionMode(str, Enum):
    """Execution mode for allocator intent lifecycle."""

    LIVE = "LIVE"
    SHADOW = "SHADOW"


class RegimeShock(str, Enum):
    """Regime severity buckets used for uncertainty scaling."""

    NORMAL = "NORMAL"
    STRESS = "STRESS"
    SHOCK = "SHOCK"
    CRISIS = "CRISIS"


class FundingSourceStatus(str, Enum):
    """Funding readiness state for each intent."""

    SETTLED_CASH = "SETTLED_CASH"
    MARGIN_UTILIZED = "MARGIN_UTILIZED"
    PENDING_SALE_PROCEEDS = "PENDING_SALE_PROCEEDS"
    UNFUNDED = "UNFUNDED"


class IntentStatus(str, Enum):
    """Intent lifecycle states for idempotent outbox processing."""

    PROPOSED = "PROPOSED"
    VALIDATED = "VALIDATED"
    VALIDATED_WAIT_FUNDING = "VALIDATED_WAIT_FUNDING"
    SUBMITTED = "SUBMITTED"
    FILLED = "FILLED"
    EXPIRED_INTENT = "EXPIRED_INTENT"
    EXPIRED_FUNDING_WINDOW = "EXPIRED_FUNDING_WINDOW"
    REJECTED_COVARIANCE_VETO = "REJECTED_COVARIANCE_VETO"
    REJECTED_PRICE_SLIP = "REJECTED_PRICE_SLIP"
    REJECTED_IMPACT_VETO = "REJECTED_IMPACT_VETO"
    REJECTED_FUNDING = "REJECTED_FUNDING"
    REJECTED_LIABILITY_HURDLE = "REJECTED_LIABILITY_HURDLE"
    REJECTED_COVARIANCE_UNMODELED_SYMBOL = "REJECTED_COVARIANCE_UNMODELED_SYMBOL"


@dataclass(frozen=True)
class LaneParams:
    """Lane-specific reliability and thesis timing controls."""

    h_days: float
    h_decisions: float
    ttt_soft_days: int
    ttt_hard_days: int
    s_base: float
    k_shock: float


LANE_PARAMS: Dict[Lane, LaneParams] = {
    Lane.CORE: LaneParams(504.0, 12.0, 180, 360, 12.0, 0.8),
    Lane.MOMENTUM: LaneParams(63.0, 20.0, 10, 20, 8.0, 1.6),
    Lane.HEDGE: LaneParams(21.0, 15.0, 2, 5, 10.0, 0.4),
}


SHOCK_MULTIPLIER: Dict[RegimeShock, float] = {
    RegimeShock.NORMAL: 1.0,
    RegimeShock.STRESS: 1.3,
    RegimeShock.SHOCK: 1.7,
    RegimeShock.CRISIS: 2.2,
}


GROUP_CAP_BY_REGIME: Dict[RegimeShock, float] = {
    RegimeShock.NORMAL: 0.25,
    RegimeShock.STRESS: 0.20,
    RegimeShock.SHOCK: 0.15,
    RegimeShock.CRISIS: 0.10,
}


MVC_VETO_THRESHOLD: float = 0.35
ADV_PARTICIPATION_MAX: float = 0.01


IMPACT_K_BY_LANE: Dict[Lane, float] = {
    Lane.CORE: 0.15,
    Lane.MOMENTUM: 0.35,
    Lane.HEDGE: 0.20,
}


@dataclass
class DecisionObservation:
    """Observed realized outcome used to calibrate reliability."""

    score: float
    edge_bps: float
    age_days: float
    age_decisions: float


@dataclass
class ReliabilityInputs:
    """Runtime inputs needed to compute adjusted expected return."""

    e_raw_bps: float
    r_data: float
    r_global: float
    r_regime_raw: float
    n_eff_regime: float


@dataclass
class AllocationIntent:
    """Allocator intent record persisted in SQLite outbox."""

    intent_id: str
    run_id: str
    lane: Lane
    symbol: str
    asset_id: str
    asset_class_id: AssetClassId
    valuation_methodology: ValuationMethodology
    execution_mode: ExecutionMode
    side: str
    target_notional_usd: float
    correlation_group_tag: str
    funding_source_status: FundingSourceStatus
    funding_available_at_utc: Optional[dt.datetime]
    funding_reservation_id: Optional[str]
    snapshot_id: str
    snapshot_hash_canonical: str
    max_slippage_bps: float
    created_at_utc: dt.datetime
    expires_at_utc: dt.datetime
    snapshot_hash_raw: str = ""
    last_valuation_at_utc: Optional[dt.datetime] = None
    status: IntentStatus = IntentStatus.PROPOSED
    idempotency_key: str = ""
    expected_edge_bps: float = 0.0
    adjusted_edge_bps: float = 0.0
    reason_code: str = ""
    reason: str = ""


@dataclass
class PortfolioSnapshot:
    """Reduced portfolio state for concentration and covariance gating."""

    symbols: list[str]
    weights: list[float]
    covariance: list[list[float]]
    group_tags: Dict[str, str]
    nav_usd: float
    margin_utilization: float = 0.0
    margin_cap: float = 0.35


@dataclass
class MarketSnapshot:
    """Cached market data row used by allocator gates (no per-intent external IO)."""

    symbol: str
    snapshot_time_utc: dt.datetime
    price: float
    adv30_notional_usd: Optional[float]
    vol20d_bps: Optional[float]
    spread_bps: float
    source_latency_ms: int = 0
