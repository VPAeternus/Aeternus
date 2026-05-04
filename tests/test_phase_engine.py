"""
Tests for tradingagents.phase_engine package.

Validates phase classification, signal generation, and P&L math
using synthetic data. No network access or API keys required.
"""

import numpy as np
import pandas as pd
import pytest


# ─── Helpers ──────────────────────────────────────────────────────────────

def _make_synthetic_df(n=500, base_price=100.0, uptrend=True):
    """
    Generate synthetic OHLCV DataFrame with all indicator columns
    needed by phase_engine. Date is a column (not index), matching
    the schema from data_engine.load().
    """
    np.random.seed(42)  # deterministic for reproducibility
    dates = pd.bdate_range(start="2020-01-01", periods=n, freq="B")

    drift = 0.0005 if uptrend else -0.0005
    returns = np.random.normal(drift, 0.015, n)
    closes = base_price * np.exp(np.cumsum(returns))

    opens = closes * (1 + np.random.uniform(-0.005, 0.005, n))
    highs = np.maximum(opens, closes) * (1 + np.random.uniform(0, 0.01, n))
    lows = np.minimum(opens, closes) * (1 - np.random.uniform(0, 0.01, n))
    volumes = np.random.randint(800_000, 1_200_000, n).astype(float)

    df = pd.DataFrame({
        "date": dates,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
    })

    # SMAs (use NaN for insufficient window, matching real data)
    df["sma3"]   = df["close"].rolling(3).mean()
    df["sma10"]  = df["close"].rolling(10).mean()
    df["sma20"]  = df["close"].rolling(20).mean()
    df["sma50"]  = df["close"].rolling(50).mean()
    df["sma200"] = df["close"].rolling(200).mean()

    # FVG detection (same logic as data_engine)
    hi = df["high"].values
    lo = df["low"].values
    bull_fvg = np.zeros(n)
    bear_fvg = np.zeros(n)
    for i in range(2, n):
        if hi[i - 2] < lo[i]:
            bull_fvg[i] = 1
        if lo[i - 2] > hi[i]:
            bear_fvg[i] = 1

    df["is_bull_fvg"] = bull_fvg
    df["is_bear_fvg"] = bear_fvg
    df["fvg_bull"] = pd.Series(bull_fvg).rolling(20).sum().values
    df["fvg_bear"] = pd.Series(bear_fvg).rolling(20).sum().values
    denom = df["fvg_bull"] + df["fvg_bear"]
    df["fvg_ratio"] = np.where(denom == 0, np.nan, df["fvg_bull"] / denom)

    # VIX (synthetic, centered in signal sweet spot)
    vix_vals = 18.0 + np.random.normal(0, 2, n)
    df["vix"] = np.clip(vix_vals, 10, 40)
    df["vix_sma10"] = df["vix"].rolling(10).mean()
    df["vix_sma20"] = df["vix"].rolling(20).mean()

    return df


@pytest.fixture
def synthetic_df_500():
    return _make_synthetic_df(500)


@pytest.fixture
def synthetic_df_short():
    return _make_synthetic_df(10)


# ─── Import Tests ─────────────────────────────────────────────────────────

class TestPhaseEngineImports:

    def test_import_config(self):
        from tradingagents.phase_engine import config
        assert hasattr(config, "UNIVERSE")
        assert hasattr(config, "TRANSACTION_BPS")

    def test_import_phase_engine(self):
        from tradingagents.phase_engine import phase_engine
        assert callable(phase_engine.classify_phases)
        assert callable(phase_engine.should_short_rth)

    def test_import_backtest(self):
        from tradingagents.phase_engine.backtest import PhaseBacktest, BacktestResult
        assert hasattr(BacktestResult, "__dataclass_fields__")

    def test_import_scanner(self):
        from tradingagents.phase_engine import scanner
        assert isinstance(scanner.DEFAULT_UNIVERSE, list)
        assert "QQQ" in scanner.DEFAULT_UNIVERSE

    def test_import_data_engine(self):
        from tradingagents.phase_engine import data_engine
        assert callable(data_engine.load)


# ─── Config Tests ─────────────────────────────────────────────────────────

