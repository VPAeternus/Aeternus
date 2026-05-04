# tests/test_phase3_modules.py
"""
Comprehensive tests for phase_engine modules:
  - cc_overbought.py   (SMA3 acceleration state machine)
  - index_overlay.py   (Index signal engine for QQQ/SPY)
  - config.py          (Configuration constants)
"""

import sys
import types
import pytest
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from unittest.mock import MagicMock

# Stub chromadb before it can be imported (pydantic v1 incompatible with Python 3.14)
if "chromadb" not in sys.modules or not hasattr(sys.modules.get("chromadb", None), "__path__"):
    _stub = types.ModuleType("chromadb")
    _stub.__path__ = []
    _stub.Client = None
    _config_stub = types.ModuleType("chromadb.config")
    _config_stub.Settings = type("Settings", (), {})
    sys.modules["chromadb"] = _stub
    sys.modules["chromadb.config"] = _config_stub


# ─────────────────────────────────────────────────────────────────────────────
# Synthetic DataFrame Factory
# ─────────────────────────────────────────────────────────────────────────────

def _make_price_df(n=600, trend="up", start_price=100.0, vix_level=18.0):
    """
    Build a DataFrame with all columns that data_engine.load() returns.
    
    Columns:
      date, open, high, low, close, volume,
      sma3, sma10, sma20, sma50, sma200,
      vix, slope_10, slope_20, vol_sma20,
      adr_14, adr_pct, fvg_bull, fvg_bear, fvg_ratio
    
    Args:
        n: number of bars
        trend: "up" (clean uptrend), "down" (downtrend), "flat" (oscillating)
        start_price: starting close price
        vix_level: constant VIX value for simplicity
    
    Returns:
        pd.DataFrame with date index and all indicator columns
    """
    dates = [datetime(2023, 1, 1) + timedelta(days=i) for i in range(n)]
    
    # Generate price based on trend
    if trend == "up":
        # Clean uptrend: each bar slightly higher
        close = start_price + np.arange(n) * 0.5
        close = close + np.random.normal(0, 0.3, n)
    elif trend == "down":
        # Downtrend: each bar slightly lower
        close = start_price - np.arange(n) * 0.3
        close = close + np.random.normal(0, 0.3, n)
    else:  # "flat"
        # Oscillating around starting price
        close = start_price + np.sin(np.arange(n) * 0.1) * 2
        close = close + np.random.normal(0, 0.2, n)
    
    close = np.maximum(close, 10.0)  # Prevent negative prices
    
    df = pd.DataFrame({
        "date": dates,
        "open": close + np.random.normal(-0.5, 0.3, n),
        "high": close + np.abs(np.random.normal(0.5, 0.3, n)),
        "low": close - np.abs(np.random.normal(0.5, 0.3, n)),
        "close": close,
        "volume": np.random.uniform(1e6, 5e6, n),
    })
    
    # Compute SMAs (these are critical for the engines)
    df["sma3"] = df["close"].rolling(3).mean()
    df["sma10"] = df["close"].rolling(10).mean()
    df["sma20"] = df["close"].rolling(20).mean()
    df["sma50"] = df["close"].rolling(50).mean()
    df["sma200"] = df["close"].rolling(200).mean()
    
    # Compute slope indicators
    sma10_slope = (df["sma10"] - df["sma10"].shift(5)) / (df["close"] * 5)
    sma20_slope = (df["sma20"] - df["sma20"].shift(5)) / (df["close"] * 5)
    df["slope_10"] = sma10_slope - sma10_slope.shift(5)
    df["slope_20"] = sma20_slope - sma20_slope.shift(5)
    
    # VIX and VIX moving averages
    df["vix"] = vix_level + np.random.normal(0, 1.0, n)
    df["vix"] = np.maximum(df["vix"], 5.0)
    df["vix_sma10"] = df["vix"].rolling(10).mean()
    df["vix_sma20"] = df["vix"].rolling(20).mean()
    
    # Volume indicators
    df["vol_sma20"] = df["volume"].rolling(20).mean()
    
    # ADR (Average Daily Range) indicators
    df["adr_14"] = (df["high"] - df["low"]).rolling(14).mean()
    df["adr_pct"] = (df["high"] - df["low"]) / df["close"] * 100
    
    # FVG (Fair Value Gap) indicators
    df["fvg_bull"] = 0.0
    df["fvg_bear"] = 0.0
    df["fvg_ratio"] = 0.0
    
    return df.reset_index(drop=True)


