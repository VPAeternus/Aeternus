"""Typed contracts for the Deal Flow Intelligence pipeline."""

from typing import Dict, List, Literal, Optional, TypedDict


class UniverseRow(TypedDict):
    symbol: str
    asset_class: Literal["Equity", "ETF", "CommodityProxy"]
    sector: str
    liquidity_score: float
    aliases: List[str]


class DealFlowSignal(TypedDict):
    symbol: str
    signal_family: Literal[
        "social_momentum",
        "news_catalyst",
        "macro_regime_fit",
        "smart_money",
        "price_momentum",
        "fundamental_factor_shadow",
        "breakout_discovery",
        "sector_rotation",
        "insider_cluster",
        "emergence",
    ]
    raw_score: float
    z_score: float
    direction: Literal["BULLISH", "BEARISH", "NEUTRAL"]
    evidence_count: int
    freshness_hours: float
    source_status: Literal["OK", "NO_DATA", "ERROR", "NOT_CONFIGURED"]
    source_name: str


class ManualContextSnapshot(TypedDict, total=False):
    akg_found: bool
    display_name: Optional[str]
    sector: Optional[str]
    asset_class: Optional[str]
    aeternus_score: Optional[float]
    last_scored_date: Optional[str]


class ManualIdea(TypedDict):
    symbol: str
    created_at: str
    active: bool
    context_snapshot: ManualContextSnapshot


class ManualWatchlist(TypedDict):
    updated_at: str
    items: List[ManualIdea]


class EventTriggerResult(TypedDict):
    triggered: bool
    reasons: List[str]
    metrics: Dict[str, Optional[float]]