class TestConfigDefaults:

    def test_transaction_bps(self):
        from tradingagents.phase_engine import config
        assert config.TRANSACTION_BPS == 10

    def test_phase_min_history(self):
        from tradingagents.phase_engine import config
        assert config.PHASE_MIN_HISTORY == 252

    def test_vix_thresholds(self):
        from tradingagents.phase_engine import config
        assert config.VIX_FLOOR == 15
        assert config.VIX_CEILING == 25
        assert config.VIX_FLOOR < config.VIX_CEILING

    def test_universe(self):
        from tradingagents.phase_engine import config
        assert "QQQ" in config.UNIVERSE
        assert "SPY" in config.UNIVERSE

    def test_index_tickers(self):
        from tradingagents.phase_engine import config
        assert config.INDEX_TICKERS == {"QQQ", "SPY", "IWM"}

    def test_metals(self):
        from tradingagents.phase_engine import config
        assert config.METALS_LEADER == "GLD"
        assert "GLD" in config.METALS_TICKERS
        assert "SLV" in config.METALS_TICKERS


# ─── Phase Classification Tests ───────────────────────────────────────────

class TestPhaseClassification:

    def test_returns_series(self, synthetic_df_500):
        from tradingagents.phase_engine import phase_engine
        phases = phase_engine.classify_phases(synthetic_df_500)
        assert isinstance(phases, pd.Series)

    def test_correct_length(self, synthetic_df_500):
        from tradingagents.phase_engine import phase_engine
        phases = phase_engine.classify_phases(synthetic_df_500)
        assert len(phases) == 500

    def test_valid_labels(self, synthetic_df_500):
        from tradingagents.phase_engine import phase_engine
        phases = phase_engine.classify_phases(synthetic_df_500)
        valid = {"MARK_UP", "MARK_DOWN", "DIST_ACCUM"}
        assert set(phases.unique()).issubset(valid)

    def test_short_data(self, synthetic_df_short):
        from tradingagents.phase_engine import phase_engine
        phases = phase_engine.classify_phases(synthetic_df_short)
        assert len(phases) == 10

    def test_no_nans(self, synthetic_df_500):
        from tradingagents.phase_engine import phase_engine
        phases = phase_engine.classify_phases(synthetic_df_500)
        assert not phases.isna().any()

    def test_single_bar(self):
        from tradingagents.phase_engine import phase_engine
        df = _make_synthetic_df(1)
        phases = phase_engine.classify_phases(df)
        assert len(phases) == 1
        assert phases.iloc[0] in {"MARK_UP", "MARK_DOWN", "DIST_ACCUM"}


# ─── Signal Tests ─────────────────────────────────────────────────────────

class TestSignals:

    def test_should_short_rth_returns_string(self, synthetic_df_500):
        from tradingagents.phase_engine import phase_engine
        phases = phase_engine.classify_phases(synthetic_df_500)
        sig = phase_engine.should_short_rth(synthetic_df_500, phases, 400, "QQQ")
        assert isinstance(sig, str)

    def test_rth_avoid_returns_bool(self, synthetic_df_500):
        from tradingagents.phase_engine import phase_engine
        phases = phase_engine.classify_phases(synthetic_df_500)
        result = phase_engine.is_rth_avoid(synthetic_df_500, phases, 50)
        assert isinstance(result, (bool, np.bool_))

    def test_markup_fade_returns_bool(self, synthetic_df_500):
        from tradingagents.phase_engine import phase_engine
        phases = phase_engine.classify_phases(synthetic_df_500)
        result = phase_engine.is_markup_fade(synthetic_df_500, phases, 50)
        assert isinstance(result, (bool, np.bool_))

    def test_markdown_crush_returns_bool(self, synthetic_df_500):
        from tradingagents.phase_engine import phase_engine
        phases = phase_engine.classify_phases(synthetic_df_500)
        result = phase_engine.is_markdown_crush(synthetic_df_500, phases, 50)
        assert isinstance(result, (bool, np.bool_))

    def test_metals_returns_empty_without_leader(self, synthetic_df_500):
        from tradingagents.phase_engine import phase_engine
        phases = phase_engine.classify_phases(synthetic_df_500)
        sig = phase_engine.should_short_rth(synthetic_df_500, phases, 50, "GLD")
        assert sig == ""

    def test_metals_with_leader(self, synthetic_df_500):
        from tradingagents.phase_engine import phase_engine
        phases = phase_engine.classify_phases(synthetic_df_500)
        sig = phase_engine.should_short_rth(
            synthetic_df_500, phases, 50, "GLD",
            leader_df=synthetic_df_500, leader_phases=phases,
        )
        assert sig in {"", "metals_md_flush", "metals_mu_spike"}

    def test_equity_signal_subset(self, synthetic_df_500):
        """Stock tickers can only get rth_avoid or markdown_crush (not markup_fade)."""
        from tradingagents.phase_engine import phase_engine
        phases = phase_engine.classify_phases(synthetic_df_500)
        valid = {"", "rth_avoid", "markdown_crush"}
        for i in range(100, 400):
            sig = phase_engine.should_short_rth(synthetic_df_500, phases, i, "NVDA")
            assert sig in valid

    def test_index_signal_superset(self, synthetic_df_500):
        """Index tickers can also get markup_fade and weak_regime_rth."""
        from tradingagents.phase_engine import phase_engine
        phases = phase_engine.classify_phases(synthetic_df_500)
        valid = {"", "rth_avoid", "markup_fade", "markdown_crush", "weak_regime_rth"}
        for i in range(100, 400):
            sig = phase_engine.should_short_rth(synthetic_df_500, phases, i, "QQQ")
            assert sig in valid


