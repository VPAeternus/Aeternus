"""Runtime model router — selects analyst LLM tier based on data quality and ticker.

When computation engines have sparse data (low coverage), the LLM must reason harder.
This module provides routing logic; wiring into the graph is a separate task.
"""

from typing import Any, Dict, Optional

# Major large-cap tickers — these have rich, well-structured data from all vendors.
# When data coverage is high for these, the quick (cheap) model suffices.
_LARGE_CAP_TICKERS: frozenset = frozenset({
    # Mega-caps
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "BRK-B",
    # Large financials
    "JPM", "V", "MA", "BAC", "GS", "WFC", "C", "BLK", "SPGI", "BK",
    # Large healthcare
    "UNH", "JNJ", "ABBV", "MRK", "PFE", "TMO", "ABT", "DHR", "AMGN", "GILD", "ISRG",
    # Large tech
    "AVGO", "ORCL", "CRM", "AMD", "CSCO", "QCOM", "TXN", "INTU", "ADBE", "NOW",
    "NFLX", "ACN", "IBM", "PANW", "LRCX", "MU", "ANET",
    # Large consumer/industrial
    "WMT", "PG", "KO", "PEP", "COST", "HD", "MCD", "NKE", "DIS",
    "CAT", "GE", "HON", "UPS", "RTX", "DE", "BA", "LIN",
    # Large energy
    "XOM", "CVX",
    # Major ETFs
    "SPY", "QQQ", "IWM", "DIA", "VTI", "IVV",
})

# Coverage threshold below which we use the deep (expensive) model.
# Matches epistemic._coverage_to_tier() LOW boundary and scorer MIN_ANCHOR_COVERAGE.
_LOW_COVERAGE_THRESHOLD = 0.4


def is_large_cap(ticker: str) -> bool:
    """Check if ticker is in the large-cap set. Case insensitive."""
    return ticker.upper().strip() in _LARGE_CAP_TICKERS


def select_analyst_tier(data_coverage: float, ticker: str = "") -> str:
    """Select analyst model tier based on data quality and ticker characteristics.

    Rules:
    - Low data coverage (< 0.4) → "deep" (LLM must reason harder with sparse data)
    - Non-large-cap ticker → "deep" (less analyst coverage, need deeper reasoning)
    - High coverage + large-cap → "quick" (rich data, standard analysis suffices)

    Returns: "deep" or "quick"
    """
    if data_coverage < _LOW_COVERAGE_THRESHOLD:
        return "deep"
    if ticker and not is_large_cap(ticker):
        return "deep"
    return "quick"


def get_llm_for_tier(tier: str, quick_llm: Any, deep_llm: Any) -> Any:
    """Return the appropriate LLM instance for the given tier.

    Args:
        tier: "deep" or "quick" (from select_analyst_tier)
        quick_llm: The fast/cheap LLM instance
        deep_llm: The deep/expensive LLM instance

    Returns: The selected LLM instance. Defaults to quick_llm for unknown tiers.
    """
    if tier == "deep":
        return deep_llm
    return quick_llm


def should_use_dynamic_routing(config: Dict[str, Any]) -> bool:
    """Check if dynamic analyst routing is enabled in config.

    Reads config["analyst_dynamic_routing"]. Defaults to False (opt-in).
    """
    return bool(config.get("analyst_dynamic_routing", False))