# ─────────────────────────────────────────────────────────────────────────────
# Tests for config.py
# ─────────────────────────────────────────────────────────────────────────────

class TestConfig:
    """Test configuration constants are properly defined."""
    
    def test_import(self):
        """Test that config module imports without error."""
        from tradingagents.phase_engine import config
        assert config is not None
    
    def test_universe_is_list(self):
        """Test UNIVERSE is a list of strings."""
        from tradingagents.phase_engine import config
        assert isinstance(config.UNIVERSE, list)
        assert len(config.UNIVERSE) > 0
        assert all(isinstance(t, str) for t in config.UNIVERSE)
    
    def test_universe_contains_indices(self):
        """Test UNIVERSE includes QQQ and SPY."""
        from tradingagents.phase_engine import config
        assert "QQQ" in config.UNIVERSE
        assert "SPY" in config.UNIVERSE
    
    def test_start_date_format(self):
        """Test START_DATE is a valid ISO date string."""
        from tradingagents.phase_engine import config
        assert isinstance(config.START_DATE, str)
        # Should parse as date without error
        pd.to_datetime(config.START_DATE)
    
    def test_numeric_constants_positive(self):
        """Test numeric parameters are positive."""
        from tradingagents.phase_engine import config
        assert config.CACHE_STALE_DAYS > 0
        assert config.WARMUP_DAYS > 0
        assert config.ADR_WINDOW > 0
        assert config.VOLUME_AVG_WINDOW > 0
        assert config.SMA_SLOPE_LOOKBACK > 0
    
    def test_percentile_bounds(self):
        """Test percentile parameters are valid (0-100)."""
        from tradingagents.phase_engine import config
        assert 0 <= config.MARKUP_PERCENTILE <= 100
        assert 0 <= config.MARKDN_PERCENTILE <= 100
        assert config.MARKDN_PERCENTILE < config.MARKUP_PERCENTILE
    
    def test_index_tickers_constant(self):
        """Test INDEX_TICKERS includes expected indices."""
        from tradingagents.phase_engine import config
        assert isinstance(config.INDEX_TICKERS, set)
        assert "QQQ" in config.INDEX_TICKERS
        assert "SPY" in config.INDEX_TICKERS
    
    def test_metals_configuration(self):
        """Test metals subsystem constants."""
        from tradingagents.phase_engine import config
        assert config.METALS_LEADER == "GLD"
        assert isinstance(config.METALS_TICKERS, set)
        assert "GLD" in config.METALS_TICKERS


# ─────────────────────────────────────────────────────────────────────────────
# Tests for cc_overbought.py
# ─────────────────────────────────────────────────────────────────────────────