# ─── Phase Summary ────────────────────────────────────────────────────────

class TestPhaseSummary:

    def test_returns_dict(self, synthetic_df_500):
        from tradingagents.phase_engine import phase_engine
        phases = phase_engine.classify_phases(synthetic_df_500)
        summary = phase_engine.phase_summary(phases)
        assert isinstance(summary, dict)

    def test_has_expected_keys(self, synthetic_df_500):
        from tradingagents.phase_engine import phase_engine
        phases = phase_engine.classify_phases(synthetic_df_500)
        summary = phase_engine.phase_summary(phases)
        for key in ["total_bars", "MARK_UP", "MARK_DOWN", "DIST_ACCUM",
                     "pct_markup", "pct_markdn", "pct_dist"]:
            assert key in summary

    def test_counts_sum_to_total(self, synthetic_df_500):
        from tradingagents.phase_engine import phase_engine
        phases = phase_engine.classify_phases(synthetic_df_500)
        s = phase_engine.phase_summary(phases)
        assert s["MARK_UP"] + s["MARK_DOWN"] + s["DIST_ACCUM"] == s["total_bars"]

    def test_percentages_sum_to_100(self, synthetic_df_500):
        from tradingagents.phase_engine import phase_engine
        phases = phase_engine.classify_phases(synthetic_df_500)
        s = phase_engine.phase_summary(phases)
        assert abs(s["pct_markup"] + s["pct_markdn"] + s["pct_dist"] - 100.0) < 0.01


# ─── Macro Regime Tests ───────────────────────────────────────────────────

class TestMacroRegime:

    def test_macro_bearish_early_index_false(self):
        from tradingagents.phase_engine import phase_engine
        df = _make_synthetic_df(400)
        assert phase_engine.is_macro_bearish(df, 10) is False

    def test_macro_bearish_returns_bool(self, synthetic_df_500):
        from tradingagents.phase_engine import phase_engine
        result = phase_engine.is_macro_bearish(synthetic_df_500, 300)
        assert isinstance(result, (bool, np.bool_))

    def test_market_stress_returns_bool(self, synthetic_df_500):
        from tradingagents.phase_engine import phase_engine
        result = phase_engine.is_market_stress(synthetic_df_500, 100)
        assert isinstance(result, (bool, np.bool_))

    def test_severe_stress_returns_bool(self, synthetic_df_500):
        from tradingagents.phase_engine import phase_engine
        result = phase_engine.is_severe_stress(synthetic_df_500, 100)
        assert isinstance(result, (bool, np.bool_))

    def test_market_health_oob_index(self):
        from tradingagents.phase_engine import phase_engine
        df = _make_synthetic_df(100)
        assert phase_engine.is_market_health_bearish(df, 200) is False


# ─── BacktestResult Dataclass ────────────────────────────────────────────

