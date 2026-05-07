"""Portfolio Correlation Guard.

Computes pairwise correlation matrix and effective number of independent bets
from open position return series. Returns a formatted brief for the risk discussion.
Pure local Python + yfinance + numpy — no LLM calls.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List

import numpy as np


def build_correlation_brief(
    symbols: List[str],
    lookback_days: int = 60,
) -> str:
    """Compute portfolio correlation and return formatted brief for risk discussion.

    Args:
        symbols: List of ticker symbols from open positions.
        lookback_days: Number of calendar days for return history.

    Returns:
        Formatted multi-line string. Empty string if < 2 symbols or data insufficient.
    """
    if len(symbols) < 2:
        return ""

    try:
        import yfinance as yf
        import pandas as pd
    except ImportError:
        return ""

    # Fetch close prices
    end = datetime.now()
    start = end - timedelta(days=lookback_days + 10)  # buffer for market days
    try:
        prices = yf.download(
            symbols,
            start=start,
            end=end,
            auto_adjust=True,
            progress=False,
        )
        if prices.empty:
            return ""
        # Handle multi-level columns from yf.download
        if isinstance(prices.columns, pd.MultiIndex):
            prices = prices["Close"]
        elif "Close" in prices.columns:
            prices = prices[["Close"]]
    except Exception:
        return ""

    # Need a DataFrame with multiple columns
    if isinstance(prices, pd.Series):
        return ""  # only got one symbol's data

    # Drop symbols with no data
    prices = prices.dropna(axis=1, how="all")
    available = [s for s in symbols if s in prices.columns]
    if len(available) < 2:
        return ""

    prices = prices[available]
    returns = prices.pct_change().dropna()

    if len(returns) < 20:
        return ""

    corr_matrix = returns.corr()

    # Effective number of bets via eigenvalue HHI
    try:
        eigenvalues = np.linalg.eigvalsh(corr_matrix.values)
        eigenvalues = np.maximum(eigenvalues, 0)  # numerical stability
        total = eigenvalues.sum()
        if total > 0:
            weights = eigenvalues / total
            hhi = float((weights ** 2).sum())
            effective_bets = 1.0 / hhi if hhi > 0 else float(len(available))
        else:
            effective_bets = float(len(available))
    except Exception:
        effective_bets = float(len(available))

    # Top correlated pairs
    pairs: List[tuple] = []
    for i, s1 in enumerate(available):
        for j, s2 in enumerate(available):
            if i < j and s1 in corr_matrix.columns and s2 in corr_matrix.columns:
                corr_val = corr_matrix.loc[s1, s2]
                if not np.isnan(corr_val):
                    pairs.append((s1, s2, float(corr_val)))
    pairs.sort(key=lambda x: -abs(x[2]))

    # Format brief
    n = len(available)
    lines = ["=== PORTFOLIO CORRELATION ==="]
    lines.append(f"Effective independent bets: {effective_bets:.1f} / {n} positions")
    if effective_bets < n * 0.5:
        lines.append(
            "WARNING: Low diversification — portfolio positions are highly correlated"
        )
    if pairs:
        top = pairs[:3]
        lines.append("Highest correlations:")
        for s1, s2, corr in top:
            lines.append(f"  {s1} — {s2}: {corr:.2f}")
    lines.append("=== END CORRELATION ===")
    return "\n".join(lines)