class TestCCOverboughtEngine:
    """Test the SMA3 acceleration CC overbought state machine."""

    def test_import(self):
        """Test that cc_overbought module imports without error."""
        from tradingagents.phase_engine.cc_overbought import CCOverboughtEngine
        assert CCOverboughtEngine is not None

    def test_classification_above_both(self):
        """Test _classify_regime returns ABOVE_BOTH when price > both SMAs."""
        from tradingagents.phase_engine.cc_overbought import _classify_regime

        # Price above both SMAs
        regime = _classify_regime(close=110.0, sma50=100.0, sma200=95.0)
        assert regime == "ABOVE_BOTH"

    def test_classification_above_200_below_50(self):
        """Test regime classification when between SMAs."""
        from tradingagents.phase_engine.cc_overbought import _classify_regime

        regime = _classify_regime(close=105.0, sma50=110.0, sma200=100.0)
        assert regime == "ABOVE_200_BELOW_50"

    def test_classification_below_200_above_50(self):
        """Test regime classification when below 200 but above 50."""
        from tradingagents.phase_engine.cc_overbought import _classify_regime

        regime = _classify_regime(close=85.0, sma50=80.0, sma200=100.0)
        assert regime == "BELOW_200_ABOVE_50"

    def test_classification_below_both(self):
        """Test regime classification when below both SMAs."""
        from tradingagents.phase_engine.cc_overbought import _classify_regime

        regime = _classify_regime(close=85.0, sma50=95.0, sma200=100.0)
        assert regime == "BELOW_BOTH"

    def test_compute_accel_returns_series(self):
        """Test _compute_accel returns a pandas Series."""
        from tradingagents.phase_engine.cc_overbought import _compute_accel

        df = _make_price_df(n=300)
        accel = _compute_accel(df)

        assert isinstance(accel, pd.Series)
        assert len(accel) == len(df)

    def test_engine_initialization(self):
        """Test CCOverboughtEngine initializes with parameters."""
        from tradingagents.phase_engine.cc_overbought import CCOverboughtEngine

        engine = CCOverboughtEngine(holdout=3, warmup=252)
        assert engine.holdout == 3
        assert engine.warmup == 252

    def test_get_signal_returns_dict_with_required_keys(self):
        """Test get_signal returns dict with all required keys on valid data."""
        df = _make_price_df(n=600, trend="up")

        # Mock data_engine via sys.modules before importing
        mock_data_engine = MagicMock()
        mock_data_engine.load = MagicMock(return_value=df)
        sys.modules["tradingagents.phase_engine.data_engine"] = mock_data_engine

        # Now import and use
        from tradingagents.phase_engine.cc_overbought import CCOverboughtEngine
        engine = CCOverboughtEngine()
        signal = engine.get_signal("AAPL")

        assert isinstance(signal, dict)
        assert "ticker" in signal
        assert "state" in signal
        assert "regime" in signal
        assert "accel_percentile" in signal
        assert "invested_pct" in signal
        assert "close" in signal
        assert "sma3" in signal
        assert "sma50" in signal
        assert "sma200" in signal

    def test_state_is_long_or_cash(self):
        """Test that state is either 'long' or 'cash'."""
        df = _make_price_df(n=600, trend="up")
        mock_data_engine = MagicMock()
        mock_data_engine.load = MagicMock(return_value=df)
        sys.modules["tradingagents.phase_engine.data_engine"] = mock_data_engine

        from tradingagents.phase_engine.cc_overbought import CCOverboughtEngine
        engine = CCOverboughtEngine()
        signal = engine.get_signal("AAPL")

        assert signal["state"] in ("long", "cash")

    def test_regime_valid_values(self):
        """Test that regime is one of four valid values."""
        df = _make_price_df(n=600, trend="up")
        mock_data_engine = MagicMock()
        mock_data_engine.load = MagicMock(return_value=df)
        sys.modules["tradingagents.phase_engine.data_engine"] = mock_data_engine

        from tradingagents.phase_engine.cc_overbought import CCOverboughtEngine
        engine = CCOverboughtEngine()
        signal = engine.get_signal("AAPL")

        valid_regimes = {"ABOVE_BOTH", "ABOVE_200_BELOW_50", "BELOW_200_ABOVE_50", "BELOW_BOTH"}
        assert signal["regime"] in valid_regimes

    def test_invested_pct_in_range(self):
        """Test that invested_pct is between 0 and 100."""
        df = _make_price_df(n=600, trend="up")
        mock_data_engine = MagicMock()
        mock_data_engine.load = MagicMock(return_value=df)
        sys.modules["tradingagents.phase_engine.data_engine"] = mock_data_engine

        from tradingagents.phase_engine.cc_overbought import CCOverboughtEngine
        engine = CCOverboughtEngine()
        signal = engine.get_signal("AAPL")

        assert isinstance(signal["invested_pct"], (int, float))
        assert 0 <= signal["invested_pct"] <= 100

    def test_graceful_failure_on_bad_ticker(self):
        """Test that get_signal returns {} on failure."""
        def mock_load(ticker):
            return None  # Simulate missing data

        mock_data_engine = MagicMock()
        mock_data_engine.load = mock_load
        sys.modules["tradingagents.phase_engine.data_engine"] = mock_data_engine

        from tradingagents.phase_engine.cc_overbought import CCOverboughtEngine
        engine = CCOverboughtEngine()
        signal = engine.get_signal("INVALID")

        assert signal == {}

    def test_index_tickers_return_empty(self):
        """CCOverbought is stock-only; index ETFs should return no signal."""
        df = _make_price_df(n=600, trend="up")
        mock_data_engine = MagicMock()
        mock_data_engine.load = MagicMock(return_value=df)
        sys.modules["tradingagents.phase_engine.data_engine"] = mock_data_engine

        from tradingagents.phase_engine.cc_overbought import CCOverboughtEngine
        engine = CCOverboughtEngine()

        assert engine.get_signal("QQQ") == {}
        assert engine.get_signal("SPY") == {}
        assert engine.get_signal("IWM") == {}

    def test_get_signals_skips_failures(self):
        """Test get_signals filters out empty signals."""
        df_good = _make_price_df(n=600, trend="up")

        def mock_load(ticker):
            if ticker == "GOOD":
                return df_good
            return None  # Simulate failure for "BAD"

        mock_data_engine = MagicMock()
        mock_data_engine.load = mock_load
        sys.modules["tradingagents.phase_engine.data_engine"] = mock_data_engine

        from tradingagents.phase_engine.cc_overbought import CCOverboughtEngine
        engine = CCOverboughtEngine()
        results = engine.get_signals(["GOOD", "BAD", "GOOD"])

        # Should only include successful signals
        assert len(results) > 0
        for sig in results:
            assert sig.get("ticker") is not None


