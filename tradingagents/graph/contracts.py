"""Typed contracts for Aeternus portfolio risk and hedging flows."""

from typing import Literal, Optional, TypedDict


class PortfolioRiskSnapshot(TypedDict):
    timestamp: str
    gross_exposure_usd: float
    net_exposure_usd: float
    portfolio_beta_60d: float
    var_95_1d_pct_nav: float
    drawdown_20d_pct: float
    tech_concentration_pct: float
    current_hedge_pct: float


class MarketRegimeSnapshot(TypedDict):
    timestamp: str
    spy_close: float
    spy_sma20: float
    spy_sma200: float
    spy_sma200_5d_ago: float
    spy_deviation_pct: float
    vix_close: float


class HedgeSignal(TypedDict):
    base_hedge_pct: float
    s7_boost_pct: float
    bear_trigger_active: bool
    crash_trigger_active: bool
    target_hedge_pct_pre_hysteresis: float
    mode: Literal["BULL", "S7_STANDBY", "S7_HEDGE", "BEAR", "BEAR_S7_BOOST", "CRASH"]
    market_regime: str
    risk_metrics: dict


class HedgeDecision(TypedDict):
    final_target_hedge_pct: float
    instrument: Literal["SPY", "QQQ"]
    action: Literal["INCREASE_HEDGE", "DECREASE_HEDGE", "NO_CHANGE"]
    delta_hedge_pct: float
    delta_notional_usd: float
    reason: str
    status: Literal[
        "EXECUTED",
        "SKIPPED_HYSTERESIS",
        "DATA_INSUFFICIENT",
        "NO_POSITIONS",
    ]


class HedgeOrder(TypedDict):
    timestamp: str
    instrument: Literal["SPY", "QQQ"]
    action: Literal["INCREASE_HEDGE", "DECREASE_HEDGE"]
    delta_hedge_pct: float
    delta_notional_usd: float
    previous_hedge_pct: float
    target_hedge_pct: float
    mode: Literal["BULL", "S7_STANDBY", "S7_HEDGE", "BEAR", "BEAR_S7_BOOST", "CRASH"]
    reason: str


class KerberosSignal(TypedDict):
    timestamp: str
    vxx_close: float
    vix_close: float
    pct_b_2sd: float
    pct_b_1sd: float
    entry_triggered: bool
    exit_triggered: bool
    data_sufficient: bool
    bars_available: int


class KerberosDecision(TypedDict):
    action: Literal["OPEN_PUT", "CLOSE_PUT", "HOLD", "NO_SIGNAL"]
    status: Literal[
        "EXECUTED",
        "SKIPPED_COOLDOWN",
        "SKIPPED_POSITION_OPEN",
        "DATA_INSUFFICIENT",
        "NO_SIGNAL",
    ]
    reason: str
    put_strike: float
    put_premium: float
    put_dte: int
    put_iv: float
    vxx_spot: float


class KerberosOrder(TypedDict):
    timestamp: str
    action: Literal["OPEN_PUT", "CLOSE_PUT"]
    vxx_spot: float
    put_strike: float
    put_premium: float
    put_dte: int
    put_iv: float
    exit_vxx_spot: float
    exit_put_value: float
    pnl_per_contract: float
    return_on_premium_pct: float
    hold_days: int
    exit_reason: Literal["SIGNAL", "EXPIRY", ""]


class ExecutionOrderIntent(TypedDict):
    order_intent_id: str
    client_order_id: str
    idempotency_key: str
    symbol: str
    side: Literal["BUY", "SELL"]
    order_type: Literal["MARKET"]
    time_in_force: Literal["DAY"]
    execution_mode: Literal["paper"]
    target_weight: float
    target_notional_usd: float
    reference_price: float
    target_quantity: float
    aeternus_score: float
    confidence: int
    lane: str
    research_playbook: str
    dominant_signal_family: str
    queue_id: str
    rating_id: str


class ExecutionFill(TypedDict):
    execution_id: str
    broker_order_id: str
    executed_at: str
    plan_id: str
    date: str
    order_intent_id: str
    client_order_id: str
    idempotency_key: str
    symbol: str
    side: Literal["BUY", "SELL"]
    order_type: Literal["MARKET"]
    time_in_force: Literal["DAY"]
    execution_mode: Literal["paper"]
    filled_quantity: float
    filled_price: float
    filled_notional_usd: float
    signed_quantity: float
    queue_id: str
    rating_id: str
    lane: str
    research_playbook: str
    dominant_signal_family: str
    status: Literal["FILLED"]


class ExecutionPosition(TypedDict):
    symbol: str
    net_quantity: float
    avg_price: float
    market_value_usd: float
    direction: Literal["LONG", "SHORT"]
    rating_ids: list[str]
    lane: str
    research_playbook: str
    updated_at: str