class TestBacktestResult:

    def test_creation(self):
        from tradingagents.phase_engine.backtest import BacktestResult
        r = BacktestResult(
            ticker="TEST", start_date="2020-01-01", end_date="2025-01-01",
            start_capital=100_000, final_equity=150_000,
            total_return_pct=50.0, cagr_pct=8.5, sharpe=1.2, sortino=1.5,
            max_drawdown_pct=15.0, max_drawdown_duration_days=60,
            total_trades=100, signal_win_rate_pct=55.0, avg_signal_pnl=0.15,
            benchmark_return_pct=40.0, benchmark_cagr_pct=7.0, alpha_pct=1.5,
        )
        assert r.ticker == "TEST"
        assert r.alpha_pct == 1.5
        assert r.final_equity == 150_000

    def test_optional_fields_default(self):
        from tradingagents.phase_engine.backtest import BacktestResult
        r = BacktestResult(
            ticker="X", start_date="2020-01-01", end_date="2025-01-01",
            start_capital=100_000, final_equity=100_000,
            total_return_pct=0.0, cagr_pct=0.0, sharpe=0.0, sortino=0.0,
            max_drawdown_pct=0.0, max_drawdown_duration_days=0,
            total_trades=0, signal_win_rate_pct=0.0, avg_signal_pnl=0.0,
            benchmark_return_pct=0.0, benchmark_cagr_pct=0.0, alpha_pct=0.0,
        )
        assert r.equity_curve == []
        assert r.trades == []
        assert r.phase_distribution == {}
        assert r.signal_breakdown == {}


# ─── P&L Math ─────────────────────────────────────────────────────────────

class TestPnLMath:

    def test_signal_day_formula(self):
        """Signal day: raw = 2*open[i+1] - close[i+1] - close[i]
           cost = 2 * BPS/10000 * open[i+1]
           pnl = raw - cost"""
        from tradingagents.phase_engine import config

        close_i = 100.0
        open_next = 101.0
        close_next = 99.0

        raw = 2 * open_next - close_next - close_i  # 202 - 199 = 3.0
        cost = 2 * (config.TRANSACTION_BPS / 10000.0) * open_next  # 0.202
        pnl = raw - cost

        assert raw == pytest.approx(3.0)
        assert cost == pytest.approx(0.202, abs=0.001)
        assert pnl == pytest.approx(2.798, abs=0.001)

    def test_non_signal_day_formula(self):
        """Non-signal day: pnl = close[i] - close[i-1]"""
        assert 101.0 - 100.0 == pytest.approx(1.0)
        assert 99.0 - 100.0 == pytest.approx(-1.0)

    def test_signal_day_large_drop(self):
        """Large intraday drop → profitable short."""
        from tradingagents.phase_engine import config

        close_i = 100.0
        open_next = 102.0
        close_next = 96.0

        raw = 2 * open_next - close_next - close_i  # 204 - 196 = 8.0
        cost = 2 * (config.TRANSACTION_BPS / 10000.0) * open_next
        pnl = raw - cost

        assert raw == pytest.approx(8.0)
        assert pnl > 7.7

    def test_compounding_return(self):
        """Equity compounds: equity[i] = equity[i-1] * (1 + pnl/prev_close)"""
        equity = 100_000.0
        prev_close = 100.0
        pnl = 1.0  # +1% day

        daily_return = pnl / prev_close
        equity *= (1 + daily_return)

        assert equity == pytest.approx(101_000.0)


# ─── Edge Cases ───────────────────────────────────────────────────────────

class TestEdgeCases:

    def test_all_nan_fvg_ratio(self):
        from tradingagents.phase_engine import phase_engine
        df = _make_synthetic_df(100)
        df["fvg_ratio"] = np.nan
        phases = phase_engine.classify_phases(df)
        assert len(phases) == 100
        assert not phases.isna().any()

    def test_zero_volume_day(self):
        from tradingagents.phase_engine import phase_engine
        df = _make_synthetic_df(100)
        df.loc[50, "volume"] = 0
        phases = phase_engine.classify_phases(df)
        assert len(phases) == 100

    def test_signal_at_first_bar(self, synthetic_df_500):
        from tradingagents.phase_engine import phase_engine
        phases = phase_engine.classify_phases(synthetic_df_500)
        sig = phase_engine.should_short_rth(synthetic_df_500, phases, 0, "QQQ")
        assert isinstance(sig, str)

    def test_signal_at_last_bar(self, synthetic_df_500):
        from tradingagents.phase_engine import phase_engine
        phases = phase_engine.classify_phases(synthetic_df_500)
        sig = phase_engine.should_short_rth(
            synthetic_df_500, phases, len(synthetic_df_500) - 1, "QQQ",
        )
        assert isinstance(sig, str)


