"""Graph package exports.

Keep package import light so schema-only imports do not initialize the full
trading graph.
"""

__all__ = [
    "TradingAgentsGraph",
    "ConditionalLogic",
    "GraphSetup",
    "Propagator",
    "SignalProcessor",
]


def __getattr__(name: str):
    if name == "TradingAgentsGraph":
        from .trading_graph import TradingAgentsGraph

        return TradingAgentsGraph
    if name == "ConditionalLogic":
        from .conditional_logic import ConditionalLogic

        return ConditionalLogic
    if name == "GraphSetup":
        from .setup import GraphSetup

        return GraphSetup
    if name == "Propagator":
        from .propagation import Propagator

        return Propagator
    if name == "SignalProcessor":
        from .signal_processing import SignalProcessor

        return SignalProcessor
    raise AttributeError(f"module 'tradingagents.graph' has no attribute {name!r}")
