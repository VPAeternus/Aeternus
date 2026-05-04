"""
Tests for V3 Index Benchmark feature (QQQ/SPY momentum acceleration).

Validates:
- v3_backtest.run_backtest() produces correct columns and RTH/overnight conditions
- v3_benchmark_stats() returns expected metric dict for index tickers
- Non-index tickers return empty dict
- Insufficient data handling
- Configuration constants (v3_hurdle_min_score, v3_benchmark_enabled)

Uses monkeypatch for mocking data_engine.load(). No conftest.py fixtures.
"""

import numpy as np
import pandas as pd
import pytest


# ─── Factory Helpers (monkeypatch-friendly) ───────────────────────────────────

def _make_synthetic_df(n=300):
    """
    Create synthetic OHLCV+indicator DataFrame for V3 backtest.
    Matches schema from data_engine.load() with date as column.
    Uses np.random.seed(42) for reproducibility.
    """
    np.random.seed(42)
    dates = pd.bdate_range("2024-01-01", periods=n)
    close = 100 + np.cumsum(np.random.randn(n) * 0.5)
    
    return pd.DataFrame({
        "date": dates,
        "open": close - np.random.rand(n) * 0.3,
        "close": close,
        "sma3": pd.Series(close).rolling(3).mean().ffill().bfill(),
        "sma10": pd.Series(close).rolling(10).mean().ffill().bfill(),
        "sma20": pd.Series(close).rolling(20).mean().ffill().bfill(),
        "sma50": pd.Series(close).rolling(50).mean().ffill().bfill(),
        "sma200": pd.Series(close).rolling(200).mean().ffill().bfill(),
        "vix": 18 + np.random.randn(n) * 3,
        "volume": 1_000_000 + np.random.randint(-100_000, 100_000, n),
    })


# ─── Tests ────────────────────────────────────────────────────────────────────

def test_run_backtest_synthetic():
    """
    Test run_backtest() on synthetic data.
    Verify it produces all expected columns with correct types.
    """
    from tradingagents.phase_engine.v3_backtest import run_backtest
    
    df = _make_synthetic_df(n=300)
    result = run_backtest(df)
    
    # Check all expected columns are present
    expected_cols = {
        "date", "open", "close", "regime", "rth_cond", "leg1", "leg2", "leg3",
        "rth_pnl", "leg1_pnl", "leg2_pnl", "leg3_pnl", "on_active", "on_pnl",
        "total_pnl", "accel", "vix"
    }
    assert set(result.columns) == expected_cols, (
        f"Missing columns: {expected_cols - set(result.columns)}, "
        f"Extra columns: {set(result.columns) - expected_cols}"
    )
    
    # Check row count matches input
    assert len(result) == len(df), f"Expected {len(df)} rows, got {len(result)}"
    
    # Check types
    assert result["rth_cond"].dtype == bool
    assert result["leg1"].dtype == bool
    assert result["leg2"].dtype == bool
    assert result["leg3"].dtype == bool
    assert result["on_active"].dtype == bool
    assert result["rth_pnl"].dtype in (float, np.floating)
    assert result["on_pnl"].dtype in (float, np.floating)
    assert result["total_pnl"].dtype in (float, np.floating)


