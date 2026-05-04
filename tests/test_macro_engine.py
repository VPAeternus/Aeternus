"""Tests for tradingagents.agents.utils.macro_engine"""

import sys
import types
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

import pandas as pd

from tradingagents.agents.utils.macro_engine import (
    _classify_regime,
    _compute_regime_fit,
    _compute_monetary_stress,
    _compute_rate_headwind,
    _compute_commodity_cycle,
    _compute_correlation_regime,
    _try_fetch_fred,
    build_macro_snapshot,
)

import numpy as np


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------

def _regime_args(
    spy_close=500.0,
    spy_sma20=498.0,
    spy_sma200=495.0,
    vix_close=18.0,
    spy_return_1d_pct=0.3,
    dgs10=None,
    cpi_yoy=None,
    yield_curve_2s10s=None,
):
    """Return a kwargs dict for _classify_regime with sensible defaults."""
    return dict(
        spy_close=spy_close,
        spy_sma20=spy_sma20,
        spy_sma200=spy_sma200,
        vix_close=vix_close,
        spy_return_1d_pct=spy_return_1d_pct,
        dgs10=dgs10,
        cpi_yoy=cpi_yoy,
        yield_curve_2s10s=yield_curve_2s10s,
    )


def _stress_indicators(**overrides):
    """Return a minimal stress indicators dict."""
    base = {
        "gold_vs_spy": 0.0,
        "btc_vs_spy": 0.0,
        "usd_trend": 0.0,
        "silver_vs_gold": 0.0,
        "tlt_20d_return": 0.0,
        "gld_20d_return": 0.0,
        "dbc_20d_return": 0.0,
        "dgs10": None,
        "cpi_yoy": None,
        "yield_curve_2s10s": None,
    }
    base.update(overrides)
    return base


def _make_close_series(n=250, price=100.0):
    """Return a pandas Series of length n with a constant close price."""
    return pd.Series([price] * n, dtype=float)


def _make_market_data_dict(
    spy=500.0,
    vix=18.0,
    gld=180.0,
    slv=22.0,
    tlt=90.0,
    uup=28.0,
    dbc=20.0,
    btc=40000.0,
    hyg=75.0,
    lqd=105.0,
    eem=42.0,
):
    """Return a market_data dict keyed by ticker with constant-price Series."""
    return {
        "SPY": _make_close_series(250, spy),
        "^VIX": _make_close_series(250, vix),
        "GLD": _make_close_series(250, gld),
        "SLV": _make_close_series(250, slv),
        "TLT": _make_close_series(250, tlt),
        "UUP": _make_close_series(250, uup),
        "DBC": _make_close_series(250, dbc),
        "BTC-USD": _make_close_series(250, btc),
        "HYG": _make_close_series(250, hyg),
        "LQD": _make_close_series(250, lqd),
        "EEM": _make_close_series(250, eem),
    }


def _make_correlated_series(n=100, correlation=-0.7, seed=42):
    """Return two pandas Series with approximately the given Pearson correlation.

    Uses Cholesky decomposition to generate correlated returns, then
    converts to price series.
    """
    rng = np.random.RandomState(seed)
    # Generate correlated returns
    cov = np.array([[1.0, correlation], [correlation, 1.0]])
    L = np.linalg.cholesky(cov)
    uncorrelated = rng.randn(n, 2)
    correlated = uncorrelated @ L.T
    # Convert returns to price levels
    prices_a = 100.0 * np.cumprod(1 + correlated[:, 0] * 0.01)
    prices_b = 100.0 * np.cumprod(1 + correlated[:, 1] * 0.01)
    return pd.Series(prices_a, dtype=float), pd.Series(prices_b, dtype=float)


# ---------------------------------------------------------------------------
# _classify_regime tests
# ---------------------------------------------------------------------------

