"""Scoring function — AGENT MODIFIES THIS FILE.

Starts as exact copy of production scoring logic.
Run: python autoresearch/score.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prepare import evaluate  # noqa: E402

# Production weights (9 families + breakout_discovery)
WEIGHTS = {
    "price_momentum": 30.0,
    "social_momentum": 10.0,
    "news_catalyst": 15.0,
    "macro_regime_fit": 14.0,
    "smart_money": 11.0,
    "sector_rotation": 8.0,
    "insider_cluster": 5.0,
    "emergence": 7.0,
    "liquidity_tradability": 5.0,
    "breakout_discovery": 0.0,
}

MIN_SIGNAL_FAMILIES = 3


def momentum_score(subscores):
    """Production momentum_score: 60% price + 30% social + 10% news."""
    return (
        0.60 * subscores.get("price_momentum", 50.0)
        + 0.30 * subscores.get("social_momentum", 50.0)
        + 0.10 * subscores.get("news_catalyst", 50.0)
    )


def asymmetry_score(subscores, mom_score):
    """Production asymmetry_score: 70% momentum + 10% macro + 10% smart + 10% liq."""
    return (
        0.70 * mom_score
        + 0.10 * subscores.get("macro_regime_fit", 50.0)
        + 0.10 * subscores.get("smart_money", 50.0)
        + 0.10 * subscores.get("liquidity_tradability", 50.0)
    )


def score(signals):
    """Score all tickers in a snapshot.

    Args:
        signals: {ticker: {family: score_0_to_100}}
    Returns:
        {ticker: composite_score}
    """
    result = {}
    for ticker, subscores in signals.items():
        weighted_sum = 0.0
        total_weight = 0.0
        for family, weight in WEIGHTS.items():
            s = subscores.get(family)
            if s is None:
                continue
            weighted_sum += weight * float(s)
            total_weight += weight

        if total_weight <= 0:
            continue

        result[ticker] = weighted_sum / total_weight

    return result


if __name__ == "__main__":
    results = evaluate(score)
    print("\n---")
    for k, v in results.items():
        fmt = f"{v:.4f}" if isinstance(v, float) else str(v)
        print(f"{k + ':':20s} {fmt}")
