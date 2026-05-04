"""Capital Allocator v1 package exports."""

from .allocator import AllocationContextProvider, CapitalAllocator
from .contracts import (
    ADV_PARTICIPATION_MAX,
    GROUP_CAP_BY_REGIME,
    IMPACT_K_BY_LANE,
    LANE_PARAMS,
    MVC_VETO_THRESHOLD,
    SHOCK_MULTIPLIER,
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
from .gates import (
    CovarianceGate,
    FundingGate,
    GateResult,
    ImpactGate,
    ImpactGateResult,
    PriceSlipResult,
    enforce_price_slip,
)
from .liability_engine import (
    AssetLiabilityProfile,
    ConstantRegimePremiumProvider,
    ConstantRiskFreeRateProvider,
    LiabilityBreakdown,
    LiabilityConfig,
    LiabilityEngine,
    LiabilityInputs as LiabilityEvalInputs,
)
from .market_snapshot_seed import build_default_market_snapshots, seed_market_snapshot_cache
from .reporting import build_allocator_report_card
from .weighting import risk_parity_weights, score_to_weights
from .regime_override import read_regime_override, resolve_regime, write_regime_override
from .reliability import ReliabilityEngine
from .repository import SQLiteAllocatorRepository

__all__ = [
    "AllocationContextProvider",
    "AllocationIntent",
    "ADV_PARTICIPATION_MAX",
    "AssetClassId",
    "AssetLiabilityProfile",
    "CapitalAllocator",
    "ConstantRegimePremiumProvider",
    "ConstantRiskFreeRateProvider",
    "CovarianceGate",
    "DecisionObservation",
    "ExecutionMode",
    "FundingGate",
    "FundingSourceStatus",
    "GROUP_CAP_BY_REGIME",
    "GateResult",
    "IMPACT_K_BY_LANE",
    "ImpactGate",
    "ImpactGateResult",
    "IntentStatus",
    "LANE_PARAMS",
    "Lane",
    "LiabilityBreakdown",
    "LiabilityConfig",
    "LiabilityEngine",
    "LiabilityEvalInputs",
    "MarketSnapshot",
    "MVC_VETO_THRESHOLD",
    "PortfolioSnapshot",
    "PriceSlipResult",
    "RegimeShock",
    "read_regime_override",
    "build_default_market_snapshots",
    "build_allocator_report_card",
    "ReliabilityEngine",
    "ReliabilityInputs",
    "resolve_regime",
    "seed_market_snapshot_cache",
    "SHOCK_MULTIPLIER",
    "SQLiteAllocatorRepository",
    "ValuationMethodology",
    "write_regime_override",
    "enforce_price_slip",
    "risk_parity_weights",
    "score_to_weights",
]
