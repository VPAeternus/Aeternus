"""Tests for tradingagents.agents.utils.momentum_engine"""

import sys
import types
import numpy as np
import pandas as pd
import pytest

# Stub chromadb before it can be imported (pydantic v1 incompatible with Python 3.14)
if "chromadb" not in sys.modules or not hasattr(sys.modules.get("chromadb", None), "__path__"):
    _stub = types.ModuleType("chromadb")
    _stub.__path__ = []  # make it look like a package
    _stub.Client = None
    _config_stub = types.ModuleType("chromadb.config")
    _config_stub.Settings = type("Settings", (), {})
    sys.modules["chromadb"] = _stub
    sys.modules["chromadb.config"] = _config_stub

from tradingagents.agents.utils.momentum_engine import (
    build_momentum_snapshot,
    get_regime_state,
    _clamp,
    _compute_accel,
    _score_trend_strength,
    _score_momentum_health,
    _score_regime_quality,
    _score_volume_confirmation,
    _regime_label,
    _run_cc_overbought_window,
)


# ============================================================================
# Synthetic Data Factory
# ============================================================================

def _make_df(n_bars=600, trend="up", base_price=100.0):
    """
    Build a realistic DataFrame with all required columns.
    
    trend="up": price starts at base_price, ends around base_price * 1.8
    trend="down": price starts at base_price, ends around base_price * 0.6
    trend="flat": price oscillates around base_price
    """
    dates = pd.date_range(end="2026-02-23", periods=n_bars, freq="D")
    
    # Generate base price series based on trend
    if trend == "up":
        # Clean uptrend with slight noise
        slope = (base_price * 1.8 - base_price) / n_bars
        prices = [base_price + slope * i + np.random.normal(0, base_price * 0.005) for i in range(n_bars)]
    elif trend == "down":
        # Downtrend
        slope = (base_price * 0.6 - base_price) / n_bars
        prices = [base_price + slope * i + np.random.normal(0, base_price * 0.005) for i in range(n_bars)]
    else:  # flat
        # Oscillation around base
        prices = [base_price + np.random.normal(0, base_price * 0.02) for _ in range(n_bars)]
    
    close = np.array(prices)
    open_ = close + np.random.normal(0, base_price * 0.01, n_bars)
    high = close + np.abs(np.random.normal(base_price * 0.01, base_price * 0.008, n_bars))
    low = close - np.abs(np.random.normal(base_price * 0.01, base_price * 0.008, n_bars))
    volume = np.random.uniform(1e6, 5e6, n_bars)
    
    # Compute SMAs
    df = pd.DataFrame({
        "date": dates,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })
    
    df["sma3"] = df["close"].rolling(window=3, min_periods=1).mean()
    df["sma10"] = df["close"].rolling(window=10, min_periods=1).mean()
    df["sma20"] = df["close"].rolling(window=20, min_periods=1).mean()
    df["sma50"] = df["close"].rolling(window=50, min_periods=1).mean()
    df["sma200"] = df["close"].rolling(window=200, min_periods=1).mean()
    
    # Volume SMA
    df["vol_sma20"] = df["volume"].rolling(window=20, min_periods=1).mean()
    
    # Dummy columns (not used in tests but might be in engine)
    df["vix"] = 20.0
    df["slope_10"] = 0.1
    df["slope_20"] = 0.1
    df["adr_14"] = 1.5
    df["adr_pct"] = 0.015
    df["fvg_bull"] = 0
    df["fvg_bear"] = 0
    df["fvg_ratio"] = 0.5
    
    return df.reset_index(drop=True)


# ============================================================================
# Tests: Import & Existence
# ============================================================================

def test_import():
    """build_momentum_snapshot and get_regime_state are importable"""
    assert callable(build_momentum_snapshot)
    assert callable(get_regime_state)


# ============================================================================
# Tests: build_momentum_snapshot Return Structure
# ============================================================================

def test_returns_dict_with_required_keys(monkeypatch):
    """build_momentum_snapshot returns dict with all required top-level keys"""
    df = _make_df(n_bars=600, trend="up")
    
    mock_de = type("MockDE", (), {
        "load": staticmethod(lambda ticker: df)
    })()
    
    monkeypatch.setattr(
        "tradingagents.phase_engine.data_engine",
        mock_de,
        raising=False
    )
    
    result = build_momentum_snapshot("FAKE")
    
    assert isinstance(result, dict)
    assert "regime" in result
    assert "signal_state" in result
    assert "accel_percentile" in result
    assert "accel_value" in result
    assert "invested_pct_2y" in result
    assert "days_of_history" in result
    assert "subscores" in result
    assert "composite_score" in result
    assert "direction" in result
    assert "data_coverage" in result


