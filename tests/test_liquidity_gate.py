"""Tests for tradingagents/graph/liquidity_gate.py"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from tradingagents.graph.liquidity_gate import (
    check_liquidity,
    filter_orders_by_liquidity,
    get_liquidity_metrics,
)


# --- Test 1: Liquid name passes ---

def test_liquid_name_passes():
    """ADV $50M, market cap $5B → passes both thresholds."""
    with patch("tradingagents.graph.liquidity_gate.yf.Ticker") as mock_ticker:
        mock_instance = MagicMock()
        mock_instance.info = {
            "averageVolume": 1_000_000,  # 1M shares
            "regularMarketPrice": 50.0,   # 1M * $50 = $50M ADV
            "marketCap": 5_000_000_000,   # $5B
        }
        mock_ticker.return_value = mock_instance

        passes, reason = check_liquidity("AAPL", min_adv_usd=10_000_000, min_market_cap=100_000_000)

    assert passes is True
    assert reason == ""


# --- Test 2: Low ADV rejected ---

def test_low_adv_rejected():
    """ADV $2M, market cap $1B → rejected due to low ADV."""
    with patch("tradingagents.graph.liquidity_gate.yf.Ticker") as mock_ticker:
        mock_instance = MagicMock()
        mock_instance.info = {
            "averageVolume": 40_000,       # 40k shares
            "regularMarketPrice": 50.0,    # 40k * $50 = $2M ADV
            "marketCap": 1_000_000_000,    # $1B
        }
        mock_ticker.return_value = mock_instance

        passes, reason = check_liquidity("ILIQ", min_adv_usd=10_000_000, min_market_cap=100_000_000)

    assert passes is False
    assert "ADV" in reason
    assert "$2.0M" in reason
    assert "below minimum" in reason


# --- Test 3: Low market cap rejected ---

def test_low_market_cap_rejected():
    """ADV $50M, market cap $50M → rejected due to low market cap."""
    with patch("tradingagents.graph.liquidity_gate.yf.Ticker") as mock_ticker:
        mock_instance = MagicMock()
        mock_instance.info = {
            "averageVolume": 1_000_000,    # 1M shares
            "regularMarketPrice": 50.0,    # 1M * $50 = $50M ADV
            "marketCap": 50_000_000,       # $50M (below $100M minimum)
        }
        mock_ticker.return_value = mock_instance

        passes, reason = check_liquidity("SMCAP", min_adv_usd=10_000_000, min_market_cap=100_000_000)

    assert passes is False
    assert "Market cap" in reason
    assert "$50M" in reason
    assert "below minimum" in reason


# --- Test 4: SELL order always passes ---

def test_sell_always_passes():
    """SELL order with low ADV → passes (exits never blocked)."""
    with patch("tradingagents.graph.liquidity_gate.yf.Ticker") as mock_ticker:
        mock_instance = MagicMock()
        mock_instance.info = {
            "averageVolume": 10_000,       # Very low ADV
            "regularMarketPrice": 50.0,
            "marketCap": 50_000_000,       # Below minimum
        }
        mock_ticker.return_value = mock_instance

        orders = [
            {
                "symbol": "ILIQ",
                "side": "SELL",
                "quantity": 100,
            }
        ]

        passed, rejected = filter_orders_by_liquidity(
            orders,
            min_adv_usd=10_000_000,
            min_market_cap=100_000_000,
        )

    assert len(passed) == 1
    assert len(rejected) == 0
    assert passed[0]["symbol"] == "ILIQ"


# --- Test 5: Filter orders splits correctly ---

def test_filter_orders_splits_correctly():
    """Mixed list of BUY/SELL, liquid/illiquid → correct split."""
    with patch("tradingagents.graph.liquidity_gate.yf.Ticker") as mock_ticker:
        def _make_ticker(symbol):
            instance = MagicMock()
            if symbol == "AAPL":
                # Liquid
                instance.info = {
                    "averageVolume": 1_000_000,
                    "regularMarketPrice": 150.0,
                    "marketCap": 3_000_000_000,
                }
            elif symbol == "ILIQ":
                # Illiquid
                instance.info = {
                    "averageVolume": 10_000,
                    "regularMarketPrice": 50.0,
                    "marketCap": 50_000_000,
                }
            else:
                instance.info = {}
            return instance

        mock_ticker.side_effect = lambda s: _make_ticker(s)

        orders = [
            {"symbol": "AAPL", "side": "BUY", "quantity": 100},      # BUY, liquid → PASS
            {"symbol": "ILIQ", "side": "BUY", "quantity": 100},      # BUY, illiquid → REJECT
            {"symbol": "ILIQ", "side": "SELL", "quantity": 100},     # SELL, illiquid → PASS
        ]

        passed, rejected = filter_orders_by_liquidity(
            orders,
            min_adv_usd=10_000_000,
            min_market_cap=100_000_000,
        )

    assert len(passed) == 2
    assert len(rejected) == 1

    # Check passed orders
    assert passed[0]["symbol"] == "AAPL"
    assert passed[0]["side"] == "BUY"
    assert passed[1]["symbol"] == "ILIQ"
    assert passed[1]["side"] == "SELL"

    # Check rejected order
    assert rejected[0]["symbol"] == "ILIQ"
    assert rejected[0]["side"] == "BUY"
    assert "reason" in rejected[0]


# --- Test 6: yfinance failure returns zero metrics ---

def test_yfinance_failure_returns_zero_metrics():
    """Exception in yf.Ticker → graceful failure with zero metrics."""
    with patch("tradingagents.graph.liquidity_gate.yf.Ticker") as mock_ticker:
        mock_ticker.side_effect = Exception("Network error")

        metrics = get_liquidity_metrics("BADTICKER")

    assert metrics["symbol"] == "BADTICKER"
    assert metrics["adv_usd"] == 0.0
    assert metrics["market_cap"] == 0.0
    assert metrics["fetched_at"] == "error"

    # Now test filter behavior on zero metrics
    orders = [
        {"symbol": "BADTICKER", "side": "BUY", "quantity": 100}
    ]

    passed, rejected = filter_orders_by_liquidity(
        orders,
        min_adv_usd=10_000_000,
        min_market_cap=100_000_000,
    )

    assert len(passed) == 0
    assert len(rejected) == 1
    assert rejected[0]["symbol"] == "BADTICKER"
    assert "ADV" in rejected[0]["reason"]
