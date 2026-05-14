"""Agent package exports.

Exports are loaded only when requested so importing one small utility does not
pull in the full graph/trader stack.
"""

__all__ = [
    "FinancialSituationMemory",
    "AgentState",
    "create_msg_delete",
    "create_market_analyst",
    "create_news_analyst",
    "create_momentum_reviewer",
    "create_trader",
]


def __getattr__(name: str):
    if name == "FinancialSituationMemory":
        from .utils.memory import FinancialSituationMemory

        return FinancialSituationMemory
    if name == "AgentState":
        from .utils.agent_states import AgentState

        return AgentState
    if name == "create_msg_delete":
        from .utils.agent_utils import create_msg_delete

        return create_msg_delete
    if name == "create_market_analyst":
        from .analysts.market_analyst import create_market_analyst

        return create_market_analyst
    if name == "create_news_analyst":
        from .analysts.news_analyst import create_news_analyst

        return create_news_analyst
    if name == "create_momentum_reviewer":
        from .analysts.momentum_reviewer import create_momentum_reviewer

        return create_momentum_reviewer
    if name == "create_trader":
        from .trader.trader import create_trader

        return create_trader
    raise AttributeError(f"module 'tradingagents.agents' has no attribute {name!r}")