def test_subscores_dict_structure(monkeypatch):
    """subscores dict has all four required keys"""
    df = _make_df(n_bars=600, trend="up")
    
    mock_de = type("MockDE", (), {
        "load": staticmethod(lambda ticker: df)
    })()
    
    monkeypatch.setattr(
        "tradingagents.phase_engine.data_engine",
        mock_de,
        raising=False
    )
    
    result = build_momentum_snapshot("FAKE")
    
    subscores = result["subscores"]
    assert isinstance(subscores, dict)
    assert "trend_strength" in subscores
    assert "momentum_health" in subscores
    assert "regime_quality" in subscores
    assert "volume_confirmation" in subscores


# ============================================================================
# Tests: Value Constraints
# ============================================================================

def test_subscores_are_clamped_0_100(monkeypatch):
    """All four subscores are in [0, 100]"""
    df = _make_df(n_bars=600, trend="up")
    
    mock_de = type("MockDE", (), {
        "load": staticmethod(lambda ticker: df)
    })()
    
    monkeypatch.setattr(
        "tradingagents.phase_engine.data_engine",
        mock_de,
        raising=False
    )
    
    result = build_momentum_snapshot("FAKE")
    subscores = result["subscores"]
    
    assert 0 <= subscores["trend_strength"] <= 100
    assert 0 <= subscores["momentum_health"] <= 100
    assert 0 <= subscores["regime_quality"] <= 100
    assert 0 <= subscores["volume_confirmation"] <= 100


def test_composite_score_in_range(monkeypatch):
    """composite_score is int in [0, 100]"""
    df = _make_df(n_bars=600, trend="up")
    
    mock_de = type("MockDE", (), {
        "load": staticmethod(lambda ticker: df)
    })()
    
    monkeypatch.setattr(
        "tradingagents.phase_engine.data_engine",
        mock_de,
        raising=False
    )
    
    result = build_momentum_snapshot("FAKE")
    
    assert isinstance(result["composite_score"], (int, np.integer))
    assert 0 <= result["composite_score"] <= 100


def test_direction_valid_values(monkeypatch):
    """direction is one of BULLISH/NEUTRAL/BEARISH"""
    df = _make_df(n_bars=600, trend="up")
    
    mock_de = type("MockDE", (), {
        "load": staticmethod(lambda ticker: df)
    })()
    
    monkeypatch.setattr(
        "tradingagents.phase_engine.data_engine",
        mock_de,
        raising=False
    )
    
    result = build_momentum_snapshot("FAKE")
    
    assert result["direction"] in ["BULLISH", "NEUTRAL", "BEARISH"]


def test_regime_values_valid(monkeypatch):
    """regime is one of the four expected string values"""
    df = _make_df(n_bars=600, trend="up")
    
    mock_de = type("MockDE", (), {
        "load": staticmethod(lambda ticker: df)
    })()
    
    monkeypatch.setattr(
        "tradingagents.phase_engine.data_engine",
        mock_de,
        raising=False
    )
    
    result = build_momentum_snapshot("FAKE")
    
    assert result["regime"] in [
        "ABOVE_BOTH",
        "ABOVE_200_BELOW_50",
        "BELOW_200_ABOVE_50",
        "BELOW_BOTH"
    ]


def test_signal_state_valid_values(monkeypatch):
    """signal_state is either 'long' or 'cash'"""
    df = _make_df(n_bars=600, trend="up")
    
    mock_de = type("MockDE", (), {
        "load": staticmethod(lambda ticker: df)
    })()
    
    monkeypatch.setattr(
        "tradingagents.phase_engine.data_engine",
        mock_de,
        raising=False
    )
    
    result = build_momentum_snapshot("FAKE")
    
    assert result["signal_state"] in ["long", "cash"]


# ============================================================================
# Tests: Trend Direction Scenarios
# ============================================================================

