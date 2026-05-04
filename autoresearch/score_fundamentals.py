"""Fundamental scoring function — AGENT MODIFIES THIS FILE.

Percentile-rank each financial ratio across tickers, apply weighted sum.
Run: python autoresearch/score_fundamentals.py
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prepare_fundamentals import evaluate  # noqa: E402

# Baseline weights — agent optimizes these
WEIGHTS = {
    "revenue_growth_yoy": 15.0,
    "margin_expansion": 10.0,
    "roe": 15.0,
    "earnings_momentum": 15.0,
    "fcf_yield": 15.0,
    "accrual_quality_inv": 10.0,   # inverted — lower accruals = better
    "debt_to_equity_inv": 10.0,    # inverted — lower leverage = better
    "dilution_inv": 10.0,          # inverted — less dilution = better
}


def _percentile_rank(values):
    """Percentile-rank a dict of {ticker: value}, return {ticker: 0.0-1.0}."""
    finite = {k: v for k, v in values.items() if v is not None and math.isfinite(v)}
    if len(finite) <= 1:
        return {k: 0.5 for k in values}
    items = sorted(finite.items(), key=lambda kv: kv[1])
    n = len(items)
    ranks = {key: idx / (n - 1) for idx, (key, _) in enumerate(items)}
    # Tickers with None get median rank
    for k in values:
        if k not in ranks:
            ranks[k] = 0.5
    return ranks


def score(fundamentals):
    """Score all tickers in a snapshot. Percentile-rank each ratio, weighted sum, scale 0-100.

    Args:
        fundamentals: {ticker: {ratio_name: value_or_None}}
    Returns:
        {ticker: composite_score_0_to_100}
    """
    tickers = list(fundamentals.keys())
    if not tickers:
        return {}

    # Map ratio names to raw values, handling inversions
    ratio_map = {
        "revenue_growth_yoy": {},
        "margin_expansion": {},
        "roe": {},
        "earnings_momentum": {},
        "fcf_yield": {},
        "accrual_quality_inv": {},  # invert: lower = better → negate
        "debt_to_equity_inv": {},   # invert: lower = better → negate
        "dilution_inv": {},         # invert: lower = better → negate
    }

    for ticker, ratios in fundamentals.items():
        ratio_map["revenue_growth_yoy"][ticker] = ratios.get("revenue_growth_yoy")
        ratio_map["margin_expansion"][ticker] = ratios.get("margin_expansion")
        ratio_map["roe"][ticker] = ratios.get("roe")
        ratio_map["earnings_momentum"][ticker] = ratios.get("earnings_momentum")
        ratio_map["fcf_yield"][ticker] = ratios.get("fcf_yield")

        # Inverted ratios: negate so higher rank = better
        aq = ratios.get("accrual_quality")
        ratio_map["accrual_quality_inv"][ticker] = -aq if aq is not None else None

        de = ratios.get("debt_to_equity")
        ratio_map["debt_to_equity_inv"][ticker] = -de if de is not None else None

        dil = ratios.get("dilution")
        ratio_map["dilution_inv"][ticker] = -dil if dil is not None else None

    # Percentile-rank each ratio
    ranked = {name: _percentile_rank(vals) for name, vals in ratio_map.items()}

    # Weighted composite
    result = {}
    total_weight = sum(WEIGHTS.values())
    if total_weight <= 0:
        return {t: 50.0 for t in tickers}

    for ticker in tickers:
        weighted_sum = 0.0
        for ratio_name, weight in WEIGHTS.items():
            weighted_sum += weight * ranked.get(ratio_name, {}).get(ticker, 0.5)
        result[ticker] = max(0.0, min(100.0, (weighted_sum / total_weight) * 100.0))

    return result


if __name__ == "__main__":
    results = evaluate(score)
    print("\n---")
    for k, v in results.items():
        fmt = f"{v:.4f}" if isinstance(v, float) else str(v)
        print(f"{k + ':':20s} {fmt}")