# ─── S7 Weak Regime Tests ────────────────────────────────────────────────

def _make_weak_regime_df(n=500, vix_value=22.0):
    """Synthetic DataFrame where close is below SMA20/50/200 but above SMA3."""
    df = _make_synthetic_df(n, base_price=100.0, uptrend=False)
    # Force weak regime: C > SMA3 and C < SMA20 < SMA50 < SMA200
    for i in range(n):
        c = df.loc[i, "close"]
        df.loc[i, "sma3"] = c - 1.0
        df.loc[i, "sma20"] = c + 2.0
        df.loc[i, "sma50"] = c + 5.0
        df.loc[i, "sma200"] = c + 10.0
    # Set VIX to desired value
    df["vix"] = vix_value
    df["vix_sma10"] = vix_value
    df["vix_sma20"] = vix_value
    return df


class TestS7Config:

    def test_s7_tickers(self):
        from tradingagents.phase_engine import config
        assert config.S7_TICKERS == {"QQQ", "SPY"}

    def test_s7_overnight_vix_ranges(self):
        from tradingagents.phase_engine import config
        assert config.S7_OVERNIGHT_VIX == [(20, 30), (40, 200)]

    def test_s7_rth_vix_ranges(self):
        from tradingagents.phase_engine import config
        assert config.S7_RTH_VIX == [(20, 25), (30, 40)]


class TestVixInRanges:

    def test_in_range(self):
        from tradingagents.phase_engine import phase_engine
        assert phase_engine._vix_in_ranges(22.0, [(20, 30)]) is True

    def test_below_range(self):
        from tradingagents.phase_engine import phase_engine
        assert phase_engine._vix_in_ranges(15.0, [(20, 30)]) is False

    def test_at_boundary_lo(self):
        from tradingagents.phase_engine import phase_engine
        assert phase_engine._vix_in_ranges(20.0, [(20, 30)]) is True

    def test_at_boundary_hi(self):
        from tradingagents.phase_engine import phase_engine
        # hi is exclusive
        assert phase_engine._vix_in_ranges(30.0, [(20, 30)]) is False

    def test_multiple_ranges(self):
        from tradingagents.phase_engine import phase_engine
        ranges = [(20, 30), (40, 200)]
        assert phase_engine._vix_in_ranges(25.0, ranges) is True
        assert phase_engine._vix_in_ranges(45.0, ranges) is True
        assert phase_engine._vix_in_ranges(35.0, ranges) is False


class TestWeakRegimeSmaCheck:

    def test_weak_regime_true(self):
        from tradingagents.phase_engine import phase_engine
        df = _make_weak_regime_df(500)
        assert phase_engine._weak_regime_sma_check(df, 300) == True  # noqa: E712

    def test_not_weak_when_above_sma200(self):
        from tradingagents.phase_engine import phase_engine
        df = _make_weak_regime_df(500)
        # Place SMA200 below close
        df.loc[300, "sma200"] = df.loc[300, "close"] - 5.0
        assert phase_engine._weak_regime_sma_check(df, 300) == False  # noqa: E712

    def test_not_weak_when_below_sma3(self):
        from tradingagents.phase_engine import phase_engine
        df = _make_weak_regime_df(500)
        # Place SMA3 above close
        df.loc[300, "sma3"] = df.loc[300, "close"] + 1.0
        assert phase_engine._weak_regime_sma_check(df, 300) == False  # noqa: E712