def test_uptrend_is_bullish(monkeypatch):
    """Strong uptrend price data → direction BULLISH, high trend_strength"""
    df = _make_df(n_bars=600, trend="up")
    
    mock_de = type("MockDE", (), {
        "load": staticmethod(lambda ticker: df)
    })()
    
    monkeypatch.setattr(
        "tradingagents.phase_engine.data_engine",
        mock_de,
        raising=False
    )
    
    result = build_momentum_snapshot("FAKE")
    
    # Strong uptrend should be bullish
    assert result["direction"] == "BULLISH"
    # Price should be above both SMAs
    assert result["regime"] in ["ABOVE_BOTH", "ABOVE_200_BELOW_50"]
    # Trend strength should be high
    assert result["subscores"]["trend_strength"] > 65


def test_downtrend_is_bearish_or_neutral(monkeypatch):
    """Downtrend price data → direction BEARISH or NEUTRAL, low trend_strength"""
    df = _make_df(n_bars=600, trend="down")
    
    mock_de = type("MockDE", (), {
        "load": staticmethod(lambda ticker: df)
    })()
    
    monkeypatch.setattr(
        "tradingagents.phase_engine.data_engine",
        mock_de,
        raising=False
    )
    
    result = build_momentum_snapshot("FAKE")
    
    # Downtrend should not be bullish
    assert result["direction"] in ["BEARISH", "NEUTRAL"]
    # Trend strength should be lower
    assert result["subscores"]["trend_strength"] < 65


# ============================================================================
# Tests: Data Coverage Tiers
# ============================================================================

def test_data_coverage_insufficient_data(monkeypatch):
    """data_coverage = 0.0 for <252 bars"""
    df = _make_df(n_bars=200, trend="up")
    
    mock_de = type("MockDE", (), {
        "load": staticmethod(lambda ticker: df)
    })()
    
    monkeypatch.setattr(
        "tradingagents.phase_engine.data_engine",
        mock_de,
        raising=False
    )
    
    result = build_momentum_snapshot("FAKE")
    
    assert result["data_coverage"] == 0.0


def test_data_coverage_partial(monkeypatch):
    """data_coverage = 0.5 for 252-503 bars"""
    df = _make_df(n_bars=350, trend="up")
    
    mock_de = type("MockDE", (), {
        "load": staticmethod(lambda ticker: df)
    })()
    
    monkeypatch.setattr(
        "tradingagents.phase_engine.data_engine",
        mock_de,
        raising=False
    )
    
    result = build_momentum_snapshot("FAKE")
    
    assert result["data_coverage"] == 0.5


def test_data_coverage_full(monkeypatch):
    """data_coverage = 1.0 for 504+ bars"""
    df = _make_df(n_bars=600, trend="up")
    
    mock_de = type("MockDE", (), {
        "load": staticmethod(lambda ticker: df)
    })()
    
    monkeypatch.setattr(
        "tradingagents.phase_engine.data_engine",
        mock_de,
        raising=False
    )
    
    result = build_momentum_snapshot("FAKE")
    
    assert result["data_coverage"] == 1.0


def test_data_coverage_at_boundary_252(monkeypatch):
    """data_coverage = 0.5 at exactly 252 bars"""
    df = _make_df(n_bars=252, trend="up")
    
    mock_de = type("MockDE", (), {
        "load": staticmethod(lambda ticker: df)
    })()
    
    monkeypatch.setattr(
        "tradingagents.phase_engine.data_engine",
        mock_de,
        raising=False
    )
    
    result = build_momentum_snapshot("FAKE")
    
    assert result["data_coverage"] == 0.5


def test_data_coverage_at_boundary_504(monkeypatch):
    """data_coverage = 1.0 at exactly 504 bars"""
    df = _make_df(n_bars=504, trend="up")
    
    mock_de = type("MockDE", (), {
        "load": staticmethod(lambda ticker: df)
    })()
    
    monkeypatch.setattr(
        "tradingagents.phase_engine.data_engine",
        mock_de,
        raising=False
    )
    
    result = build_momentum_snapshot("FAKE")
    
    assert result["data_coverage"] == 1.0


# ============================================================================
# Tests: Error Handling
# ============================================================================

def test_graceful_degradation_on_bad_ticker(monkeypatch):
    """Returns {} when data_engine raises an exception"""
    def raise_error(ticker):
        raise Exception("Network error")
    
    mock_de = type("MockDE", (), {
        "load": staticmethod(raise_error)
    })()
    
    monkeypatch.setattr(
        "tradingagents.phase_engine.data_engine",
        mock_de,
        raising=False
    )
    
    result = build_momentum_snapshot("BADTICKER")
    
    assert result == {}