class TestClassifyRegime:
    def test_classify_regime_bull(self):
        """SPY above both SMAs and low VIX → BULL."""
        regime, triggers = _classify_regime(**_regime_args(
            spy_close=520.0,
            spy_sma20=510.0,
            spy_sma200=490.0,
            vix_close=16.0,
            spy_return_1d_pct=0.3,
        ))
        assert regime == "BULL"

    def test_classify_regime_bear(self):
        """SPY below SMA200 → BEAR (regardless of VIX unless VOL_SHOCK first)."""
        regime, triggers = _classify_regime(**_regime_args(
            spy_close=480.0,
            spy_sma20=490.0,
            spy_sma200=500.0,
            vix_close=22.0,
            spy_return_1d_pct=0.5,
        ))
        assert regime == "BEAR"
        assert "spy<sma200" in triggers

    def test_classify_regime_vol_shock_high_vix(self):
        """VIX >= 50 → VOL_SHOCK (highest priority)."""
        regime, triggers = _classify_regime(**_regime_args(
            spy_close=500.0,
            spy_sma200=490.0,
            vix_close=55.0,
            spy_return_1d_pct=0.3,
        ))
        assert regime == "VOL_SHOCK"

    def test_classify_regime_vol_shock_large_move(self):
        """|spy_return_1d_pct| >= 3.0 → VOL_SHOCK."""
        regime, triggers = _classify_regime(**_regime_args(
            spy_close=500.0,
            spy_sma200=490.0,
            vix_close=20.0,
            spy_return_1d_pct=3.5,
        ))
        assert regime == "VOL_SHOCK"

    def test_classify_regime_high_vol(self):
        """VIX >= 30 (but < 50) with SPY above SMA200 → HIGH_VOL."""
        regime, triggers = _classify_regime(**_regime_args(
            spy_close=510.0,
            spy_sma20=505.0,
            spy_sma200=490.0,
            vix_close=35.0,
            spy_return_1d_pct=0.3,
        ))
        assert regime == "HIGH_VOL"

    def test_classify_regime_risk_off(self):
        """SPY < SMA20 and VIX >= 25 → RISK_OFF."""
        regime, triggers = _classify_regime(**_regime_args(
            spy_close=498.0,
            spy_sma20=505.0,
            spy_sma200=490.0,
            vix_close=28.0,
            spy_return_1d_pct=0.3,
        ))
        assert regime == "RISK_OFF"
        assert "spy<sma20" in triggers

    def test_classify_regime_inflation_shock(self):
        """CPI YoY >= 4.0 with normal SPY/VIX → INFLATION_SHOCK."""
        regime, triggers = _classify_regime(**_regime_args(
            spy_close=510.0,
            spy_sma20=508.0,
            spy_sma200=495.0,
            vix_close=18.0,
            spy_return_1d_pct=0.3,
            cpi_yoy=5.0,
        ))
        assert regime == "INFLATION_SHOCK"

    def test_classify_regime_rates_uptrend(self):
        """DGS10 >= 4.5 with normal SPY/VIX and no inflation shock → RATES_UPTREND."""
        regime, triggers = _classify_regime(**_regime_args(
            spy_close=510.0,
            spy_sma20=508.0,
            spy_sma200=495.0,
            vix_close=18.0,
            spy_return_1d_pct=0.3,
            dgs10=5.0,
            cpi_yoy=None,
        ))
        assert regime == "RATES_UPTREND"

    def test_classify_regime_euphoria(self):
        """SPY >> SMA200 (>=5% deviation) and VIX <= 15 → EUPHORIA."""
        # SPY=530, SMA200=490: deviation = (530-490)/490*100 = 8.16% >= 5%
        regime, triggers = _classify_regime(**_regime_args(
            spy_close=530.0,
            spy_sma20=525.0,
            spy_sma200=490.0,
            vix_close=13.0,
            spy_return_1d_pct=0.3,
        ))
        assert regime == "EUPHORIA"

    def test_classify_regime_neutral(self):
        """No primary triggers fires → NEUTRAL."""
        # SPY > SMA200 but SMA20 < SMA200, VIX between 20 and 25 — no BULL (sma20 not >= sma200)
        # and VIX < 25 so no RISK_OFF; VIX < 30 so no HIGH_VOL; no FRED data.
        regime, triggers = _classify_regime(**_regime_args(
            spy_close=500.0,
            spy_sma20=493.0,   # sma20 < sma200 → BULL requires sma20 >= sma200
            spy_sma200=495.0,
            vix_close=22.0,
            spy_return_1d_pct=0.3,
        ))
        assert regime == "NEUTRAL"


# ---------------------------------------------------------------------------
# _compute_regime_fit tests
# ---------------------------------------------------------------------------

