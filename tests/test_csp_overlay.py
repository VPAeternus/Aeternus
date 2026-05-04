"""Tests for the CSP overlay module."""

import math
import pandas as pd
import pytest
from unittest.mock import patch, MagicMock
from tradingagents.graph.csp_overlay import (
    CspRecommendation,
    CspOverlayResult,
    evaluate_csp_regime,
)


def _fake_qqq(sma_anchor=500.0, roc_pct=-3.0, n=260):
    """Build a fake QQQ Close series where the last price and ROC are controlled.

    Args:
        sma_anchor: Target SMA200 level (we set prices near this)
        roc_pct: 20-day ROC percentage (price today vs 20 days ago)
        n: Number of bars (should be >= 21 to compute 20-day ROC)

    Returns:
        DataFrame with Close column and DatetimeIndex
    """
    # Create base series with prices around sma_anchor so SMA200 ≈ sma_anchor
    prices = [float(sma_anchor)] * 200 + [float(sma_anchor * 0.95)] * (n - 200)

    # Adjust price 20 days ago to produce the desired roc_pct
    # ROC = (price_today - price_20d_ago) / price_20d_ago * 100
    # So: price_20d_ago = price_today / (1 + roc_pct / 100)
    last = prices[-1]
    price_20d_ago = last / (1 + roc_pct / 100)
    prices[-21] = price_20d_ago

    # Create index with exactly n dates. Business day freq may not create exactly n dates,
    # so request n+2 and then slice to match the price array length
    idx = pd.date_range(end="2026-03-01", periods=n + 5, freq="B")[:len(prices)]
    df = pd.DataFrame({"Close": prices}, index=idx)
    return df


def _fake_vix(level=28.0, n=30):
    """Build a fake VIX Close series."""
    # Create index with exactly n dates. Business day freq may not create exactly n dates,
    # so request n+2 and then slice to match the price array length
    idx = pd.date_range(end="2026-03-01", periods=n + 5, freq="B")[:n]
    return pd.DataFrame({"Close": [float(level)] * n}, index=idx)


class TestCspOverlayAboveSma200:
    """Test case: QQQ above SMA200 → ABOVE_SMA200 recommendation."""

    def test_above_sma200_returns_above_regime(self):
        """QQQ above SMA200 → ABOVE_SMA200, rationale mentions 'bull regime'."""
        with patch("tradingagents.graph.csp_overlay.yf.download") as mock_dl:
            # Create a QQQ series that's above SMA200: all prices at 525, so SMA200 ≈ 525 and last ≈ 525
            qqq_df = _fake_qqq(sma_anchor=525.0, roc_pct=-3.0, n=260)
            # Then set the last price to 550 (well above SMA200)
            qqq_prices = qqq_df["Close"].copy()
            qqq_prices.iloc[-1] = 550.0
            qqq_df["Close"] = qqq_prices

            def side_effect(ticker, **kwargs):
                if ticker == "QQQ":
                    return qqq_df
                elif ticker == "^VIX":
                    return _fake_vix(level=30.0, n=30)
                return pd.DataFrame()

            mock_dl.side_effect = side_effect

            result = evaluate_csp_regime(as_of_date="2026-03-01")

            assert result.recommendation == CspRecommendation.ABOVE_SMA200
            assert result.below_sma200 is False
            assert "bull regime" in result.rationale.lower()
            assert result.filter_reason == "ABOVE_SMA200"


