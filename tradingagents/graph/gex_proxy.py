"""Approximate GEX from SPY options chain via yfinance.

Simple dealer gamma exposure proxy — NOT a replacement for manual Grok input,
but prevents flying blind when manual data is stale.

4-hour in-process cache (like liquidity_gate.py).
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# In-process cache: (result_dict, fetch_time_unix)
_CACHE: Optional[Tuple[Dict[str, Any], float]] = None
_CACHE_TTL_SECONDS = 4 * 3600  # 4 hours


def compute_gex_proxy() -> Dict[str, Any]:
    """Approximate GEX from SPY options chain. 4-hour cache.

    Returns dict with: net_gex, gex_magnitude, key_pin_strike,
    gamma_flip_strike, source, fetched_at, error (if any).
    """
    global _CACHE

    now = time.time()
    if _CACHE is not None:
        result, fetch_time = _CACHE
        if now - fetch_time < _CACHE_TTL_SECONDS:
            return result

    result = _fetch_gex()
    _CACHE = (result, now)
    return result


def _fetch_gex() -> Dict[str, Any]:
    """Fetch SPY options chain and compute approximate GEX."""
    try:
        import yfinance as yf

        spy = yf.Ticker("SPY")
        info = spy.info or {}
        spot = float(info.get("regularMarketPrice") or info.get("previousClose") or 0.0)
        if spot <= 0:
            return _error_result("Could not fetch SPY spot price")

        expirations = spy.options
        if not expirations:
            return _error_result("No SPY options expirations available")

        # Use nearest 2 expirations
        use_expiries = expirations[:2]

        total_call_gamma_above = 0.0
        total_put_gamma_below = 0.0
        max_oi_strike = 0
        max_oi_total = 0
        all_strikes_gamma: Dict[int, float] = {}

        for exp in use_expiries:
            chain = spy.option_chain(exp)
            calls = chain.calls
            puts = chain.puts

            for _, row in calls.iterrows():
                strike = float(row.get("strike", 0))
                oi = int(row.get("openInterest", 0) or 0)
                if strike > spot and oi > 0:
                    # Calls above spot → dealer long gamma (sold calls, long gamma hedge)
                    gamma_contrib = oi * 100 * spot * 0.01  # rough gamma proxy
                    total_call_gamma_above += gamma_contrib
                strike_int = int(round(strike))
                total_strike_oi = int(row.get("openInterest", 0) or 0)
                all_strikes_gamma[strike_int] = all_strikes_gamma.get(strike_int, 0) + total_strike_oi

            for _, row in puts.iterrows():
                strike = float(row.get("strike", 0))
                oi = int(row.get("openInterest", 0) or 0)
                if strike < spot and oi > 0:
                    # Puts below spot → dealer short gamma (sold puts, short gamma hedge)
                    gamma_contrib = oi * 100 * spot * 0.01
                    total_put_gamma_below += gamma_contrib
                strike_int = int(round(strike))
                total_strike_oi = int(row.get("openInterest", 0) or 0)
                all_strikes_gamma[strike_int] = all_strikes_gamma.get(strike_int, 0) + total_strike_oi

        # Net GEX = call gamma above spot - put gamma below spot
        net_gex_value = total_call_gamma_above - total_put_gamma_below

        if net_gex_value > 0:
            net_gex = "LONG_GAMMA"
        elif net_gex_value < 0:
            net_gex = "SHORT_GAMMA"
        else:
            net_gex = "NEUTRAL"

        # Magnitude based on ratio
        total = total_call_gamma_above + total_put_gamma_below
        if total > 0:
            ratio = abs(net_gex_value) / total
            if ratio > 0.6:
                magnitude = "extreme"
            elif ratio > 0.3:
                magnitude = "elevated"
            elif ratio > 0.1:
                magnitude = "moderate"
            else:
                magnitude = "low"
        else:
            magnitude = "low"

        # Key pin strike = strike with max total OI
        if all_strikes_gamma:
            max_oi_strike = max(all_strikes_gamma, key=all_strikes_gamma.get)
            max_oi_total = all_strikes_gamma[max_oi_strike]

        # Gamma flip: approximate as spot-level (where call/put OI crosses)
        # Simplified: use the closest strike to spot as the flip zone
        gamma_flip_strike = int(round(spot))

        return {
            "net_gex": net_gex,
            "gex_magnitude": magnitude,
            "key_pin_strike": max_oi_strike,
            "gamma_flip_strike": gamma_flip_strike,
            "spot_price": round(spot, 2),
            "source": "yfinance_proxy",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }

    except Exception as exc:
        logger.warning("GEX proxy fetch failed: %s", exc)
        return _error_result(str(exc))


def _error_result(msg: str) -> Dict[str, Any]:
    return {
        "net_gex": "UNKNOWN",
        "gex_magnitude": "unknown",
        "key_pin_strike": 0,
        "gamma_flip_strike": 0,
        "source": "yfinance_proxy",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "error": msg,
    }
