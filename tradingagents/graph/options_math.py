"""Black-Scholes math helpers for options position monitoring.

Shared by cc_csp_roll_monitor and any future options modules.
Do NOT modify csp_overlay.py — it keeps its own inline copy.
"""
import math


def _norm_cdf(x: float) -> float:
    """Standard normal CDF via math.erfc."""
    return 0.5 * math.erfc(-x / math.sqrt(2))


def _bs_call(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Black-Scholes call price."""
    if T <= 0 or sigma <= 0:
        return max(S - K, 0.0)
    sqrt_T = math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T
    return S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)


def _bs_put(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Black-Scholes put price."""
    if T <= 0 or sigma <= 0:
        return max(K - S, 0.0)
    sqrt_T = math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T
    return K * math.exp(-r * T) * _norm_cdf(-d2) - S * _norm_cdf(-d1)


def _bs_delta_call(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Black-Scholes call delta = N(d1)."""
    if T <= 0 or sigma <= 0:
        return 1.0 if S > K else 0.0
    sqrt_T = math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * sqrt_T)
    return _norm_cdf(d1)


def _bs_delta_put(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Black-Scholes put delta = N(d1) - 1."""
    return _bs_delta_call(S, K, T, r, sigma) - 1.0