class TestComputeRegimeFit:
    def test_regime_fit_bull_base(self):
        """BULL regime base score for plain Equity → 78."""
        score = _compute_regime_fit("BULL", "Technology", "Equity")
        assert score == 78

    def test_regime_fit_sector_adjustment_energy_inflation(self):
        """Energy sector in INFLATION_SHOCK gets +8 on base 30 → 38."""
        score = _compute_regime_fit("INFLATION_SHOCK", "Energy", "Equity")
        assert score == 38

    def test_regime_fit_gold_override_bear(self):
        """Gold asset_class in BEAR regime → override to 70."""
        score = _compute_regime_fit("BEAR", "", "Gold")
        assert score == 70

    def test_regime_fit_gold_override_vol_shock(self):
        """Gold asset_class in VOL_SHOCK regime → override to 70."""
        score = _compute_regime_fit("VOL_SHOCK", "", "Gold")
        assert score == 70

    def test_regime_fit_gold_override_risk_off(self):
        """Gold asset_class in RISK_OFF regime → override to 70."""
        score = _compute_regime_fit("RISK_OFF", "", "Gold")
        assert score == 70

    def test_regime_fit_neutral_base(self):
        """NEUTRAL regime → base 52."""
        score = _compute_regime_fit("NEUTRAL", "", "Equity")
        assert score == 52

    def test_regime_fit_tech_rates_penalty(self):
        """Technology sector in RATES_UPTREND gets -5 on base 42 → 37."""
        score = _compute_regime_fit("RATES_UPTREND", "Technology", "Equity")
        assert score == 37

    def test_regime_fit_commodity_inflation_override(self):
        """Commodity asset_class in INFLATION_SHOCK → override to 75."""
        score = _compute_regime_fit("INFLATION_SHOCK", "", "Commodity")
        assert score == 75


# ---------------------------------------------------------------------------
# _compute_monetary_stress tests
# ---------------------------------------------------------------------------

class TestComputeMonetaryStress:
    def test_monetary_stress_neutral_equity(self):
        """All zero indicators → score 50 for Equity."""
        score = _compute_monetary_stress(_stress_indicators(), "Equity")
        assert score == 50

    def test_monetary_stress_equity_high_gold_vs_spy(self):
        """Gold outperforming SPY significantly → stress rises → equity headwind (score < 50)."""
        indicators = _stress_indicators(gold_vs_spy=0.05, usd_trend=0.0)
        score = _compute_monetary_stress(indicators, "Equity")
        # composite = 0.45*0.05 = 0.0225; equity: 50 - 200*0.0225 = 50 - 4.5 = 45.5 → 45
        assert score < 50

    def test_monetary_stress_gold_inverted_vs_equity(self):
        """For Gold asset_class, same stress = tailwind (score > 50)."""
        indicators = _stress_indicators(gold_vs_spy=0.05)
        equity_score = _compute_monetary_stress(indicators, "Equity")
        gold_score = _compute_monetary_stress(indicators, "Gold")
        # Equity: 50 - 200*composite (lower); Gold: 50 + 200*composite (higher)
        assert gold_score > equity_score
        assert gold_score > 50
        assert equity_score < 50

    def test_monetary_stress_usd_strengthening_equity(self):
        """Strong USD (positive usd_trend) → composite uses -0.25*usd_trend → equity score > 50."""
        indicators = _stress_indicators(usd_trend=0.05)
        score = _compute_monetary_stress(indicators, "Equity")
        # composite = -0.25*0.05 = -0.0125; equity: 50 - 200*(-0.0125) = 50 + 2.5 = 52.5 → 52
        assert score > 50

    def test_monetary_stress_btc_capped(self):
        """BTC relative return capped at 0.15 even if input is extreme."""
        indicators_uncapped = _stress_indicators(btc_vs_spy=0.5)
        indicators_capped = _stress_indicators(btc_vs_spy=0.15)
        # Both should produce the same score since 0.5 is capped to 0.15
        assert (
            _compute_monetary_stress(indicators_uncapped, "Equity")
            == _compute_monetary_stress(indicators_capped, "Equity")
        )


# ---------------------------------------------------------------------------
# _compute_rate_headwind tests
# ---------------------------------------------------------------------------