class TestCspOverlaySellCsp:
    """Test case: all filters pass → SELL_CSP recommendation."""

    def test_sell_csp_all_filters_pass(self):
        """Below SMA200, VIX=30, ROC=-3% → SELL_CSP, strike ≈ qqq_price * 0.90."""
        with patch("tradingagents.graph.csp_overlay.yf.download") as mock_dl:
            def side_effect(ticker, **kwargs):
                if ticker == "QQQ":
                    return _fake_qqq(sma_anchor=500.0, roc_pct=-3.0, n=260)
                elif ticker == "^VIX":
                    return _fake_vix(level=30.0, n=30)
                return pd.DataFrame()

            mock_dl.side_effect = side_effect

            result = evaluate_csp_regime(as_of_date="2026-03-01")

            assert result.recommendation == CspRecommendation.SELL_CSP
            assert result.below_sma200 is True
            assert result.vix_in_band is True
            assert result.roc_ok is True
            assert result.estimated_premium_usd > 0
            # Strike should be exactly 10% OTM
            assert result.csp_strike == pytest.approx(result.qqq_price * 0.90, rel=0.001)

    def test_sell_csp_rationale_contains_key_metrics(self):
        """When SELL_CSP, rationale string contains key metrics."""
        with patch("tradingagents.graph.csp_overlay.yf.download") as mock_dl:
            def side_effect(ticker, **kwargs):
                if ticker == "QQQ":
                    return _fake_qqq(sma_anchor=500.0, roc_pct=-3.0, n=260)
                elif ticker == "^VIX":
                    return _fake_vix(level=30.0, n=30)
                return pd.DataFrame()

            mock_dl.side_effect = side_effect

            result = evaluate_csp_regime(as_of_date="2026-03-01")

            assert result.recommendation == CspRecommendation.SELL_CSP
            # Rationale should mention key metrics
            assert "SMA200" in result.rationale
            assert "VIX" in result.rationale
            assert "10%" in result.rationale
            assert "1,140%" in result.rationale

    def test_csp_strike_is_10pct_otm(self):
        """When SELL_CSP, csp_strike == qqq_price * 0.90."""
        with patch("tradingagents.graph.csp_overlay.yf.download") as mock_dl:
            def side_effect(ticker, **kwargs):
                if ticker == "QQQ":
                    return _fake_qqq(sma_anchor=500.0, roc_pct=-3.0, n=260)
                elif ticker == "^VIX":
                    return _fake_vix(level=30.0, n=30)
                return pd.DataFrame()

            mock_dl.side_effect = side_effect

            result = evaluate_csp_regime(as_of_date="2026-03-01")

            assert result.recommendation == CspRecommendation.SELL_CSP
            assert result.csp_strike == pytest.approx(result.qqq_price * 0.90, rel=0.001)


class TestCspOverlayHoldThinPremium:
    """Test case: below SMA200, VIX < 25 → HOLD_THIN_PREMIUM."""

    def test_hold_thin_premium_vix_below_25(self):
        """Below SMA200, VIX=18 → HOLD_THIN_PREMIUM, filter_reason contains 'VIX'."""
        with patch("tradingagents.graph.csp_overlay.yf.download") as mock_dl:
            def side_effect(ticker, **kwargs):
                if ticker == "QQQ":
                    return _fake_qqq(sma_anchor=500.0, roc_pct=-3.0, n=260)
                elif ticker == "^VIX":
                    return _fake_vix(level=18.0, n=30)
                return pd.DataFrame()

            mock_dl.side_effect = side_effect

            result = evaluate_csp_regime(as_of_date="2026-03-01")

            assert result.recommendation == CspRecommendation.HOLD_THIN_PREMIUM
            assert result.below_sma200 is True
            assert result.vix < 25.0
            assert result.vix_in_band is False
            assert "VIX" in result.filter_reason


class TestCspOverlayHoldPanic:
    """Test case: below SMA200, VIX > 40 → HOLD_PANIC."""

    def test_hold_panic_vix_above_40(self):
        """Below SMA200, VIX=55 → HOLD_PANIC, filter_reason contains 'VIX'."""
        with patch("tradingagents.graph.csp_overlay.yf.download") as mock_dl:
            def side_effect(ticker, **kwargs):
                if ticker == "QQQ":
                    return _fake_qqq(sma_anchor=500.0, roc_pct=-3.0, n=260)
                elif ticker == "^VIX":
                    return _fake_vix(level=55.0, n=30)
                return pd.DataFrame()

            mock_dl.side_effect = side_effect

            result = evaluate_csp_regime(as_of_date="2026-03-01")

            assert result.recommendation == CspRecommendation.HOLD_PANIC
            assert result.below_sma200 is True
            assert result.vix > 40.0
            assert result.vix_in_band is False
            assert "VIX" in result.filter_reason


