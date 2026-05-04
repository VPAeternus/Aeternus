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


class ManualMergeDecision(TypedDict):
    symbol: str
    action: Literal["INCLUDED", "REINFORCED", "REJECTED"]
    reason: str
    priority: int
    lane_preference: Literal["CORE", "MOMENTUM"]
    note: str
    lane: str
    selected_rank: Optional[int]


class DealFlowCandidate(TypedDict):
    symbol: str
    asset_class: str
    sector: str
    liquidity_score: float
    subscores: Dict[str, float]
    deal_flow_score: float
    active_families: int
    evidence_count: int
    freshness_hours: float
    status: Literal["ACTIVE", "LOW_DATA"]
    risk_tags: List[str]
    trend_tags: List[str]
    lane: Literal["CORE", "MOMENTUM"]
    upside_3m_score: float
    emergence_proxy_score: float
    narrative_ignition_score: float
    fundamentals_acceleration_score: float
    relative_strength_score: float
    lane_candidates: List[str]
    core_score: float
    momentum_score: float
    asymmetry_score: float
    source: str
    source_detail: str
    manual_note: str
    manual_priority: int
    reason: str


class DealFlowShortlist(TypedDict):
    run_id: str
    date: str
    trigger: Literal["daily", "event", "manual"]
    top_k: int
    candidates: List[DealFlowCandidate]
    event_triggered: bool
    event_reasons: List[str]
    manual_included_count: int
    manual_symbols: List[str]
    manual_merge_summary: Dict[str, int]


class ResearchQueueItem(TypedDict):
    queue_id: str
    symbol: str
    asset_class: str
    sector: str
    lane: Literal["CORE", "MOMENTUM"]
    upside_3m_score: float
    emergence_proxy_score: float
    narrative_ignition_score: float
    fundamentals_acceleration_score: float
    relative_strength_score: float
    lane_candidates: List[str]
    deal_flow_score: float
    momentum_score: float
    asymmetry_score: float
    subscores: Dict[str, float]
    thesis_tags: List[str]
    risk_tags: List[str]
    evidence: Dict[str, float]
    why_now: str
    source: Literal["AUTO", "MANUAL"]
    source_detail: str
    manual_note: str
    research_playbook: Literal[
        "MOMENTUM_BREAKOUT",

        "HYBRID_COMPOUNDER",
    ]
    triage_score: float
    selected_for_deep: bool


class ResearchQueue(TypedDict):
    run_id: str
    date: str
    canonical_sector_map: Dict[str, str]
    items: List[ResearchQueueItem]
    deep_k: int
    selected_queue_ids: List[str]
    source_artifact: str


class EventTriggerResult(TypedDict):
    triggered: bool
    reasons: List[str]
    metrics: Dict[str, Optional[float]]