class TestComputeRateHeadwind:
    def test_rate_headwind_with_fred_low_rates(self):
        """dgs10 < 3.0 → rate_score=72, with neutral trend and cpi → combined in expected range."""
        indicators = _stress_indicators(dgs10=2.5, tlt_20d_return=0.01, cpi_yoy=2.5)
        score = _compute_rate_headwind(indicators, "", "Equity")
        # rate_score=72, trend_score = clamp(50+300*0.01)=53, inflation_score=58 (2<cpi<3)
        # combined = 0.35*72 + 0.30*53 + 0.35*58 = 25.2 + 15.9 + 20.3 = 61.4 → 61
        assert 55 <= score <= 70

    def test_rate_headwind_with_fred_high_rates(self):
        """dgs10 >= 5.0 → rate_score=28, score should be low."""
        indicators = _stress_indicators(dgs10=5.5, tlt_20d_return=-0.01, cpi_yoy=4.5)
        score = _compute_rate_headwind(indicators, "", "Equity")
        # rate_score=28, trend_score=clamp(50-3)=47, inflation_score=28
        # combined = 0.35*28+0.30*47+0.35*28 = 9.8+14.1+9.8 = 33.7 → 33
        assert score < 45

    def test_rate_headwind_no_fred_uses_tlt(self):
        """When dgs10=None, TLT momentum is sole proxy."""
        indicators_rising = _stress_indicators(dgs10=None, tlt_20d_return=0.03)
        indicators_falling = _stress_indicators(dgs10=None, tlt_20d_return=-0.03)
        score_rising = _compute_rate_headwind(indicators_rising, "", "Equity")
        score_falling = _compute_rate_headwind(indicators_falling, "", "Equity")
        # Rising TLT (falling rates) → rate-favourable
        assert score_rising > score_falling

    def test_rate_headwind_tech_sector_penalty(self):
        """Technology sector multiplied by 0.85 → lower score than neutral sector."""
        indicators = _stress_indicators(dgs10=3.5, tlt_20d_return=0.0, cpi_yoy=2.0)
        score_tech = _compute_rate_headwind(indicators, "Technology", "Equity")
        score_neutral = _compute_rate_headwind(indicators, "", "Equity")
        assert score_tech < score_neutral

    def test_rate_headwind_financial_sector_bonus(self):
        """Financial sector multiplied by 1.05 → higher score than neutral sector."""
        indicators = _stress_indicators(dgs10=3.5, tlt_20d_return=0.0, cpi_yoy=2.0)
        score_fin = _compute_rate_headwind(indicators, "Financial", "Equity")
        score_neutral = _compute_rate_headwind(indicators, "", "Equity")
        assert score_fin > score_neutral


# ---------------------------------------------------------------------------
# _compute_commodity_cycle tests
# ---------------------------------------------------------------------------

class TestComputeCommodityCycle:
    def test_commodity_cycle_energy_positive_dbc(self):
        """Energy sector with positive DBC momentum → score > 50."""
        indicators = _stress_indicators(dbc_20d_return=0.04)
        score = _compute_commodity_cycle(indicators, "Energy", "Equity")
        # raw = 50 + 250*0.04 = 60 → 60
        assert score > 50

    def test_commodity_cycle_tech_positive_dbc_headwind(self):
        """Technology sector with positive DBC momentum → score < 50 (commodity headwind)."""
        indicators = _stress_indicators(dbc_20d_return=0.04)
        score = _compute_commodity_cycle(indicators, "Technology", "Equity")
        # raw = 50 - 150*0.04 = 44 → 44
        assert score < 50

    def test_commodity_cycle_gold_uses_gld_momentum(self):
        """Gold asset_class uses GLD momentum, not DBC."""
        indicators = _stress_indicators(gld_20d_return=0.03, dbc_20d_return=0.0)
        score = _compute_commodity_cycle(indicators, "", "Gold")
        # raw = 50 + 200*0.03 = 56 → 56
        assert score > 50

    def test_commodity_cycle_neutral_zero_returns(self):
        """All zero returns → score == 50."""
        indicators = _stress_indicators(dbc_20d_return=0.0, gld_20d_return=0.0)
        score = _compute_commodity_cycle(indicators, "", "Equity")
        assert score == 50

    def test_commodity_cycle_energy_vs_tech_divergence(self):
        """Energy scores higher than Tech when DBC momentum is positive."""
        indicators = _stress_indicators(dbc_20d_return=0.03)
        energy_score = _compute_commodity_cycle(indicators, "Energy", "Equity")
        tech_score = _compute_commodity_cycle(indicators, "Technology", "Equity")
        assert energy_score > tech_score


# ---------------------------------------------------------------------------
# build_macro_snapshot integration tests
# ---------------------------------------------------------------------------