class TestCspOverlayHoldFastCrash:
    """Test case: below SMA200, VIX in band, ROC < -8% → HOLD_FAST_CRASH."""

    def test_hold_fast_crash_roc_below_threshold(self):
        """Below SMA200, VIX=30, ROC=-12% → HOLD_FAST_CRASH, filter_reason contains 'ROC'."""
        with patch("tradingagents.graph.csp_overlay.yf.download") as mock_dl:
            def side_effect(ticker, **kwargs):
                if ticker == "QQQ":
                    return _fake_qqq(sma_anchor=500.0, roc_pct=-12.0, n=260)
                elif ticker == "^VIX":
                    return _fake_vix(level=30.0, n=30)
                return pd.DataFrame()

            mock_dl.side_effect = side_effect

            result = evaluate_csp_regime(as_of_date="2026-03-01")

            assert result.recommendation == CspRecommendation.HOLD_FAST_CRASH
            assert result.below_sma200 is True
            assert result.vix_in_band is True
            assert result.roc_ok is False
            assert result.roc_20d_pct < -8.0
            assert "ROC" in result.filter_reason


class TestCspOverlayDataUnavailable:
    """Test case: yfinance failure → DATA_UNAVAILABLE."""

    def test_data_unavailable_on_yfinance_failure(self):
        """yfinance raises Exception → DATA_UNAVAILABLE."""
        with patch("tradingagents.graph.csp_overlay.yf.download") as mock_dl:
            mock_dl.side_effect = Exception("Network error")

            result = evaluate_csp_regime(as_of_date="2026-03-01")

            assert result.recommendation == CspRecommendation.DATA_UNAVAILABLE
            assert result.qqq_price == 0.0
            assert result.sma200 == 0.0
            assert result.vix == 0.0
            assert "Data unavailable" in result.rationale


class TestCspOverlayEdgeCases:
    """Additional edge case tests."""

    def test_vix_exactly_25_boundary(self):
        """VIX exactly at 25 (lower boundary, not inclusive) → should not trigger HOLD_THIN_PREMIUM."""
        with patch("tradingagents.graph.csp_overlay.yf.download") as mock_dl:
            # VIX = 25.0 means VIX < 25 is False, so should evaluate other gates
            def side_effect(ticker, **kwargs):
                if ticker == "QQQ":
                    return _fake_qqq(sma_anchor=500.0, roc_pct=-3.0, n=260)
                elif ticker == "^VIX":
                    return _fake_vix(level=25.0, n=30)
                return pd.DataFrame()

            mock_dl.side_effect = side_effect

            result = evaluate_csp_regime(as_of_date="2026-03-01")

            # VIX=25 does not satisfy 25 < VIX, so skip HOLD_THIN_PREMIUM
            # Check if it goes to SELL_CSP (all other gates pass)
            assert result.recommendation == CspRecommendation.SELL_CSP
            assert result.vix == 25.0

    def test_vix_exactly_40_boundary(self):
        """VIX exactly at 40 (upper boundary, not inclusive) → should not trigger HOLD_PANIC."""
        with patch("tradingagents.graph.csp_overlay.yf.download") as mock_dl:
            # VIX = 40.0 means VIX > 40 is False, so should evaluate other gates
            def side_effect(ticker, **kwargs):
                if ticker == "QQQ":
                    return _fake_qqq(sma_anchor=500.0, roc_pct=-3.0, n=260)
                elif ticker == "^VIX":
                    return _fake_vix(level=40.0, n=30)
                return pd.DataFrame()

            mock_dl.side_effect = side_effect

            result = evaluate_csp_regime(as_of_date="2026-03-01")

            # VIX=40 does not satisfy VIX > 40, so skip HOLD_PANIC
            # Check if it goes to SELL_CSP (all other gates pass)
            assert result.recommendation == CspRecommendation.SELL_CSP
            assert result.vix == 40.0

    def test_roc_exactly_minus_8_boundary(self):
        """ROC exactly at -8.0 (boundary, not inclusive) → roc_ok should be True."""
        with patch("tradingagents.graph.csp_overlay.yf.download") as mock_dl:
            def side_effect(ticker, **kwargs):
                if ticker == "QQQ":
                    return _fake_qqq(sma_anchor=500.0, roc_pct=-8.0, n=260)
                elif ticker == "^VIX":
                    return _fake_vix(level=30.0, n=30)
                return pd.DataFrame()

            mock_dl.side_effect = side_effect

            result = evaluate_csp_regime(as_of_date="2026-03-01")

            # ROC=-8.0 does not satisfy ROC < -8.0, so roc_ok = True
            assert result.roc_20d_pct == pytest.approx(-8.0, abs=0.01)
            assert result.roc_ok is True
            # Should reach SELL_CSP
            assert result.recommendation == CspRecommendation.SELL_CSP