def test_v3_benchmark_stats_returns_expected_keys(monkeypatch):
    """
    Monkeypatch data_engine.load() to return synthetic data.
    Call v3_benchmark_stats("QQQ") and verify all expected keys present.
    """
    from tradingagents.phase_engine import data_engine
    from tradingagents.phase_engine.index_overlay import v3_benchmark_stats
    
    # Mock data_engine.load() to return synthetic data
    def mock_load(ticker: str) -> pd.DataFrame:
        if ticker == "QQQ":
            return _make_synthetic_df(n=300)
        return None
    
    monkeypatch.setattr(data_engine, "load", mock_load)
    
    # Call v3_benchmark_stats with QQQ
    result = v3_benchmark_stats("QQQ", lookback_days=50)
    
    # Assert result is not empty
    assert isinstance(result, dict)
    assert len(result) > 0, "Expected non-empty dict for QQQ"
    
    # Check all expected keys
    expected_keys = {
        "ticker", "total_pts", "bh_pts", "annualized_pts_per_yr",
        "rth_skip_rate_pct", "on_active_rate_pct",
        "current_rth", "current_overnight", "current_leg", "period_days",
        "date_start", "date_end", "v3_total_return_pct", "bh_total_return_pct",
        "v3_cagr_pct", "bh_cagr_pct",
    }
    actual_keys = set(result.keys())
    assert actual_keys == expected_keys, (
        f"Missing keys: {expected_keys - actual_keys}, "
        f"Extra keys: {actual_keys - expected_keys}"
    )
    
    # Check value types
    assert result["ticker"] == "QQQ"
    assert isinstance(result["total_pts"], (int, float))
    assert isinstance(result["bh_pts"], (int, float))
    assert isinstance(result["annualized_pts_per_yr"], (int, float))
    assert isinstance(result["v3_total_return_pct"], (int, float))
    assert isinstance(result["bh_total_return_pct"], (int, float))
    assert isinstance(result["v3_cagr_pct"], (int, float))
    assert isinstance(result["bh_cagr_pct"], (int, float))
    assert isinstance(result["rth_skip_rate_pct"], (int, float))
    assert isinstance(result["on_active_rate_pct"], (int, float))
    assert isinstance(result["current_rth"], bool)
    assert isinstance(result["current_overnight"], bool)
    assert isinstance(result["period_days"], int)
    # current_leg may be None or string
    assert result["current_leg"] is None or isinstance(result["current_leg"], str)


def test_v3_benchmark_stats_non_index_returns_empty(monkeypatch):
    """
    Call v3_benchmark_stats("AAPL") and verify it returns empty dict.
    AAPL is not an index ticker (only QQQ and SPY valid).
    """
    from tradingagents.phase_engine.index_overlay import v3_benchmark_stats
    
    result = v3_benchmark_stats("AAPL", lookback_days=50)
    assert result == {}, f"Expected empty dict for non-index ticker, got {result}"


def test_v3_benchmark_stats_insufficient_data(monkeypatch):
    """
    Monkeypatch data_engine.load() to return only 10 rows (< 50 min threshold).
    Verify v3_benchmark_stats() returns empty dict.
    """
    from tradingagents.phase_engine import data_engine
    from tradingagents.phase_engine.index_overlay import v3_benchmark_stats
    
    def mock_load(ticker: str) -> pd.DataFrame:
        if ticker == "QQQ":
            return _make_synthetic_df(n=10)  # Too small
        return None
    
    monkeypatch.setattr(data_engine, "load", mock_load)
    
    result = v3_benchmark_stats("QQQ", lookback_days=50)
    assert result == {}, f"Expected empty dict for insufficient data, got {result}"


def test_v3_hurdle_config_key():
    """
    Import DEFAULT_CONFIG and verify v3 config keys have expected values.
    """
    from tradingagents.default_config import DEFAULT_CONFIG
    
    assert "v3_hurdle_min_score" in DEFAULT_CONFIG
    assert DEFAULT_CONFIG["v3_hurdle_min_score"] == 62.0
    
    assert "v3_benchmark_enabled" in DEFAULT_CONFIG
    assert DEFAULT_CONFIG["v3_benchmark_enabled"] is True


def test_run_backtest_rth_conditions():
    """
    Detailed test of RTH leg conditions in run_backtest().
    Verify that leg1, leg2, leg3 are independent and correctly attributed.
    """
    from tradingagents.phase_engine.v3_backtest import run_backtest
    
    df = _make_synthetic_df(n=300)
    result = run_backtest(df)
    
    # Check that rth_cond is the OR of all three legs
    # Note: legs in result are non-overlapping (leg2_net, leg3_net)
    # rth_cond is the OR of the original legs (before non-overlap)
    rth_from_legs = result["leg1"] | result["leg2"] | result["leg3"]
    assert rth_from_legs.equals(result["rth_cond"]), (
        "rth_cond should equal (leg1 | leg2 | leg3)"
    )
    
    # Verify P&L attribution: non-overlapping legs
    for idx in result.index:
        leg1_val = result.loc[idx, "leg1"]
        leg2_val = result.loc[idx, "leg2"]
        leg3_val = result.loc[idx, "leg3"]
        
        # In the result, legs are already non-overlapping
        # leg1 takes priority, then leg2, then leg3
        # So at most one should be True per row
        num_true = sum([leg1_val, leg2_val, leg3_val])
        assert num_true <= 1, (
            f"Row {idx}: multiple legs active (leg1={leg1_val}, "
            f"leg2={leg2_val}, leg3={leg3_val})"
        )


