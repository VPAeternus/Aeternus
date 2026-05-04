"""Tests for RTH timing engine (S-057)."""

import numpy as np
import pandas as pd
import pytest


def _make_df(close_val: float, sma200_above: bool, daily_vol_pct: float, n: int = 350):
    """Build a synthetic OHLCV DataFrame with target volatility in last 61 bars.

    If sma200_above=True, the last close is above SMA200, SMA50, and SMA3.
    daily_vol_pct controls the mean absolute daily return in the last 61 bars.
    n=350 provides warmup data for 252-day initialization.
    """
    np.random.seed(42)
    target_abs_ret = daily_vol_pct / 100.0

    # Create prices: smoothly increasing/decreasing for trend + recent volatility
    prices = np.full(n, close_val, dtype=float)

    # Build a smooth SMA200 baseline that current price is above/below
    if sma200_above:
        # Low baseline so we can be above it
        baseline = np.linspace(close_val * 0.80, close_val * 0.95, n)
    else:
        # High baseline so we can be below it
        baseline = np.linspace(close_val * 1.05, close_val * 1.15, n)

    # Start from baseline and add volatility everywhere
    prices = baseline.copy()

    # Add high volatility moves, especially in last 61 bars
    for i in range(n):
        # Random walk component
        if i > 0:
            sign = 1.0 if np.random.random() > 0.5 else -1.0
            if i >= n - 61:
                # Last 61 bars: use full target_abs_ret volatility
                move = sign * target_abs_ret * np.random.uniform(0.5, 1.5)
            else:
                # Earlier bars: use lower volatility
                move = sign * target_abs_ret * 0.3 * np.random.uniform(0.5, 1.5)
            prices[i] = prices[i - 1] * (1.0 + move)

    # Ensure SMA positioning for final bar
    sma200_val = np.mean(prices[-200:])
    sma50_val = np.mean(prices[-50:])
    sma3_val = np.mean(prices[-3:])

    if sma200_above:
        if prices[-1] <= sma200_val:
            prices[-1] = sma200_val * 1.02
        if prices[-1] <= sma50_val:
            prices[-1] = sma50_val * 1.02
        if prices[-1] <= sma3_val:
            prices[-1] = sma3_val * 1.01
    else:
        if prices[-1] >= sma200_val:
            prices[-1] = sma200_val * 0.98

    dates = pd.date_range(end="2026-02-27", periods=n, freq="B")
    df = pd.DataFrame({
        "date": dates,
        "open": prices,
        "high": prices * 1.01,
        "low": prices * 0.99,
        "close": prices,
        "volume": np.full(n, 1_000_000),
    })

    # Compute SMA columns so rth_timing.py can use them directly
    df["sma3"] = df["close"].rolling(3).mean()
    df["sma50"] = df["close"].rolling(50).mean()
    df["sma200"] = df["close"].rolling(200).mean()

    return df


class TestRTHTimingEngine:
    def test_high_vol_above_sma200(self):
        """Q5 stock above all SMAs -> returns new schema."""
        from tradingagents.phase_engine.rth_timing import RTHTimingEngine
        # Input 2.0% generates ~2.34% actual vol -> Q5
        df = _make_df(100.0, sma200_above=True, daily_vol_pct=2.0)
        engine = RTHTimingEngine()
        sig = engine.get_signal("TEST", df=df)
        assert sig["above_sma200"] is True
        assert sig["above_sma50"] is True
        assert sig["above_sma3"] is True
        assert sig["vol_quintile"] == 5
        assert isinstance(sig["rth_avg_daily"], (float, int))
        assert isinstance(sig["rth_last5d"], (float, int))

    def test_low_vol_above_sma200(self):
        """Q1 stock above all SMAs."""
        from tradingagents.phase_engine.rth_timing import RTHTimingEngine
        # Input 0.5% generates ~0.60% actual vol -> Q1
        df = _make_df(100.0, sma200_above=True, daily_vol_pct=0.5)
        engine = RTHTimingEngine()
        sig = engine.get_signal("TEST", df=df)
        assert sig["above_sma200"] is True
        assert sig["above_sma50"] is True
        assert sig["above_sma3"] is True
        assert sig["vol_quintile"] == 1
        assert isinstance(sig["rth_avg_daily"], (float, int))
        assert isinstance(sig["rth_last5d"], (float, int))

    def test_below_sma200(self):
        """Stock below SMA200."""
        from tradingagents.phase_engine.rth_timing import RTHTimingEngine
        df = _make_df(100.0, sma200_above=False, daily_vol_pct=2.0)
        engine = RTHTimingEngine()
        sig = engine.get_signal("TEST", df=df)
        assert sig["above_sma200"] is False
        assert isinstance(sig["rth_avg_daily"], (float, int))
        assert isinstance(sig["rth_last5d"], (float, int))

    def test_vol_quintile_boundaries(self):
        """Correct quintile for each threshold boundary."""
        from tradingagents.phase_engine.rth_timing import _vol_quintile
        assert _vol_quintile(0.5) == 1    # < 1.13
        assert _vol_quintile(1.12) == 1   # < 1.13
        assert _vol_quintile(1.13) == 2   # >= 1.13, < 1.34
        assert _vol_quintile(1.33) == 2   # < 1.34
        assert _vol_quintile(1.34) == 3   # >= 1.34, < 1.54
        assert _vol_quintile(1.53) == 3   # < 1.54
        assert _vol_quintile(1.54) == 4   # >= 1.54, < 1.83
        assert _vol_quintile(1.82) == 4   # < 1.83
        assert _vol_quintile(1.83) == 5   # >= 1.83
        assert _vol_quintile(3.0) == 5    # well above

    def test_returns_empty_on_failure(self):
        """Bad data -> {}"""
        from tradingagents.phase_engine.rth_timing import RTHTimingEngine
        engine = RTHTimingEngine()
        # Too few bars
        df = pd.DataFrame({"close": [100.0] * 50, "date": pd.date_range("2026-01-01", periods=50)})
        assert engine.get_signal("TEST", df=df) == {}

    def test_get_signals_batch(self):
        """get_signals returns list, skips failures."""
        from tradingagents.phase_engine.rth_timing import RTHTimingEngine
        engine = RTHTimingEngine()
        df_good = _make_df(100.0, sma200_above=True, daily_vol_pct=2.0)
        df_bad = pd.DataFrame({"close": [1.0]})

        # Monkeypatch get_signal to use our dataframes
        call_count = [0]
        orig = engine.get_signal
        def mock_get_signal(ticker, df=None):
            call_count[0] += 1
            if ticker == "GOOD":
                return orig("GOOD", df=df_good)
            return orig("BAD", df=df_bad)

        engine.get_signal = mock_get_signal
        results = engine.get_signals(["GOOD", "BAD"])
        assert len(results) == 1
        assert results[0]["ticker"] == "GOOD"