class TestS7Signals:

    def test_overnight_fires_vix_22(self):
        from tradingagents.phase_engine import phase_engine
        df = _make_weak_regime_df(500, vix_value=22.0)
        phases = phase_engine.classify_phases(df)
        assert phase_engine.is_weak_regime_overnight(df, phases, 300) is True

    def test_overnight_blocked_vix_35(self):
        from tradingagents.phase_engine import phase_engine
        df = _make_weak_regime_df(500, vix_value=35.0)
        phases = phase_engine.classify_phases(df)
        # VIX 35 is NOT in [(20,30), (40,200)]
        assert phase_engine.is_weak_regime_overnight(df, phases, 300) is False

    def test_overnight_fires_vix_45(self):
        from tradingagents.phase_engine import phase_engine
        df = _make_weak_regime_df(500, vix_value=45.0)
        phases = phase_engine.classify_phases(df)
        assert phase_engine.is_weak_regime_overnight(df, phases, 300) is True

    def test_rth_fires_vix_22(self):
        from tradingagents.phase_engine import phase_engine
        df = _make_weak_regime_df(500, vix_value=22.0)
        phases = phase_engine.classify_phases(df)
        assert phase_engine.is_weak_regime_rth(df, phases, 300) is True

    def test_rth_blocked_vix_28(self):
        from tradingagents.phase_engine import phase_engine
        df = _make_weak_regime_df(500, vix_value=28.0)
        phases = phase_engine.classify_phases(df)
        # VIX 28 is NOT in [(20,25), (30,40)]
        assert phase_engine.is_weak_regime_rth(df, phases, 300) is False

    def test_rth_fires_vix_35(self):
        from tradingagents.phase_engine import phase_engine
        df = _make_weak_regime_df(500, vix_value=35.0)
        phases = phase_engine.classify_phases(df)
        assert phase_engine.is_weak_regime_rth(df, phases, 300) is True


class TestOvernightRouter:

    def test_returns_signal_for_qqq(self):
        from tradingagents.phase_engine import phase_engine
        df = _make_weak_regime_df(500, vix_value=22.0)
        phases = phase_engine.classify_phases(df)
        sig = phase_engine.should_short_overnight(df, phases, 300, "QQQ")
        assert sig == "weak_regime_overnight"

    def test_returns_signal_for_spy(self):
        from tradingagents.phase_engine import phase_engine
        df = _make_weak_regime_df(500, vix_value=22.0)
        phases = phase_engine.classify_phases(df)
        sig = phase_engine.should_short_overnight(df, phases, 300, "SPY")
        assert sig == "weak_regime_overnight"

    def test_empty_for_non_s7_ticker(self):
        from tradingagents.phase_engine import phase_engine
        df = _make_weak_regime_df(500, vix_value=22.0)
        phases = phase_engine.classify_phases(df)
        sig = phase_engine.should_short_overnight(df, phases, 300, "NVDA")
        assert sig == ""

    def test_empty_for_iwm(self):
        from tradingagents.phase_engine import phase_engine
        df = _make_weak_regime_df(500, vix_value=22.0)
        phases = phase_engine.classify_phases(df)
        sig = phase_engine.should_short_overnight(df, phases, 300, "IWM")
        assert sig == ""

    def test_rth_router_includes_s7b(self):
        from tradingagents.phase_engine import phase_engine
        df = _make_weak_regime_df(500, vix_value=22.0)
        phases = phase_engine.classify_phases(df)
        sig = phase_engine.should_short_rth(df, phases, 300, "QQQ")
        # Should get weak_regime_rth (if no other signal fires first)
        assert sig in {"weak_regime_rth", "rth_avoid", "markup_fade", "markdown_crush", ""}


class TestScannerListReturn:

    def test_scan_ticker_returns_list(self):
        from tradingagents.phase_engine import scanner, phase_engine
        df = _make_synthetic_df(500)
        phases = phase_engine.classify_phases(df)
        result = scanner.scan_ticker("QQQ", df, phases)
        assert isinstance(result, list)

    def test_scan_ticker_empty_returns_empty_list(self):
        from tradingagents.phase_engine import scanner, phase_engine
        df = _make_synthetic_df(1)
        phases = phase_engine.classify_phases(df)
        result = scanner.scan_ticker("QQQ", df, phases)
        assert result == []

    def test_scan_ticker_signal_has_session_field(self):
        from tradingagents.phase_engine import scanner, phase_engine
        df = _make_weak_regime_df(500, vix_value=22.0)
        phases = phase_engine.classify_phases(df)
        result = scanner.scan_ticker("QQQ", df, phases)
        for sig in result:
            assert "session" in sig
            assert sig["session"] in {"rth", "overnight"}