# ─────────────────────────────────────────────────────────────────────────────
# Tests for index_overlay.py
# ─────────────────────────────────────────────────────────────────────────────

class TestIndexOverlayEngine:
    """Test the Index Overlay signal engine."""
    
    def test_import(self):
        """Test that index_overlay module imports without error."""
        from tradingagents.phase_engine.index_overlay import IndexOverlayEngine
        assert IndexOverlayEngine is not None
    
    def test_engine_initialization(self):
        """Test IndexOverlayEngine initializes."""
        from tradingagents.phase_engine.index_overlay import IndexOverlayEngine
        
        engine = IndexOverlayEngine()
        assert engine.INDEX_TICKERS == {"QQQ", "SPY"}
    
    def test_non_index_returns_empty(self):
        """Test get_signal returns {} for non-index tickers."""
        df = _make_price_df(n=600)
        mock_data_engine = MagicMock()
        mock_data_engine.load = MagicMock(return_value=df)
        sys.modules["tradingagents.phase_engine.data_engine"] = mock_data_engine
        
        from tradingagents.phase_engine.index_overlay import IndexOverlayEngine
        engine = IndexOverlayEngine()
        signal = engine.get_signal("AAPL")
        
        # Non-index tickers should return empty dict
        assert signal == {}
    
    def test_get_signal_required_keys_qqq(self):
        """Test get_signal returns all required keys for QQQ."""
        df = _make_price_df(n=600, trend="up", vix_level=18.0)
        mock_data_engine = MagicMock()
        mock_data_engine.load = MagicMock(return_value=df)
        sys.modules["tradingagents.phase_engine.data_engine"] = mock_data_engine
        
        from tradingagents.phase_engine.index_overlay import IndexOverlayEngine
        engine = IndexOverlayEngine()
        signal = engine.get_signal("QQQ")
        
        assert isinstance(signal, dict)
        assert "ticker" in signal
        assert "date" in signal
        assert "rth" in signal
        assert "overnight" in signal
        assert "active_leg" in signal
        assert "leg1" in signal
        assert "leg2" in signal
        assert "leg3" in signal
        assert "vix" in signal
        assert "regime" in signal
        assert "close" in signal
        assert "sma10" in signal
        assert "sma20" in signal
    
    def test_get_signal_required_keys_spy(self):
        """Test get_signal returns keys for SPY."""
        df = _make_price_df(n=600, trend="up", vix_level=18.0)
        mock_data_engine = MagicMock()
        mock_data_engine.load = MagicMock(return_value=df)
        sys.modules["tradingagents.phase_engine.data_engine"] = mock_data_engine
        
        from tradingagents.phase_engine.index_overlay import IndexOverlayEngine
        engine = IndexOverlayEngine()
        signal = engine.get_signal("SPY")
        
        assert signal != {}
        assert signal["ticker"] == "SPY"
    
    def test_leg_values_are_boolean(self):
        """Test that leg1, leg2, leg3, rth, overnight are booleans."""
        df = _make_price_df(n=600, trend="up")
        mock_data_engine = MagicMock()
        mock_data_engine.load = MagicMock(return_value=df)
        sys.modules["tradingagents.phase_engine.data_engine"] = mock_data_engine
        
        from tradingagents.phase_engine.index_overlay import IndexOverlayEngine
        engine = IndexOverlayEngine()
        signal = engine.get_signal("QQQ")
        
        assert isinstance(signal["leg1"], bool)
        assert isinstance(signal["leg2"], bool)
        assert isinstance(signal["leg3"], bool)
        assert isinstance(signal["rth"], bool)
        assert isinstance(signal["overnight"], bool)
    
    def test_overnight_active_normal_conditions(self):
        """Test overnight is True under normal VIX conditions."""
        df = _make_price_df(n=600, trend="up", vix_level=18.0)
        # Set normal conditions (no skip conditions)
        df.loc[len(df)-2, "vix"] = 18.0
        
        mock_data_engine = MagicMock()
        mock_data_engine.load = MagicMock(return_value=df)
        sys.modules["tradingagents.phase_engine.data_engine"] = mock_data_engine
        
        from tradingagents.phase_engine.index_overlay import IndexOverlayEngine
        engine = IndexOverlayEngine()
        signal = engine.get_signal("QQQ")
        
        # Under normal conditions, overnight should be True
        assert signal["overnight"] is True
    
    def test_get_signals_filters_to_index_tickers(self):
        """Test get_signals only returns signals for index tickers."""
        df = _make_price_df(n=600)
        mock_data_engine = MagicMock()
        mock_data_engine.load = MagicMock(return_value=df)
        sys.modules["tradingagents.phase_engine.data_engine"] = mock_data_engine
        
        from tradingagents.phase_engine.index_overlay import IndexOverlayEngine
        engine = IndexOverlayEngine()
        signals = engine.get_signals(["AAPL", "QQQ", "SPY", "MSFT"])
        
        # Should only return QQQ and SPY
        tickers = {sig["ticker"] for sig in signals}
        assert tickers <= {"QQQ", "SPY"}
    
    def test_get_signals_all_indices(self):
        """Test get_signals with no filter returns both index signals."""
        df = _make_price_df(n=600)
        mock_data_engine = MagicMock()
        mock_data_engine.load = MagicMock(return_value=df)
        sys.modules["tradingagents.phase_engine.data_engine"] = mock_data_engine
        
        from tradingagents.phase_engine.index_overlay import IndexOverlayEngine
        engine = IndexOverlayEngine()
        signals = engine.get_signals()
        
        # Should return signals for both QQQ and SPY
        tickers = {sig["ticker"] for sig in signals}
        assert len(tickers) == 2
        assert "QQQ" in tickers
        assert "SPY" in tickers
    
    def test_compute_accel_regime_returns_series(self):
        """Test _compute_accel_regime returns a pandas Series."""
        from tradingagents.phase_engine.index_overlay import IndexOverlayEngine
        
        df = _make_price_df(n=300)
        engine = IndexOverlayEngine()
        regime = engine._compute_accel_regime(df)
        
        assert isinstance(regime, pd.Series)
        assert len(regime) == len(df)
    
    def test_regime_values_are_valid(self):
        """Test that regime values are valid strings."""
        from tradingagents.phase_engine.index_overlay import IndexOverlayEngine
        
        df = _make_price_df(n=300)
        engine = IndexOverlayEngine()
        regime = engine._compute_accel_regime(df)
        
        valid_regimes = {"accel_dn", "accel_up", "neutral"}
        for val in regime.dropna():
            assert val in valid_regimes
    
    def test_active_leg_priority(self):
        """Test active_leg is one of the valid values."""
        df = _make_price_df(n=600, trend="up", vix_level=25.0)
        
        mock_data_engine = MagicMock()
        mock_data_engine.load = MagicMock(return_value=df)
        sys.modules["tradingagents.phase_engine.data_engine"] = mock_data_engine
        
        from tradingagents.phase_engine.index_overlay import IndexOverlayEngine
        engine = IndexOverlayEngine()
        signal = engine.get_signal("QQQ")
        
        # active_leg should be one of the valid strings or None
        valid_legs = {"leg1_dip_buy", "leg2_stay_long", "leg3_uptrend_decel", None}
        assert signal["active_leg"] in valid_legs
    
    def test_check_legs_returns_all_keys(self):
        """Test _check_legs returns dict with all leg and RTH keys."""
        df = _make_price_df(n=600)
        from tradingagents.phase_engine.index_overlay import IndexOverlayEngine
        
        engine = IndexOverlayEngine()
        legs = engine._check_legs(df)
        
        assert isinstance(legs, dict)
        assert "leg1" in legs
        assert "leg2" in legs
        assert "leg3" in legs
        assert "rth" in legs
        assert "overnight" in legs


