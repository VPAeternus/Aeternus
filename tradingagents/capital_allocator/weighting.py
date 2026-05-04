"""
Portfolio weighting utilities for the Capital Allocator.

score_to_weights: Convert AeternusRating scores + confidence to normalized weights.
risk_parity_weights: Equal Risk Contribution via Spinu (2013) convex optimization.
"""
from __future__ import annotations

import logging
import math
from typing import Dict, List

import numpy as np

logger = logging.getLogger(__name__)


def score_to_weights(
    ratings: List[Dict],
    min_score: float = 40.0,
    max_weight: float = 0.25,
) -> Dict[str, float]:
    """Convert AeternusRating dicts into normalized long-only portfolio weights.

    Algorithm (adapted from QuantConnect Lean InsightWeightingPortfolioConstructionModel):
    1. Filter out ratings with aeternus_score < min_score (sub-threshold excluded).
    2. For each passing ticker: raw_weight = (aeternus_score / 100) * (confidence / 5)
       This gives a weight proportional to both score strength and confidence.
    3. Normalize: weight_i = raw_weight_i / sum(raw_weights) so weights sum to 1.0.
    4. Cap any single weight at max_weight (0.25 default = 4-position floor).
       After capping, re-normalize remaining weights iteratively until convergence.
    5. Return {ticker: weight} dict. Excluded tickers are omitted from the dict.

    Args:
        ratings: List of AeternusRating dicts (must have 'ticker', 'aeternus_score', 'confidence').
        min_score: Ratings below this score are excluded from allocation.
        max_weight: Maximum weight per position (prevents over-concentration).

    Returns:
        Dict mapping ticker -> normalized weight. Weights sum to ~1.0.
        Returns empty dict if no ratings pass the min_score filter.
    """
    if not ratings:
        return {}

    # Step 1: filter by min_score
    passing = [r for r in ratings if float(r.get("aeternus_score", 0.0)) >= min_score]
    if not passing:
        return {}

    # Step 2: compute raw weights
    tickers = [r["ticker"] for r in passing]
    raw = np.array(
        [(float(r["aeternus_score"]) / 100.0) * (float(r["confidence"]) / 5.0) for r in passing],
        dtype=float,
    )

    total = raw.sum()
    if total <= 0.0:
        return {}

    # Step 3: normalize to sum to 1.0
    w = raw / total

    # Step 4: cap at max_weight with iterative redistribution
    w = _apply_weight_cap(w, max_weight)

    return {ticker: float(w[i]) for i, ticker in enumerate(tickers)}


def risk_parity_weights(
    symbols: List[str],
    covariance: Dict[str, Dict[str, float]],
    max_weight: float = 0.40,
    fallback_to_equal: bool = True,
) -> Dict[str, float]:
    """Compute risk parity (equal risk contribution) portfolio weights.

    Given a covariance matrix, find weights w such that each asset contributes
    equally to total portfolio variance: w_i * (Sigma @ w)_i = constant for all i.

    Uses scipy.optimize.minimize with the Spinu (2013) objective:
        f(w) = 0.5 * w^T Sigma w - (1/N) * sum(ln(w_i))
    subject to: w_i >= 1e-6

    The log-sum term enforces positive weights and equal risk contribution at the minimum.

    Args:
        symbols: List of tickers (must be in covariance keys).
        covariance: Dict-of-dicts covariance matrix from build_covariance_matrix().
        max_weight: Cap per position after optimization.
        fallback_to_equal: If scipy fails, return equal weights.

    Returns:
        Dict mapping symbol -> weight, summing to 1.0.
        Returns empty dict if symbols is empty (or fallback_to_equal=False and optimization fails).
    """
    try:
        from scipy.optimize import minimize  # noqa: PLC0415
    except ImportError as exc:
        raise ImportError(
            "risk_parity_weights requires scipy. Install it with: pip install scipy"
        ) from exc

    n = len(symbols)
    if n == 0:
        return {}
    if n == 1:
        return {symbols[0]: 1.0}

    # Build covariance matrix as numpy array
    cov = np.array(
        [[covariance.get(si, {}).get(sj, 0.0) for sj in symbols] for si in symbols],
        dtype=float,
    )

    w0 = np.ones(n, dtype=float) / n  # equal weight starting point
    # No upper bound: the Spinu objective finds ERC weights up to a positive scale
    # factor; we normalize after. An upper bound of 1.0 causes L-BFGS-B to converge
    # at the boundary, destroying the equal-risk-contribution property.
    bounds = [(1e-6, None)] * n

    def objective(w: np.ndarray) -> float:
        return 0.5 * float(w @ cov @ w) - (1.0 / n) * float(np.sum(np.log(w)))

    def gradient(w: np.ndarray) -> np.ndarray:
        return cov @ w - (1.0 / n) / w

    try:
        result = minimize(
            objective,
            w0,
            jac=gradient,
            method="L-BFGS-B",
            bounds=bounds,
            options={"maxiter": 500, "ftol": 1e-12},
        )
        if result.success or result.fun < objective(w0):
            w = np.abs(result.x)
        else:
            if fallback_to_equal:
                logger.warning("risk_parity_weights: optimizer did not converge; falling back to equal weights.")
                w = w0.copy()
            else:
                return {}
    except Exception as exc:
        logger.warning("risk_parity_weights: scipy.optimize.minimize raised %s; falling back.", exc)
        if fallback_to_equal:
            w = w0.copy()
        else:
            return {}

    # Normalize to sum to 1.0
    w_sum = w.sum()
    if w_sum <= 0.0:
        if fallback_to_equal:
            w = w0.copy()
        else:
            return {}
    else:
        w = w / w_sum

    # Apply per-position cap with iterative renormalization
    w = _apply_weight_cap(w, max_weight)

    return {sym: float(w[i]) for i, sym in enumerate(symbols)}


def _apply_weight_cap(w: np.ndarray, cap: float) -> np.ndarray:
    """Apply per-position weight cap with iterative redistribution.

    In each iteration:
    1. Identify positions exceeding the cap (overweight) and those at or below it (free).
    2. Pin overweight positions to exactly `cap`.
    3. Redistribute their excess weight proportionally among free positions.
    4. Repeat until no free position exceeds the cap (convergence), or 20 iterations.

    When all positions are simultaneously overweight (e.g. 2-position portfolio with
    cap=0.25), no redistribution is possible; the capped weights are normalized so
    they sum to 1.0.

    Args:
        w: 1-D numpy array of non-negative weights summing to ~1.0.
        cap: Maximum allowed weight per position (0 < cap <= 1.0).

    Returns:
        1-D numpy array with the same length as `w`, renormalized so weights sum
        to 1.0.
    """
    w = w.copy()
    for _ in range(20):
        over_mask = w > cap + 1e-9
        if not np.any(over_mask):
            break
        free_mask = ~over_mask
        if not np.any(free_mask):
            # All positions are overweight — no free positions to absorb excess.
            # Normalize the capped values so they sum to 1.0.
            capped = np.minimum(w, cap)
            total = capped.sum()
            w = capped / total if total > 0.0 else capped
            break
        # Excess weight to redistribute
        excess = (w[over_mask] - cap).sum()
        # Pin overweight positions to cap
        w[over_mask] = cap
        # Distribute excess proportionally to free positions
        free_total = w[free_mask].sum()
        if free_total > 1e-12:
            w[free_mask] += excess * (w[free_mask] / free_total)
        # else: nowhere to put excess — leave as-is (degenerate case)
    return w