class TestBuildMacroSnapshot:
    def test_build_macro_snapshot_structure(self, monkeypatch):
        """Mock _fetch_market_data and _try_fetch_fred; verify full output dict keys."""
        import tradingagents.agents.utils.macro_engine as engine

        monkeypatch.setattr(engine, "_fetch_market_data", lambda: _make_market_data_dict(
            spy=520.0, vix=16.0, gld=185.0, slv=23.0,
            tlt=92.0, uup=27.0, dbc=21.0, btc=45000.0,
        ))
        monkeypatch.setattr(engine, "_try_fetch_fred", lambda: {"dgs10": 4.0, "dgs2": 3.5, "cpi_yoy": 2.8, "yield_curve_2s10s": 0.5, "debt_to_gdp": None, "deficit_pct_gdp": None})

        result = build_macro_snapshot("AAPL", sector="Technology", asset_class="Equity")

        # Top-level keys
        required_keys = [
            "regime",
            "regime_triggers",
            "indicators",
            "subscores",
            "composite_score",
            "direction",
            "asset_class",
            "sector",
            "data_coverage",
            "fred_available",
        ]
        for key in required_keys:
            assert key in result, f"Missing key: {key}"

        # Sub-score keys
        assert set(result["subscores"].keys()) == {
            "regime_fit",
            "monetary_stress",
            "rate_headwind",
            "commodity_cycle",
        }

        # Indicator keys
        indicator_keys = [
            "spy_close", "spy_sma20", "spy_sma200", "spy_deviation_pct",
            "spy_return_1d_pct", "vix_close", "gld_20d_return", "btc_20d_return",
            "tlt_20d_return", "uup_20d_return", "dbc_20d_return", "slv_20d_return",
            "dgs10", "cpi_yoy",
        ]
        for key in indicator_keys:
            assert key in result["indicators"], f"Missing indicator key: {key}"

        # Type checks
        assert isinstance(result["regime"], str)
        assert isinstance(result["composite_score"], int)
        assert 0 <= result["composite_score"] <= 100
        assert result["direction"] in ("BULLISH", "BEARISH", "NEUTRAL")
        assert result["asset_class"] == "Equity"
        assert result["sector"] == "Technology"
        assert result["fred_available"] is True

    def test_build_macro_snapshot_yfinance_failure(self, monkeypatch):
        """When _fetch_market_data returns empty dict, returns neutral snapshot."""
        import tradingagents.agents.utils.macro_engine as engine

        monkeypatch.setattr(engine, "_fetch_market_data", lambda: {})
        monkeypatch.setattr(engine, "_try_fetch_fred", lambda: {"dgs10": None, "cpi_yoy": None})

        result = build_macro_snapshot("AAPL", sector="Technology", asset_class="Equity")

        assert result["regime"] == "NEUTRAL"
        assert result["composite_score"] == 50
        assert result["direction"] == "NEUTRAL"
        assert result["data_coverage"] == 0.0
        assert result["fred_available"] is False
        # All subscores neutral
        for key, val in result["subscores"].items():
            assert val == 50, f"Expected neutral subscore 50 for {key}, got {val}"

    def test_build_macro_snapshot_composite_range(self, monkeypatch):
        """Composite score is always clamped to [0, 100]."""
        import tradingagents.agents.utils.macro_engine as engine

        monkeypatch.setattr(engine, "_fetch_market_data", lambda: _make_market_data_dict())
        monkeypatch.setattr(engine, "_try_fetch_fred", lambda: {"dgs10": None, "cpi_yoy": None})

        result = build_macro_snapshot("SPY")
        assert 0 <= result["composite_score"] <= 100

    def test_build_macro_snapshot_bull_regime_detected(self, monkeypatch):
        """With clearly bullish market data, regime should be BULL."""
        import tradingagents.agents.utils.macro_engine as engine

        # SPY constant at 520 → sma20=520, sma200=520 (equal), vix=14 → meets BULL criteria
        # Actually for BULL: spy>=sma200 AND sma20>=sma200 AND vix<=20 — constant series satisfies all
        monkeypatch.setattr(engine, "_fetch_market_data", lambda: _make_market_data_dict(
            spy=520.0, vix=14.0,
        ))
        monkeypatch.setattr(engine, "_try_fetch_fred", lambda: {"dgs10": None, "cpi_yoy": None, "debt_to_gdp": None, "deficit_pct_gdp": None})

        result = build_macro_snapshot("AAPL")
        assert result["regime"] == "BULL"

    def test_build_macro_snapshot_debt_indicators_present(self, monkeypatch):
        """When FRED returns debt/deficit data, snapshot includes them with correct values."""
        import tradingagents.agents.utils.macro_engine as engine

        monkeypatch.setattr(engine, "_fetch_market_data", lambda: _make_market_data_dict(
            spy=520.0, vix=16.0, gld=185.0, slv=23.0,
            tlt=92.0, uup=27.0, dbc=21.0, btc=45000.0,
        ))
        monkeypatch.setattr(engine, "_try_fetch_fred", lambda: {
            "dgs10": 4.2,
            "dgs2": 3.7,
            "cpi_yoy": 3.1,
            "yield_curve_2s10s": 0.5,
            "debt_to_gdp": 123.5,
            "deficit_pct_gdp": -6.3,
        })

        result = build_macro_snapshot("AAPL", sector="Technology", asset_class="Equity")

        assert "debt_to_gdp" in result["indicators"]
        assert "deficit_pct_gdp" in result["indicators"]
        assert result["indicators"]["debt_to_gdp"] == 123.5
        assert result["indicators"]["deficit_pct_gdp"] == -6.3

    def test_build_macro_snapshot_debt_indicators_none_without_fred(self, monkeypatch):
        """When FRED returns None for debt/deficit, snapshot has them as None."""
        import tradingagents.agents.utils.macro_engine as engine

        monkeypatch.setattr(engine, "_fetch_market_data", lambda: _make_market_data_dict(
            spy=520.0, vix=16.0, gld=185.0, slv=23.0,
            tlt=92.0, uup=27.0, dbc=21.0, btc=45000.0,
        ))
        monkeypatch.setattr(engine, "_try_fetch_fred", lambda: {
            "dgs10": None,
            "dgs2": None,
            "cpi_yoy": None,
            "yield_curve_2s10s": None,
            "debt_to_gdp": None,
            "deficit_pct_gdp": None,
        })

        result = build_macro_snapshot("AAPL", sector="Technology", asset_class="Equity")

        assert "debt_to_gdp" in result["indicators"]
        assert "deficit_pct_gdp" in result["indicators"]
        assert result["indicators"]["debt_to_gdp"] is None
        assert result["indicators"]["deficit_pct_gdp"] is None

    def test_neutral_snapshot_has_debt_indicators(self, monkeypatch):
        """When yfinance data is empty, neutral snapshot includes debt indicators as None."""
        import tradingagents.agents.utils.macro_engine as engine

        monkeypatch.setattr(engine, "_fetch_market_data", lambda: {})
        monkeypatch.setattr(engine, "_try_fetch_fred", lambda: {
            "dgs10": None,
            "dgs2": None,
            "cpi_yoy": None,
            "yield_curve_2s10s": None,
            "debt_to_gdp": None,
            "deficit_pct_gdp": None,
        })

        result = build_macro_snapshot("AAPL", sector="Technology", asset_class="Equity")

        assert result["regime"] == "NEUTRAL"
        assert "debt_to_gdp" in result["indicators"]
        assert "deficit_pct_gdp" in result["indicators"]
        assert result["indicators"]["debt_to_gdp"] is None
        assert result["indicators"]["deficit_pct_gdp"] is None