# ─────────────────────────────────────────────────────────────────────────────
# Integration Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestCoveredCallScanner:
    """Tests for CoveredCallScanner (cc_scanner.py)."""

    def test_import(self):
        """Test that cc_scanner module imports without error."""
        from tradingagents.phase_engine.cc_scanner import CoveredCallScanner
        assert CoveredCallScanner is not None

    def test_convenience_function_import(self):
        """Test module-level convenience function imports."""
        from tradingagents.phase_engine.cc_scanner import get_cc_signals
        assert callable(get_cc_signals)

    def test_init(self):
        """Test CoveredCallScanner initializes."""
        from tradingagents.phase_engine.cc_scanner import CoveredCallScanner
        scanner = CoveredCallScanner(live=False)
        assert scanner.live is False

    def test_cc_overbought_signal_fires(self):
        """Test that cc_overbought exit triggers a cc_overbought signal."""
        from tradingagents.phase_engine.cc_scanner import CoveredCallScanner

        scanner = CoveredCallScanner(live=False)
        # Patch the regime engine to return an overbought exit
        scanner._regime_engine = MagicMock()
        scanner._regime_engine.get_signal = MagicMock(return_value={
            "ticker": "TSLA",
            "state": "cash",
            "last_exit_type": "overbought",
            "close": 250.0,
            "regime": "ABOVE_BOTH",
            "accel_percentile": 0.92,
            "date": "2026-02-28",
        })
        scanner._index_engine = MagicMock()
        scanner._index_engine.get_signal = MagicMock(return_value={})

        signals = scanner.get_signals(tickers=["TSLA"])
        assert len(signals) == 1
        assert signals[0]["signal_type"] == "cc_overbought"
        assert signals[0]["signal_detail"] == "overbought"
        assert signals[0]["ticker"] == "TSLA"
        assert signals[0]["close"] == 250.0

    def test_cc_overbought_long_state_no_signal(self):
        """Test that cc_overbought state 'long' does NOT fire a signal."""
        from tradingagents.phase_engine.cc_scanner import CoveredCallScanner

        scanner = CoveredCallScanner(live=False)
        scanner._regime_engine = MagicMock()
        scanner._regime_engine.get_signal = MagicMock(return_value={
            "ticker": "AAPL",
            "state": "long",
            "last_exit_type": "",
            "close": 180.0,
            "regime": "ABOVE_BOTH",
            "date": "2026-02-28",
        })
        scanner._index_engine = MagicMock()
        scanner._index_engine.get_signal = MagicMock(return_value={})

        signals = scanner.get_signals(tickers=["AAPL"])
        # state == "long" should NOT produce cc_overbought signal
        cc_ob_signals = [s for s in signals if s.get("signal_type") == "cc_overbought"]
        assert len(cc_ob_signals) == 0

    def test_v3_rth_skip_signal(self):
        """Test that V3 RTH skip fires v3_rth_skip signal for QQQ."""
        from tradingagents.phase_engine.cc_scanner import CoveredCallScanner

        scanner = CoveredCallScanner(live=False)
        scanner._regime_engine = MagicMock()
        scanner._index_engine = MagicMock()
        scanner._index_engine.get_signal = MagicMock(return_value={
            "ticker": "QQQ",
            "rth": False,
            "overnight": True,
            "active_leg": "leg2_stay_long",
            "close": 520.0,
            "date": "2026-02-28",
        })

        signals = scanner.get_signals(tickers=["QQQ"])
        assert len(signals) == 1
        assert signals[0]["signal_type"] == "v3_rth_skip"
        assert signals[0]["signal_detail"] == "rth_skip"
        assert signals[0]["ticker"] == "QQQ"

    def test_v3_rth_active_no_signal(self):
        """Test that V3 RTH active does NOT fire v3_rth_skip signal."""
        from tradingagents.phase_engine.cc_scanner import CoveredCallScanner

        scanner = CoveredCallScanner(live=False)
        scanner._regime_engine = MagicMock()
        scanner._index_engine = MagicMock()
        scanner._index_engine.get_signal = MagicMock(return_value={
            "ticker": "QQQ",
            "rth": True,
            "overnight": True,
            "close": 520.0,
            "date": "2026-02-28",
        })

        signals = scanner.get_signals(tickers=["QQQ"])
        assert len(signals) == 0

    def test_max_signals_cap(self):
        """Test that max_signals caps the output."""
        from tradingagents.phase_engine.cc_scanner import CoveredCallScanner

        scanner = CoveredCallScanner(live=False)
        # Return overbought exit for every ticker
        scanner._regime_engine = MagicMock()
        scanner._regime_engine.get_signal = MagicMock(side_effect=lambda t: {
            "ticker": t,
            "state": "cash",
            "last_exit_type": "overbought",
            "close": 100.0,
            "regime": "ABOVE_BOTH",
            "accel_percentile": 0.91,
            "date": "2026-02-28",
        })
        scanner._index_engine = MagicMock()
        scanner._index_engine.get_signal = MagicMock(return_value={})

        tickers = [f"T{i}" for i in range(20)]
        signals = scanner.get_signals(tickers=tickers, max_signals=3)
        assert len(signals) == 3

    def test_build_cc_recommendations(self):
        """Test build_cc_recommendations formats signals."""
        from tradingagents.phase_engine.cc_scanner import CoveredCallScanner

        scanner = CoveredCallScanner()
        recs = scanner.build_cc_recommendations([
            {"ticker": "TSLA", "signal_type": "cc_overbought", "signal_detail": "overbought",
             "close": 250.0, "regime": "ABOVE_BOTH", "date": "2026-02-28", "extra": "ignored"},
        ])
        assert len(recs) == 1
        assert recs[0]["ticker"] == "TSLA"
        assert "extra" not in recs[0]

    def test_graceful_failure(self):
        """Test that scanner returns [] on exception."""
        from tradingagents.phase_engine.cc_scanner import CoveredCallScanner

        scanner = CoveredCallScanner(live=False)
        scanner._regime_engine = MagicMock()
        scanner._regime_engine.get_signal = MagicMock(side_effect=RuntimeError("boom"))
        scanner._index_engine = MagicMock()
        scanner._index_engine.get_signal = MagicMock(side_effect=RuntimeError("boom"))

        # Should not raise, returns []
        signals = scanner.get_signals(tickers=["AAPL", "QQQ"])
        assert signals == []

    def test_get_cc_signals_convenience(self):
        """Test module-level get_cc_signals convenience function."""
        from tradingagents.phase_engine.cc_scanner import get_cc_signals
        # Should not raise even with no data
        result = get_cc_signals(tickers=[], max_signals=5)
        assert isinstance(result, list)