def test_graceful_degradation_on_none_dataframe(monkeypatch):
    """Returns {} when data_engine returns None"""
    mock_de = type("MockDE", (), {
        "load": staticmethod(lambda ticker: None)
    })()
    
    monkeypatch.setattr(
        "tradingagents.phase_engine.data_engine",
        mock_de,
        raising=False
    )
    
    result = build_momentum_snapshot("FAKE")
    
    assert result == {}


def test_graceful_degradation_on_empty_dataframe(monkeypatch):
    """Returns {} when data_engine returns empty DataFrame"""
    mock_de = type("MockDE", (), {
        "load": staticmethod(lambda ticker: pd.DataFrame())
    })()
    
    monkeypatch.setattr(
        "tradingagents.phase_engine.data_engine",
        mock_de,
        raising=False
    )
    
    result = build_momentum_snapshot("FAKE")
    
    assert result == {}


# ============================================================================
# Tests: trade_date Filter
# ============================================================================

def test_trade_date_filter(monkeypatch):
    """When trade_date provided, only uses data up to that date"""
    df = _make_df(n_bars=600, trend="up")
    
    mock_de = type("MockDE", (), {
        "load": staticmethod(lambda ticker: df)
    })()
    
    monkeypatch.setattr(
        "tradingagents.phase_engine.data_engine",
        mock_de,
        raising=False
    )
    
    # Get all data
    result_full = build_momentum_snapshot("FAKE")
    
    # Get data up to midpoint (simulate historical)
    mid_date = df.iloc[300]["date"].strftime("%Y-%m-%d")
    result_filtered = build_momentum_snapshot("FAKE", trade_date=mid_date)
    
    # Filtered should have fewer days
    assert result_filtered["days_of_history"] <= result_full["days_of_history"]


def test_trade_date_after_all_data(monkeypatch):
    """trade_date after all data returns full snapshot"""
    df = _make_df(n_bars=600, trend="up")
    
    mock_de = type("MockDE", (), {
        "load": staticmethod(lambda ticker: df)
    })()
    
    monkeypatch.setattr(
        "tradingagents.phase_engine.data_engine",
        mock_de,
        raising=False
    )
    
    result = build_momentum_snapshot("FAKE", trade_date="2099-12-31")
    
    # Should use all data
    assert result["days_of_history"] == 600


def test_trade_date_before_all_data(monkeypatch):
    """trade_date before all data returns empty"""
    df = _make_df(n_bars=600, trend="up")
    
    mock_de = type("MockDE", (), {
        "load": staticmethod(lambda ticker: df)
    })()
    
    monkeypatch.setattr(
        "tradingagents.phase_engine.data_engine",
        mock_de,
        raising=False
    )
    
    result = build_momentum_snapshot("FAKE", trade_date="2000-01-01")
    
    # No data before cutoff → returns {}
    assert result == {}


# ============================================================================
# Tests: get_regime_state
# ============================================================================

def test_get_regime_state_returns_dict(monkeypatch):
    """get_regime_state returns dict with required keys"""
    df = _make_df(n_bars=600, trend="up")
    
    mock_de = type("MockDE", (), {
        "load": staticmethod(lambda ticker: df)
    })()
    
    monkeypatch.setattr(
        "tradingagents.phase_engine.data_engine",
        mock_de,
        raising=False
    )
    
    result = get_regime_state("FAKE")
    
    assert isinstance(result, dict)
    assert "regime" in result
    assert "signal_state" in result
    assert "accel_percentile" in result


def test_get_regime_state_returns_subset(monkeypatch):
    """get_regime_state returns minimal subset (no subscores/composite)"""
    df = _make_df(n_bars=600, trend="up")
    
    mock_de = type("MockDE", (), {
        "load": staticmethod(lambda ticker: df)
    })()
    
    monkeypatch.setattr(
        "tradingagents.phase_engine.data_engine",
        mock_de,
        raising=False
    )
    
    result = get_regime_state("FAKE")
    
    # Should not have subscores or composite
    assert "subscores" not in result
    assert "composite_score" not in result
    assert "direction" not in result