def test_v3_benchmark_stats_spy(monkeypatch):
    """
    Test v3_benchmark_stats with SPY (the other valid index ticker).
    """
    from tradingagents.phase_engine import data_engine
    from tradingagents.phase_engine.index_overlay import v3_benchmark_stats
    
    def mock_load(ticker: str) -> pd.DataFrame:
        if ticker == "SPY":
            return _make_synthetic_df(n=300)
        return None
    
    monkeypatch.setattr(data_engine, "load", mock_load)
    
    result = v3_benchmark_stats("SPY", lookback_days=100)
    
    assert isinstance(result, dict)
    assert len(result) > 0
    assert result["ticker"] == "SPY"
    assert result["period_days"] == 100  # Limited to lookback_days


def test_v3_benchmark_stats_date_window(monkeypatch):
    from tradingagents.phase_engine import data_engine
    from tradingagents.phase_engine.index_overlay import v3_benchmark_stats

    def mock_load(ticker: str) -> pd.DataFrame:
        if ticker == "QQQ":
            return _make_synthetic_df(n=300)
        return None

    monkeypatch.setattr(data_engine, "load", mock_load)

    result = v3_benchmark_stats(
        "QQQ",
        lookback_days=None,
        date_start="2024-03-01",
        date_end="2024-06-01",
    )

    assert isinstance(result, dict)
    assert result["ticker"] == "QQQ"
    assert result["date_start"] >= "2024-03-01"
    assert result["date_end"] <= "2024-06-01"


def test_run_backtest_overnight_skip_conditions():
    """
    Test overnight filtering conditions in run_backtest().
    Verify on_active is computed correctly.
    """
    from tradingagents.phase_engine.v3_backtest import run_backtest
    
    df = _make_synthetic_df(n=300)
    result = run_backtest(df)
    
    # on_active should be boolean
    assert result["on_active"].dtype == bool
    
    # on_pnl should be 0 when on_active is False
    for idx in result.index:
        if not result.loc[idx, "on_active"]:
            assert result.loc[idx, "on_pnl"] == 0.0, (
                f"Row {idx}: on_pnl should be 0 when on_active is False"
            )


def test_v3_benchmark_stats_lookback_days_none(monkeypatch):
    """
    Test v3_benchmark_stats with lookback_days=None (use full history).
    Should process all available data.
    """
    from tradingagents.phase_engine import data_engine
    from tradingagents.phase_engine.index_overlay import v3_benchmark_stats
    
    def mock_load(ticker: str) -> pd.DataFrame:
        if ticker == "QQQ":
            return _make_synthetic_df(n=300)
        return None
    
    monkeypatch.setattr(data_engine, "load", mock_load)
    
    # Call with lookback_days=None (full history)
    result = v3_benchmark_stats("QQQ", lookback_days=None)
    
    assert isinstance(result, dict)
    assert len(result) > 0
    # period_days should reflect full data (minus some for indicators)
    assert result["period_days"] == 300


def test_run_backtest_pnl_attribution():
    """
    Verify that leg1_pnl + leg2_pnl + leg3_pnl <= rth_pnl per row.
    (Due to non-overlapping attribution, should sum exactly to rth_pnl.)
    """
    from tradingagents.phase_engine.v3_backtest import run_backtest
    
    df = _make_synthetic_df(n=300)
    result = run_backtest(df)
    
    for idx in result.index:
        leg_pnl_sum = (
            result.loc[idx, "leg1_pnl"] +
            result.loc[idx, "leg2_pnl"] +
            result.loc[idx, "leg3_pnl"]
        )
        rth_pnl = result.loc[idx, "rth_pnl"]
        
        # Should be equal (within floating point tolerance)
        np.testing.assert_almost_equal(
            leg_pnl_sum, rth_pnl, decimal=10,
            err_msg=f"Row {idx}: leg P&L sum mismatch"
        )