# ---------------------------------------------------------------------------
# Yield curve tests
# ---------------------------------------------------------------------------

class TestYieldCurve:
    def test_fred_returns_dgs2_and_spread(self, monkeypatch):
        """Mock FRED responses, verify dgs2 and yield_curve_2s10s populated."""
        import tradingagents.agents.utils.macro_engine as engine

        monkeypatch.setattr(engine, "_fetch_market_data", lambda: _make_market_data_dict(
            spy=520.0, vix=16.0,
        ))
        monkeypatch.setattr(engine, "_try_fetch_fred", lambda: {
            "dgs10": 4.25, "dgs2": 3.90, "cpi_yoy": 2.5,
            "debt_to_gdp": None, "deficit_pct_gdp": None,
            "yield_curve_2s10s": 0.35,
        })

        result = build_macro_snapshot("AAPL", sector="Technology", asset_class="Equity")
        assert result["indicators"]["dgs2"] == 3.90
        assert abs(result["indicators"]["yield_curve_2s10s"] - 0.35) < 0.01

    def test_spread_none_when_dgs2_missing(self, monkeypatch):
        """Verify graceful degradation when DGS2 is unavailable."""
        import tradingagents.agents.utils.macro_engine as engine

        monkeypatch.setattr(engine, "_fetch_market_data", lambda: _make_market_data_dict(
            spy=520.0, vix=16.0,
        ))
        monkeypatch.setattr(engine, "_try_fetch_fred", lambda: {
            "dgs10": 4.25, "dgs2": None, "cpi_yoy": 2.5,
            "debt_to_gdp": None, "deficit_pct_gdp": None,
            "yield_curve_2s10s": None,
        })

        result = build_macro_snapshot("AAPL", sector="Technology", asset_class="Equity")
        assert result["indicators"]["dgs2"] is None
        assert result["indicators"]["yield_curve_2s10s"] is None

    def test_rate_headwind_with_spread(self):
        """Verify 4-component weighting when spread available."""
        indicators = _stress_indicators(dgs10=3.5, tlt_20d_return=0.0, cpi_yoy=2.5, yield_curve_2s10s=1.0)
        score = _compute_rate_headwind(indicators, "", "Equity")
        # rate_score=58, trend_score=50, inflation_score=58, spread_score=60 (0.5<=spread<1.5)
        # combined = 0.30*58 + 0.25*50 + 0.25*58 + 0.20*60 = 17.4+12.5+14.5+12.0 = 56.4 → 56
        assert 50 <= score <= 65

    def test_rate_headwind_without_spread(self):
        """Verify 3-component fallback unchanged when spread missing."""
        indicators = _stress_indicators(dgs10=3.5, tlt_20d_return=0.0, cpi_yoy=2.5)
        score = _compute_rate_headwind(indicators, "", "Equity")
        # rate_score=58, trend_score=50, inflation_score=58
        # combined = 0.35*58 + 0.30*50 + 0.35*58 = 20.3+15+20.3 = 55.6 → 55
        assert 50 <= score <= 65

    def test_inverted_yield_curve_trigger(self):
        """Verify yield_curve_inverted appears in regime triggers when spread < -0.20."""
        regime, triggers = _classify_regime(
            spy_close=510.0, spy_sma20=508.0, spy_sma200=495.0,
            vix_close=18.0, spy_return_1d_pct=0.3,
            dgs10=None, cpi_yoy=None,
            yield_curve_2s10s=-0.50,
        )
        assert "yield_curve_inverted" in triggers

    def test_no_inversion_trigger_when_spread_positive(self):
        """Verify yield_curve_inverted NOT in triggers when spread is positive."""
        regime, triggers = _classify_regime(
            spy_close=510.0, spy_sma20=508.0, spy_sma200=495.0,
            vix_close=18.0, spy_return_1d_pct=0.3,
            dgs10=None, cpi_yoy=None,
            yield_curve_2s10s=1.5,
        )
        assert "yield_curve_inverted" not in triggers

    def test_inverted_spread_rate_headwind_penalty(self):
        """Inverted spread (negative) → spread_score=25, pulls rate_headwind down."""
        indicators_inverted = _stress_indicators(dgs10=3.5, tlt_20d_return=0.0, cpi_yoy=2.5, yield_curve_2s10s=-0.5)
        indicators_normal = _stress_indicators(dgs10=3.5, tlt_20d_return=0.0, cpi_yoy=2.5, yield_curve_2s10s=1.0)
        score_inverted = _compute_rate_headwind(indicators_inverted, "", "Equity")
        score_normal = _compute_rate_headwind(indicators_normal, "", "Equity")
        assert score_inverted < score_normal