def test_get_regime_state_graceful_degradation(monkeypatch):
    """get_regime_state returns {} on error"""
    def raise_error(ticker):
        raise Exception("Network error")
    
    mock_de = type("MockDE", (), {
        "load": staticmethod(raise_error)
    })()
    
    monkeypatch.setattr(
        "tradingagents.phase_engine.data_engine",
        mock_de,
        raising=False
    )
    
    result = get_regime_state("BADTICKER")
    
    assert result == {}


# ============================================================================
# Tests: Helper Functions
# ============================================================================

def test_clamp_below_range():
    """_clamp clamps values below lower bound"""
    assert _clamp(-10) == 0


def test_clamp_above_range():
    """_clamp clamps values above upper bound"""
    assert _clamp(150) == 100


def test_clamp_in_range():
    """_clamp preserves values in range"""
    assert _clamp(50) == 50


def test_clamp_custom_bounds():
    """_clamp respects custom bounds"""
    assert _clamp(-5, lo=-10, hi=10) == -5
    assert _clamp(15, lo=-10, hi=10) == 10


def test_compute_accel_returns_series():
    """_compute_accel returns pd.Series"""
    close = pd.Series([100, 101, 102, 103, 104])
    sma3 = pd.Series([100, 100.5, 101, 101.5, 102])
    result = _compute_accel(close, sma3)
    assert isinstance(result, pd.Series)
    assert len(result) == len(close)


def test_score_trend_strength_full_uptrend():
    """_score_trend_strength returns high score for full uptrend"""
    close = 150.0
    sma10 = 140.0
    sma20 = 130.0
    sma50 = 120.0
    sma200 = 100.0
    
    score = _score_trend_strength(close, sma10, sma20, sma50, sma200)
    
    assert 85 <= score <= 100


def test_score_trend_strength_full_downtrend():
    """_score_trend_strength returns low score for full downtrend"""
    close = 90.0
    sma10 = 100.0
    sma20 = 110.0
    sma50 = 120.0
    sma200 = 130.0
    
    score = _score_trend_strength(close, sma10, sma20, sma50, sma200)
    
    assert 0 <= score <= 25


def test_score_trend_strength_nan_handling():
    """_score_trend_strength returns 50 (neutral) with NaN values"""
    score = _score_trend_strength(100, float("nan"), 100, 100, 100)
    assert score == 50


def test_score_momentum_health_sweet_spot():
    """_score_momentum_health returns high score in P15-P80"""
    score_p50 = _score_momentum_health(0.5)
    assert 65 <= score_p50 <= 85


def test_score_momentum_health_overbought():
    """_score_momentum_health returns low score for overbought (P90+)"""
    score = _score_momentum_health(0.95)
    assert score < 50


def test_score_momentum_health_oversold():
    """_score_momentum_health returns moderate score for oversold"""
    score = _score_momentum_health(0.01)
    assert 45 <= score <= 60


def test_score_volume_confirmation_uptrend_strong_vol():
    """_score_volume_confirmation high in uptrend with strong volume"""
    score = _score_volume_confirmation(
        volume=3e6,
        vol_sma20=2e6,
        close=150.0,
        sma20=140.0
    )
    assert score > 60


def test_score_volume_confirmation_downtrend_weak_vol():
    """_score_volume_confirmation moderate in downtrend with weak volume"""
    score = _score_volume_confirmation(
        volume=1e6,
        vol_sma20=2e6,
        close=90.0,
        sma20=100.0
    )
    # This is actually 55 since vol_ratio=0.5, which gives 45 + 0.5*20 = 55
    assert 40 <= score <= 65


def test_regime_label_above_both():
    """_regime_label returns ABOVE_BOTH"""
    label = _regime_label(close=150.0, sma50=140.0, sma200=120.0)
    assert label == "ABOVE_BOTH"


def test_regime_label_above_200_below_50():
    """_regime_label returns ABOVE_200_BELOW_50"""
    label = _regime_label(close=130.0, sma50=140.0, sma200=120.0)
    assert label == "ABOVE_200_BELOW_50"


def test_regime_label_below_200_above_50():
    """_regime_label returns BELOW_200_ABOVE_50"""
    label = _regime_label(close=110.0, sma50=100.0, sma200=120.0)
    assert label == "BELOW_200_ABOVE_50"