class TestPhaseEngineIntegration:
    """Integration tests across multiple modules."""

    def test_cc_overbought_and_index_overlay_compatible(self):
        """Test that cc_overbought and index_overlay can coexist with same mock."""
        df = _make_price_df(n=600, trend="up")

        # Both modules use data_engine.load — ensure they work together
        mock_data_engine = MagicMock()
        mock_data_engine.load = MagicMock(return_value=df)
        sys.modules["tradingagents.phase_engine.data_engine"] = mock_data_engine

        from tradingagents.phase_engine.cc_overbought import CCOverboughtEngine
        from tradingagents.phase_engine.index_overlay import IndexOverlayEngine

        cc_engine = CCOverboughtEngine()
        index_engine = IndexOverlayEngine()

        cc_sig = cc_engine.get_signal("AAPL")
        index_sig = index_engine.get_signal("QQQ")

        assert cc_sig != {}
        assert index_sig != {}

    def test_config_used_by_cc_overbought(self):
        """Test that cc_overbought uses config.UNIVERSE."""
        from tradingagents.phase_engine.cc_overbought import get_cc_overbought_signals
        from tradingagents.phase_engine import config

        # This would fail if config.UNIVERSE is not properly defined
        assert len(config.UNIVERSE) > 0
        assert hasattr(config, "UNIVERSE")