def test_run_backtest_total_pnl_composition():
    """
    Verify total_pnl = rth_pnl + on_pnl per row.
    """
    from tradingagents.phase_engine.v3_backtest import run_backtest
    
    df = _make_synthetic_df(n=300)
    result = run_backtest(df)
    
    for idx in result.index:
        total = result.loc[idx, "rth_pnl"] + result.loc[idx, "on_pnl"]
        actual_total = result.loc[idx, "total_pnl"]
        
        np.testing.assert_almost_equal(
            total, actual_total, decimal=10,
            err_msg=f"Row {idx}: total_pnl composition mismatch"
        )


def test_index_overlay_engine_get_signal(monkeypatch):
    """
    Test IndexOverlayEngine.get_signal() returns proper signal dict.
    """
    from tradingagents.phase_engine import data_engine
    from tradingagents.phase_engine.index_overlay import IndexOverlayEngine
    
    def mock_load(ticker: str) -> pd.DataFrame:
        if ticker in ("QQQ", "SPY"):
            return _make_synthetic_df(n=300)
        return None
    
    monkeypatch.setattr(data_engine, "load", mock_load)
    
    engine = IndexOverlayEngine()
    signal = engine.get_signal("QQQ")
    
    # Should return non-empty dict for valid index
    assert isinstance(signal, dict)
    assert len(signal) > 0
    assert signal["ticker"] == "QQQ"
    assert "rth" in signal
    assert "overnight" in signal
    assert "active_leg" in signal
    assert isinstance(signal["rth"], bool)
    assert isinstance(signal["overnight"], bool)


def test_index_overlay_engine_non_index_ticker():
    """
    Test IndexOverlayEngine.get_signal() returns empty dict for non-index.
    """
    from tradingagents.phase_engine.index_overlay import IndexOverlayEngine
    
    engine = IndexOverlayEngine()
    signal = engine.get_signal("AAPL")  # Not an index
    
    assert signal == {}


def test_render_v3_benchmark_panel_shows_returns(monkeypatch):
    """
    Verify _render_v3_benchmark_panel outputs return percentages and CAGR
    when they are present in the stats dict.
    """
    import io
    from rich.console import Console
    from cli import common as cli_common

    buf = io.StringIO()
    test_console = Console(file=buf, width=120)
    monkeypatch.setattr(cli_common, "console", test_console)

    stats = {
        "ticker": "QQQ",
        "period_days": 6789,
        "current_rth": True,
        "current_overnight": False,
        "current_leg": "leg1",
        "total_pts": 1290.6,
        "bh_pts": 845.2,
        "v3_total_return_pct": 1290.6,
        "bh_total_return_pct": 845.2,
        "v3_cagr_pct": 10.24,
        "bh_cagr_pct": 8.52,
        "rth_skip_rate_pct": 14.3,
        "on_active_rate_pct": 62.1,
        "date_start": "1999-03-10",
        "date_end": "2026-03-06",
    }

    cli_common._render_v3_benchmark_panel(stats)

    output = buf.getvalue()
    assert "V3 +1290.6% vs B&H +845.2%" in output
    assert "CAGR: V3 10.24% vs B&H 8.52%" in output
    assert "1999-03-10" in output
    assert "2026-03-06" in output
    # Points line still present for backward compat
    assert "+1290.6 pts" in output


def test_v3_benchmark_config_env_override():
    """
    Test that v3 config settings can be read from DEFAULT_CONFIG
    (environment overrides tested separately in CI).
    """
    from tradingagents.default_config import DEFAULT_CONFIG
    
    # Check all v3 keys exist
    v3_keys = [k for k in DEFAULT_CONFIG.keys() if k.startswith("v3_")]
    assert len(v3_keys) > 0, "No v3 config keys found"
    
    # Spot-check known keys
    assert "v3_benchmark_enabled" in v3_keys
    assert "v3_benchmark_ticker" in v3_keys
    assert "v3_benchmark_lookback_days" in v3_keys
    assert "v3_hurdle_min_score" in v3_keys