def test_regime_label_below_both():
    """_regime_label returns BELOW_BOTH"""
    label = _regime_label(close=90.0, sma50=100.0, sma200=120.0)
    assert label == "BELOW_BOTH"


def test_regime_label_nan_handling():
    """_regime_label returns UNKNOWN with NaN"""
    label = _regime_label(close=100.0, sma50=float("nan"), sma200=120.0)
    assert label == "UNKNOWN"


def test_score_regime_quality_healthy_pattern():
    """_score_regime_quality high for healthy exit pattern"""
    score = _score_regime_quality(
        invested_pct=75.0,
        exits_ob=2,
        exits_fs=1,
        exits_dc=0,
        window=504
    )
    assert score > 60


def test_score_regime_quality_whipsaw_pattern():
    """_score_regime_quality low for high exit frequency"""
    score = _score_regime_quality(
        invested_pct=50.0,
        exits_ob=20,
        exits_fs=15,
        exits_dc=10,
        window=504
    )
    assert score < 60


# ============================================================================
# Tests: State Machine (_run_cc_overbought_window)
# ============================================================================

def test_cc_overbought_window_insufficient_data():
    """_run_cc_overbought_window handles <10 bars gracefully"""
    small_df = _make_df(n_bars=5, trend="up")
    small_df["accel"] = 0.0
    
    result = _run_cc_overbought_window(small_df)
    
    assert result["invested_pct"] == 50.0
    assert result["exits_ob"] == 0
    assert result["exits_fs"] == 0
    assert result["exits_dc"] == 0


def test_cc_overbought_window_returns_signal_state():
    """_run_cc_overbought_window returns signal_state (long or cash)"""
    df = _make_df(n_bars=600, trend="up")
    df["accel"] = _compute_accel(df["close"], df["sma3"])
    
    result = _run_cc_overbought_window(df)
    
    assert result["signal_state"] in ["long", "cash"]


# ============================================================================
# Integration Tests
# ============================================================================

def test_full_snapshot_has_consistent_scoring(monkeypatch):
    """All scores move together reasonably (bullish trend → all components up)"""
    df = _make_df(n_bars=600, trend="up")
    
    mock_de = type("MockDE", (), {
        "load": staticmethod(lambda ticker: df)
    })()
    
    monkeypatch.setattr(
        "tradingagents.phase_engine.data_engine",
        mock_de,
        raising=False
    )
    
    result = build_momentum_snapshot("FAKE")
    
    # For uptrend, most subscores should be elevated
    subscores = result["subscores"]
    avg_subscore = np.mean([
        subscores["trend_strength"],
        subscores["momentum_health"],
        subscores["regime_quality"],
        subscores["volume_confirmation"]
    ])
    
    # Should be above neutral
    assert avg_subscore > 45


def test_composite_is_weighted_average_of_subscores(monkeypatch):
    """composite_score approximately reflects subscore weights"""
    df = _make_df(n_bars=600, trend="up")
    
    mock_de = type("MockDE", (), {
        "load": staticmethod(lambda ticker: df)
    })()
    
    monkeypatch.setattr(
        "tradingagents.phase_engine.data_engine",
        mock_de,
        raising=False
    )
    
    result = build_momentum_snapshot("FAKE")
    
    subscores = result["subscores"]
    expected_composite = (
        subscores["trend_strength"] * 0.40 +
        subscores["momentum_health"] * 0.30 +
        subscores["regime_quality"] * 0.20 +
        subscores["volume_confirmation"] * 0.10
    )
    
    # Composite should be close to expected (within rounding)
    assert abs(result["composite_score"] - int(expected_composite)) <= 1


def test_direction_threshold_at_65_and_38(monkeypatch):
    """Direction thresholds are exactly 65 (bullish) and 38 (bearish)"""
    df = _make_df(n_bars=600, trend="up")
    
    mock_de = type("MockDE", (), {
        "load": staticmethod(lambda ticker: df)
    })()
    
    monkeypatch.setattr(
        "tradingagents.phase_engine.data_engine",
        mock_de,
        raising=False
    )
    
    result = build_momentum_snapshot("FAKE")
    composite = result["composite_score"]
    direction = result["direction"]
    
    if composite >= 65:
        assert direction == "BULLISH"
    elif composite <= 38:
        assert direction == "BEARISH"
    else:
        assert direction == "NEUTRAL"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
