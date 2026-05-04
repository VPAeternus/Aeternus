"""Pre-trade liquidity gate.

Rejects order intents for names that fail ADV or market cap thresholds.
Uses yfinance for ADV and market cap data with a 24-hour in-process cache.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Tuple

import yfinance as yf

logger = logging.getLogger(__name__)

# In-process cache: symbol -> (metrics_dict, fetch_time_unix)
_CACHE: Dict[str, Tuple[Dict[str, Any], float]] = {}
_CACHE_TTL_SECONDS = 86400  # 24 hours


def get_liquidity_metrics(symbol: str) -> dict:
    """Fetch ADV and market cap for a symbol with 24-hour in-process caching.

    Args:
        symbol: Ticker symbol (e.g., 'AAPL')

    Returns:
        Dict with keys:
        - symbol: str (uppercase)
        - adv_usd: float (average daily volume in USD, 0.0 on error)
        - market_cap: float (market cap in USD, 0.0 on error)
        - fetched_at: str (ISO timestamp or 'error')
    """
    symbol = str(symbol).upper().strip()

    # Check cache
    now = time.time()
    if symbol in _CACHE:
        metrics, fetch_time = _CACHE[symbol]
        if now - fetch_time < _CACHE_TTL_SECONDS:
            return metrics

    # Fetch from yfinance
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info or {}

        avg_volume = float(info.get("averageVolume") or 0.0)
        regular_price = float(info.get("regularMarketPrice") or 0.0)
        market_cap = float(info.get("marketCap") or 0.0)

        adv_usd = avg_volume * regular_price if regular_price > 0 else 0.0

        fetched_at = datetime.now(timezone.utc).isoformat()
        metrics = {
            "symbol": symbol,
            "adv_usd": adv_usd,
            "market_cap": market_cap,
            "fetched_at": fetched_at,
        }

        _CACHE[symbol] = (metrics, now)
        return metrics

    except Exception as e:
        logger.warning("Failed to fetch liquidity metrics for %s: %s", symbol, e)
        return {
            "symbol": symbol,
            "adv_usd": 0.0,
            "market_cap": 0.0,
            "fetched_at": "error",
        }


def check_liquidity(
    symbol: str,
    min_adv_usd: float = 10_000_000,
    min_market_cap: float = 100_000_000,
) -> tuple[bool, str]:
    """Check if symbol passes liquidity thresholds.

    Args:
        symbol: Ticker symbol
        min_adv_usd: Minimum average daily volume in USD (default $10M)
        min_market_cap: Minimum market cap in USD (default $100M)

    Returns:
        Tuple (passes: bool, reason: str)
        - reason is empty string if passes
        - reason is descriptive string if fails (e.g., "ADV $2.1M below minimum $10.0M")
    """
    metrics = get_liquidity_metrics(symbol)

    adv_usd = metrics.get("adv_usd", 0.0)
    market_cap = metrics.get("market_cap", 0.0)

    # Check ADV
    if adv_usd < min_adv_usd:
        adv_millions = adv_usd / 1_000_000
        min_millions = min_adv_usd / 1_000_000
        return (
            False,
            f"ADV ${adv_millions:.1f}M below minimum ${min_millions:.1f}M"
        )

    # Check market cap
    if market_cap < min_market_cap:
        cap_millions = market_cap / 1_000_000
        min_cap_millions = min_market_cap / 1_000_000
        return (
            False,
            f"Market cap ${cap_millions:.0f}M below minimum ${min_cap_millions:.0f}M"
        )

    return (True, "")


# Leveraged ETF patterns — reject unless explicitly allowed
import re

_LEVERAGED_ETF_PATTERN = re.compile(
    r"^(TQQQ|SQQQ|UPRO|SPXU|UDOW|SDOW|TNA|TZA|LABU|LABD|SOXL|SOXS|"
    r"FNGU|FNGD|TECL|TECS|SPXL|SPXS|CURE|EDZ|ERX|ERY|FAS|FAZ|"
    r"MSTU|MSTX|NUGT|DUST|JNUG|JDST|YINN|YANG|UVXY|SVXY|UVIX)$"
)


def is_leveraged_etf(symbol: str) -> bool:
    """Check if symbol is a known 2x/3x leveraged or inverse ETF."""
    return bool(_LEVERAGED_ETF_PATTERN.match(str(symbol).upper().strip()))


def filter_orders_by_liquidity(
    orders: List[Dict[str, Any]],
    min_adv_usd: float = 10_000_000,
    min_market_cap: float = 100_000_000,
    dry_run: bool = False,
    allow_leveraged_etfs: bool = False,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Filter orders by liquidity gates and leveraged ETF variance drag gate.

    Separates BUY orders that fail ADV/market cap thresholds or are
    leveraged ETFs (2x/3x) subject to variance drag.
    SELL/close orders always pass (never block exits).

    Args:
        orders: List of order intent dicts
        min_adv_usd: Minimum ADV threshold (default $10M)
        min_market_cap: Minimum market cap threshold (default $100M)
        dry_run: If True, return all orders as passed (no API calls)
        allow_leveraged_etfs: If True, skip the leveraged ETF gate

    Returns:
        Tuple (passed_orders, rejected_orders)
    """
    passed = []
    rejected = []

    for order in orders:
        if not isinstance(order, dict):
            passed.append(order)
            continue

        side = str(order.get("side", "BUY")).upper()
        symbol = str(order.get("symbol", "")).upper().strip()

        # SELL/close orders always pass
        if side != "BUY":
            passed.append(order)
            continue

        # If no symbol, pass it (will fail downstream anyway)
        if not symbol:
            passed.append(order)
            continue

        # V3 benchmark orders (QQQ/TQQQ/etc.) skip all gates
        if str(order.get("research_playbook", "")).upper() == "V3_INDEX":
            passed.append(order)
            continue

        # Leveraged ETF variance drag gate (fires even in dry_run — structural risk)
        if not allow_leveraged_etfs and is_leveraged_etf(symbol):
            rejected.append({
                "symbol": symbol,
                "side": side,
                "reason": f"Leveraged ETF blocked — variance drag destroys compounding (use --allow-leveraged-etfs to override)",
                "adv_usd": 0.0,
                "market_cap": 0.0,
            })
            continue

        # Dry run: pass remaining (skips API calls for ADV/market cap)
        if dry_run:
            passed.append(order)
            continue

        # Check liquidity for BUY orders
        passes, reason = check_liquidity(symbol, min_adv_usd, min_market_cap)

        if passes:
            passed.append(order)
        else:
            metrics = get_liquidity_metrics(symbol)
            rejected_order = {
                "symbol": symbol,
                "side": side,
                "reason": reason,
                "adv_usd": metrics.get("adv_usd", 0.0),
                "market_cap": metrics.get("market_cap", 0.0),
            }
            rejected.append(rejected_order)

    return (passed, rejected)