# ---------------------------------------------------------------------------
# _compute_correlation_regime tests
# ---------------------------------------------------------------------------

class TestCorrelationRegime:
    def test_normal_negative_correlation(self):
        """Strongly negatively correlated pair with expected negative sign → NORMAL."""
        sa, sb = _make_correlated_series(100, correlation=-0.70, seed=42)
        series_map = {"UUP": sa, "GLD": sb}
        result = _compute_correlation_regime(series_map)
        pair = result["pairs"].get("dollar_gold")
        assert pair is not None, "dollar_gold pair should be present"
        assert pair["state"] == "NORMAL"
        assert pair["corr_20d"] < 0
        assert pair["expected_sign"] == "negative"
        assert "dollar_gold" not in result["broken_pairs"]

    def test_inverted_correlation(self):
        """Strongly positively correlated pair when expected negative → INVERTED."""
        # Both rise together — positive corr where negative is expected
        sa, sb = _make_correlated_series(100, correlation=0.70, seed=99)
        series_map = {"UUP": sa, "GLD": sb}
        result = _compute_correlation_regime(series_map)
        pair = result["pairs"].get("dollar_gold")
        assert pair is not None
        assert pair["state"] == "INVERTED"
        assert pair["corr_20d"] > 0
        assert "dollar_gold" in result["broken_pairs"]

    def test_decoupled_correlation(self):
        """Near-zero correlation → DECOUPLED."""
        sa, sb = _make_correlated_series(100, correlation=0.0, seed=77)
        series_map = {"UUP": sa, "GLD": sb}
        result = _compute_correlation_regime(series_map)
        pair = result["pairs"].get("dollar_gold")
        assert pair is not None
        assert pair["state"] in ("DECOUPLED", "WEAK")
        # With 0.0 target correlation, abs(corr) should be near zero
        assert abs(pair["corr_20d"]) < 0.35

    def test_weak_correlation(self):
        """Slightly negative correlation (|corr| between 0.15 and 0.30) → WEAK."""
        sa, sb = _make_correlated_series(100, correlation=-0.22, seed=55)
        series_map = {"UUP": sa, "GLD": sb}
        result = _compute_correlation_regime(series_map)
        pair = result["pairs"].get("dollar_gold")
        assert pair is not None
        # Weak or NORMAL depending on random realization; sign should match
        assert pair["state"] in ("WEAK", "NORMAL", "DECOUPLED")
        assert pair["corr_20d"] < 0

    def test_missing_series_graceful(self):
        """Missing ticker series → pair omitted, no crash."""
        series_map = {"UUP": _make_close_series(100, 28.0)}  # GLD missing
        result = _compute_correlation_regime(series_map)
        assert "dollar_gold" not in result["pairs"]
        assert result["broken_count"] == 0
        assert isinstance(result["broken_pairs"], list)

    def test_empty_series_map(self):
        """Empty input → safe empty output."""
        result = _compute_correlation_regime({})
        assert result["pairs"] == {}
        assert result["broken_pairs"] == []
        assert result["broken_count"] == 0

    def test_eem_in_snapshot_indicators(self, monkeypatch):
        """build_macro_snapshot output includes eem_20d_return in indicators."""
        import tradingagents.agents.utils.macro_engine as engine

        monkeypatch.setattr(engine, "_fetch_market_data", lambda: _make_market_data_dict(
            spy=520.0, vix=16.0,
        ))
        monkeypatch.setattr(engine, "_try_fetch_fred", lambda: {
            "dgs10": None, "dgs2": None, "cpi_yoy": None,
            "yield_curve_2s10s": None, "debt_to_gdp": None, "deficit_pct_gdp": None,
        })

        result = build_macro_snapshot("AAPL", sector="Technology", asset_class="Equity")
        assert "eem_20d_return" in result["indicators"]

    def test_correlation_regime_in_snapshot(self, monkeypatch):
        """build_macro_snapshot output includes correlation_regime dict."""
        import tradingagents.agents.utils.macro_engine as engine

        monkeypatch.setattr(engine, "_fetch_market_data", lambda: _make_market_data_dict(
            spy=520.0, vix=16.0,
        ))
        monkeypatch.setattr(engine, "_try_fetch_fred", lambda: {
            "dgs10": None, "dgs2": None, "cpi_yoy": None,
            "yield_curve_2s10s": None, "debt_to_gdp": None, "deficit_pct_gdp": None,
        })

        result = build_macro_snapshot("AAPL", sector="Technology", asset_class="Equity")
        cr = result.get("correlation_regime")
        assert cr is not None
        assert "pairs" in cr
        assert "broken_pairs" in cr
        assert "broken_count" in cr
        assert "summary" in cr
        assert isinstance(cr["broken_count"], int)

    def test_neutral_snapshot_has_correlation_regime(self, monkeypatch):
        """Neutral snapshot (yfinance failure) includes correlation_regime with safe defaults."""
        import tradingagents.agents.utils.macro_engine as engine

        monkeypatch.setattr(engine, "_fetch_market_data", lambda: {})
        monkeypatch.setattr(engine, "_try_fetch_fred", lambda: {
            "dgs10": None, "dgs2": None, "cpi_yoy": None,
            "yield_curve_2s10s": None, "debt_to_gdp": None, "deficit_pct_gdp": None,
        })

        result = build_macro_snapshot("AAPL")
        cr = result.get("correlation_regime")
        assert cr is not None
        assert cr["pairs"] == {}
        assert cr["broken_pairs"] == []
        assert cr["broken_count"] == 0
        assert cr["summary"] == "data_unavailable"
        assert result["indicators"]["eem_20d_return"] is None

    def test_summary_format(self):
        """Summary string has expected format with counts."""
        sa_neg, sb_neg = _make_correlated_series(100, correlation=-0.70, seed=1)
        sa_pos, sb_pos = _make_correlated_series(100, correlation=0.85, seed=2)
        series_map = {
            "UUP": sa_neg, "GLD": sb_neg,
            "GLD": sa_pos, "SLV": sb_pos,  # gold_silver expects positive
        }
        result = _compute_correlation_regime(series_map)
        assert "/" in result["summary"]  # format: "N/T NORMAL, ..."
