# TradingAgents/graph/propagation.py

from typing import Any, Dict, List, Optional
from tradingagents.agents.utils.agent_states import (
    AgentState,
    InvestDebateState,
    RiskDebateState,
)


def format_dealflow_provenance(ctx: Optional[Dict[str, Any]]) -> str:
    """Build a human-readable provenance string from dealflow context.

    The output is appended to trade_lessons so all agents see how this
    ticker was surfaced by the deal flow pipeline.
    """
    if not ctx or not isinstance(ctx, dict):
        return ""

    lines = ["=== DEAL FLOW PROVENANCE ==="]

    # Core score
    score = ctx.get("deal_flow_score") or ctx.get("core_score")
    subscores = ctx.get("subscores", {}) or {}
    if score is not None:
        parts = [f"core_score {score}"]
        for key in ("momentum_score", "asymmetry_score"):
            val = subscores.get(key) or ctx.get(key)
            if val is not None:
                parts.append(f"{key} {val}")
        lines.append(f"Surfaced by deal flow: {', '.join(parts)}")

    # Top signals
    signal_keys = [
        "smart_money", "breakout_discovery", "sector_rotation",
        "social_momentum", "macro_catalyst", "cashtag_velocity",
        "insider_alpha",
    ]
    top_signals = []
    for key in signal_keys:
        val = subscores.get(key) or ctx.get(key)
        if val is not None and float(val) > 0:
            top_signals.append(f"{key} {val}")
    if top_signals:
        lines.append(f"Top signals: {', '.join(top_signals[:5])}")

    # Lane and source
    lane = ctx.get("lane") or ctx.get("research_playbook") or ""
    source = ctx.get("source") or ctx.get("trigger") or ""
    why_now = ctx.get("why_now") or ctx.get("catalyst") or ""
    meta_parts = []
    if lane:
        meta_parts.append(f"Lane: {lane}")
    if source:
        meta_parts.append(f"Source: {source}")
    if why_now:
        meta_parts.append(f"Why now: {why_now}")
    if meta_parts:
        lines.append(" | ".join(meta_parts))

    lines.append("=== END PROVENANCE ===")
    return "\n".join(lines)


class Propagator:
    """Handles state initialization and propagation through the graph."""

    def __init__(self, max_recur_limit=100):
        """Initialize with configuration parameters."""
        self.max_recur_limit = max_recur_limit

    def create_initial_state(
        self, company_name: str, trade_date: str
    ) -> Dict[str, Any]:
        """Create the initial state for the agent graph."""
        return {
            "messages": [("human", company_name)],
            "company_of_interest": company_name,
            "trade_date": str(trade_date),
            "investment_debate_state": InvestDebateState(
                {"history": "", "current_response": "", "count": 0}
            ),
            "risk_debate_state": RiskDebateState(
                {
                    "history": "",
                    "current_risky_response": "",
                    "current_safe_response": "",
                    "current_neutral_response": "",
                    "count": 0,
                }
            ),
            "market_report": "",
            "fundamentals_report": "",
            "sentiment_report": "",
            "news_report": "",
            "pretrade_risk_brief": "",
            "portfolio_snapshot": {},
            "market_regime": {},
            "hedge_signal": {},
            "hedge_decision": {},
            "fundamental_metrics": {},
            "sentiment_metrics": {},
            "macro_metrics": {},
            "momentum_metrics": {},
            "dealflow_context": {},
            "structured_verdict": {},
            "trade_lessons": "",
            "aeternus_score": {},
            "structured_trader_verdict": {},
            "portfolio_context": "",
            "drawdown_mode": False,
        }

    def get_graph_args(self) -> Dict[str, Any]:
        """Get arguments for the graph invocation."""
        return {
            "stream_mode": "values",
            "config": {"recursion_limit": self.max_recur_limit},
        }
