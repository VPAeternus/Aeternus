"""Adaptive Kelly position sizer — fractional Kelly from track record stats.

Two functions, ~50 lines. Complementary to score_to_weights() — sizes
positions from actual win/loss statistics rather than guesswork.
"""

from __future__ import annotations

from typing import Dict

import numpy as np


def compute_kelly_fraction(
    win_rate: float,
    avg_win_pct: float,
    avg_loss_pct: float,
    fractional: float = 0.25,
    min_trades: int = 10,
    trade_count: int = 0,
) -> float:
    """Compute fractional Kelly criterion for position sizing.

    f* = (p*b - q) / b, where:
        p = win_rate, q = 1 - p, b = avg_win / avg_loss (odds)

    Returns 0.0 if insufficient trade history (< min_trades).
    Negative Kelly (losing system) floors at 0.01.
    """
    if trade_count < min_trades:
        return 0.0

    p = max(0.0, min(1.0, win_rate))
    q = 1.0 - p

    abs_loss = abs(avg_loss_pct)
    abs_win = abs(avg_win_pct)

    # Edge case: no losses recorded
    if abs_loss == 0:
        return fractional  # Can't compute odds; return fractional as cap

    b = abs_win / abs_loss  # Win/loss ratio (odds)

    # Kelly formula
    kelly = (p * b - q) / b

    # Floor negative Kelly (losing system)
    if kelly <= 0:
        return 0.01

    # Apply fractional Kelly (conservative)
    return round(kelly * fractional, 4)


def apply_kelly_sizing(
    weights: Dict[str, float],
    kelly_fraction: float,
    max_position_pct: float = 0.15,
) -> Dict[str, float]:
    """Scale score-based weights by Kelly fraction. Cap at max_position_pct. Renormalize.

    Reduces overall portfolio allocation to kelly_fraction of full capacity, with
    positions sized proportionally and capped per-position. Useful for applying
    fractional Kelly criterion to a scored portfolio.

    Args:
        weights: Symbol → weight dict from score_to_weights(). Should sum to ~1.0.
        kelly_fraction: Fraction of portfolio to deploy (e.g., 0.10 = 10% Kelly).
                       Output of compute_kelly_fraction().
        max_position_pct: Maximum single-position weight within the Kelly allocation.
                         Default 15% (after scaling by kelly_fraction).

    Returns:
        New weights dict, scaled, capped, and renormalized. Sums to kelly_fraction
        (NOT 1.0), representing the deployed portion of the portfolio.
        Caller should allocate remaining (1 - kelly_fraction) to cash/reserves.

    Example:
        weights = {"AAPL": 0.4, "MSFT": 0.3, "XOM": 0.3}  # sum = 1.0
        result = apply_kelly_sizing(weights, kelly_fraction=0.10)
        # result ≈ {"AAPL": 0.04, "MSFT": 0.03, "XOM": 0.03}  # sum = 0.10
    """
    if not weights or kelly_fraction <= 0:
        return weights

    # Step 1: Scale each weight by Kelly fraction
    symbols = list(weights.keys())
    scaled = np.array([weights[sym] * kelly_fraction for sym in symbols], dtype=float)

    # Step 2: Cap and renormalize iteratively (like _apply_weight_cap)
    capped = _apply_kelly_weight_cap(scaled, max_position_pct, kelly_fraction)

    return {sym: float(capped[i]) for i, sym in enumerate(symbols)}


def _apply_kelly_weight_cap(w: np.ndarray, cap: float, target_sum: float) -> np.ndarray:
    """Apply per-position weight cap with iterative redistribution, preserving target sum.

    Similar to _apply_weight_cap in weighting.py, but ensures result sums to target_sum.

    In each iteration:
    1. Identify positions exceeding the cap (overweight) and those at or below it (free).
    2. Pin overweight positions to exactly `cap`.
    3. Redistribute their excess weight proportionally among free positions.
    4. Repeat until no free position exceeds the cap (convergence), or 20 iterations.

    Args:
        w: 1-D numpy array of non-negative weights (usually summing to target_sum).
        cap: Maximum allowed weight per position.
        target_sum: Desired sum of output array (e.g., kelly_fraction).

    Returns:
        1-D numpy array with the same length as `w`, renormalized to sum to target_sum.
    """
    w = w.copy()
    for _ in range(20):
        over_mask = w > cap + 1e-9
        if not np.any(over_mask):
            break
        free_mask = ~over_mask
        if not np.any(free_mask):
            # All positions are overweight — no free positions to absorb excess.
            # Cap and renormalize to target_sum.
            capped = np.minimum(w, cap)
            total = capped.sum()
            w = (capped / total * target_sum) if total > 0.0 else capped
            break
        # Excess weight to redistribute
        excess = (w[over_mask] - cap).sum()
        # Pin overweight positions to cap
        w[over_mask] = cap
        # Distribute excess proportionally to free positions
        free_total = w[free_mask].sum()
        if free_total > 1e-12:
            w[free_mask] += excess * (w[free_mask] / free_total)
    
    # Final renormalization to target_sum
    total = w.sum()
    if total > 1e-12:
        w = w / total * target_sum
    return w