# ─────────────────────────────────────────────────────────────────────────────
# Instrument Resolution Tests (get_signal_for_instrument)
# ─────────────────────────────────────────────────────────────────────────────

class TestInstrumentResolution:
    """IndexOverlayEngine.get_signal_for_instrument resolves leveraged ETFs."""

    def test_tqqq_resolves_to_qqq(self):
        """TQQQ → QQQ underlying, returns QQQ signal."""
        from tradingagents.phase_engine.index_overlay import IndexOverlayEngine

        df = _make_price_df(n=600, trend="up", vix_level=12.0)

        mock_data_engine = types.ModuleType("tradingagents.phase_engine.data_engine")
        mock_data_engine.load = MagicMock(return_value=df)
        sys.modules["tradingagents.phase_engine.data_engine"] = mock_data_engine

        engine = IndexOverlayEngine()
        sig = engine.get_signal_for_instrument("TQQQ")

        assert sig != {}, "TQQQ should resolve to QQQ and produce a signal"
        assert sig["ticker"] == "QQQ"
        assert sig["is_index"] is True

    def test_qqq_passthrough(self):
        """QQQ passes through unchanged."""
        from tradingagents.phase_engine.index_overlay import IndexOverlayEngine

        df = _make_price_df(n=600, trend="up", vix_level=12.0)

        mock_data_engine = types.ModuleType("tradingagents.phase_engine.data_engine")
        mock_data_engine.load = MagicMock(return_value=df)
        sys.modules["tradingagents.phase_engine.data_engine"] = mock_data_engine

        engine = IndexOverlayEngine()
        sig = engine.get_signal_for_instrument("QQQ")

        assert sig != {}
        assert sig["ticker"] == "QQQ"

    def test_unknown_ticker_returns_empty(self):
        """Unknown ticker not in INDEX_TICKERS or INSTRUMENT_UNDERLYING → {}."""
        from tradingagents.phase_engine.index_overlay import IndexOverlayEngine

        engine = IndexOverlayEngine()
        sig = engine.get_signal_for_instrument("AAPL")

        assert sig == {}
