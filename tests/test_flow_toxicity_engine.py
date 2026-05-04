"""Tests for tradingagents.agents.utils.flow_toxicity_engine"""

import sys
import types
import pytest
import numpy as np
import pandas as pd

# Stub chromadb before it can be imported (pydantic v1 incompatible with Python 3.14)
if "chromadb" not in sys.modules or not hasattr(sys.modules.get("chromadb", None), "__path__"):
    _stub = types.ModuleType("chromadb")
    _stub.__path__ = []
    _stub.Client = None
    _config_stub = types.ModuleType("chromadb.config")
    _config_stub.Settings = type("Settings", (), {})
    sys.modules["chromadb"] = _stub
    sys.modules["chromadb.config"] = _config_stub

from tradingagents.agents.utils.flow_toxicity_engine import (
    _bvc_imbalance,
    _score_flow_imbalance,
    _score_accumulation_distribution,
    _score_volume_anomaly,
    _score_price_volume_divergence,
    _compute_cmf,
    build_flow_toxicity_snapshot,
)
from tradingagents.graph.aeternus_scoring import AeternusScorer


# ---------------------------------------------------------------------------
# Helper: Synthetic OHLCV DataFrame
# ---------------------------------------------------------------------------

def _make_df(n=50, base_close=100.0, trend=0.5, volume=1000000):
    """Create a synthetic OHLCV DataFrame for testing."""
    np.random.seed(42)
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    closes = [base_close + trend * i + np.random.randn() * 0.5 for i in range(n)]
    highs = [c + abs(np.random.randn()) * 2 for c in closes]
    lows = [c - abs(np.random.randn()) * 2 for c in closes]
    opens = [(h + l) / 2 for h, l in zip(highs, lows)]
    volumes = [int(volume * (0.8 + np.random.random() * 0.4)) for _ in range(n)]
    df = pd.DataFrame({
        "open": opens, "high": highs, "low": lows, "close": closes,
        "volume": volumes,
    }, index=dates)
    df["vol_sma20"] = df["volume"].rolling(20).mean()
    return df


# ---------------------------------------------------------------------------
# Test 1: BVC Imbalance Computation
# ---------------------------------------------------------------------------

class TestBVCComputation:
    def test_known_values(self):
        """Close=high (all buying). buy_fraction=1.0, imbalance=1.0."""
        df = pd.DataFrame({
            "high": [110, 115, 120],
            "low": [100, 105, 110],
            "close": [110, 115, 120],
            "volume": [1000, 1000, 1000],
        })
        result = _bvc_imbalance(df)
        assert np.allclose(result.values, [1.0, 1.0, 1.0])

    def test_flat_bar(self):
        """When high==low, imbalance should be 0 (buy_frac=0.5)."""
        df = pd.DataFrame({
            "high": [100], "low": [100], "close": [100], "volume": [1000],
        })
        result = _bvc_imbalance(df)
        assert result.iloc[0] == 0.0

    def test_zero_volume(self):
        """When volume=0, imbalance should be NaN."""
        df = pd.DataFrame({
            "high": [110], "low": [100], "close": [105], "volume": [0],
        })
        result = _bvc_imbalance(df)
        assert np.isnan(result.iloc[0])

    def test_midpoint_close(self):
        """When close is exactly midpoint, imbalance should be 0 (buy_frac=0.5)."""
        df = pd.DataFrame({
            "high": [110], "low": [100], "close": [105], "volume": [1000],
        })
        result = _bvc_imbalance(df)
        assert result.iloc[0] == 0.0


# ---------------------------------------------------------------------------
# Test 2: Flow Imbalance Scoring
# ---------------------------------------------------------------------------

class TestFlowImbalanceScoring:
    def test_extreme(self):
        assert _score_flow_imbalance(0.8) == 15

    def test_high(self):
        assert _score_flow_imbalance(0.6) == 30

    def test_moderate(self):
        assert _score_flow_imbalance(0.4) == 50

    def test_low(self):
        assert _score_flow_imbalance(0.2) == 65

    def test_minimal(self):
        assert _score_flow_imbalance(0.1) == 80


# ---------------------------------------------------------------------------
# Test 3: CMF Computation
# ---------------------------------------------------------------------------

class TestCMFComputation:
    def test_all_closes_at_high(self):
        """Closes at high -> CMF near 1.0 (strong accumulation)."""
        df = pd.DataFrame({
            "high": [110] * 25, "low": [100] * 25,
            "close": [110] * 25, "volume": [1000] * 25,
        })
        cmf = _compute_cmf(df)
        assert cmf > 0.5

    def test_all_closes_at_low(self):
        """Closes at low -> CMF near -1.0 (strong distribution)."""
        df = pd.DataFrame({
            "high": [110] * 25, "low": [100] * 25,
            "close": [100] * 25, "volume": [1000] * 25,
        })
        cmf = _compute_cmf(df)
        assert cmf < -0.5

    def test_midpoint_neutral(self):
        """Closes at midpoint -> CMF near 0."""
        df = pd.DataFrame({
            "high": [110] * 25, "low": [100] * 25,
            "close": [105] * 25, "volume": [1000] * 25,
        })
        cmf = _compute_cmf(df)
        assert abs(cmf) < 0.1


# ---------------------------------------------------------------------------
# Test 4: Accumulation Distribution Scoring
# ---------------------------------------------------------------------------

class TestAccumulationDistributionScoring:
    def test_strong_accumulation(self):
        assert _score_accumulation_distribution(0.2) == 80

    def test_neutral(self):
        assert _score_accumulation_distribution(0.0) == 50

    def test_strong_distribution(self):
        assert _score_accumulation_distribution(-0.2) == 20


# ---------------------------------------------------------------------------
# Test 5: Price-Volume Divergence Scoring
# ---------------------------------------------------------------------------

class TestPriceVolumeDivergence:
    def test_strong_positive(self):
        assert _score_price_volume_divergence(0.6) == 70

    def test_uncorrelated(self):
        assert _score_price_volume_divergence(0.0) == 50

    def test_strong_negative(self):
        assert _score_price_volume_divergence(-0.6) == 20


# ---------------------------------------------------------------------------
# Test 6: Composite Score and Direction
# ---------------------------------------------------------------------------

class TestCompositeAndDirection:
    def test_bullish_accumulation(self):
        """Closes near highs -> high CMF, high accumulation score."""
        df = _make_df(n=50, trend=2.0)
        df["close"] = df["high"] - 0.1
        cmf = _compute_cmf(df)
        assert cmf > 0.5
        assert _score_accumulation_distribution(cmf) == 80

    def test_bearish_distribution(self):
        """Closes near lows -> negative CMF, low accumulation score."""
        df = _make_df(n=50, trend=-2.0)
        df["close"] = df["low"] + 0.1
        cmf = _compute_cmf(df)
        assert cmf < -0.5
        assert _score_accumulation_distribution(cmf) == 20

    def test_high_imbalance_low_score(self):
        """All closes at high -> VPIN near 1.0 -> flow_imbalance score < 50."""
        df = _make_df(n=50)
        df["close"] = df["high"]
        imbalance = _bvc_imbalance(df)
        vpin = float(np.nanmean(imbalance.iloc[-20:]))
        assert vpin > 0.7
        assert _score_flow_imbalance(vpin) <= 15


# ---------------------------------------------------------------------------
# Test 7: Graceful Degradation (monkeypatch _load_data)
# ---------------------------------------------------------------------------

class TestGracefulDegradation:
    def test_too_few_bars(self, monkeypatch):
        """DataFrame with only 10 rows -> returns None."""
        import tradingagents.agents.utils.flow_toxicity_engine as ft_mod
        monkeypatch.setattr(ft_mod, "_load_data", lambda ticker: _make_df(n=10))
        result = build_flow_toxicity_snapshot("TEST")
        assert result is None

    def test_failed_data_load(self, monkeypatch):
        """When data load raises RuntimeError -> returns None."""
        import tradingagents.agents.utils.flow_toxicity_engine as ft_mod
        def _raise(ticker):
            raise RuntimeError("Network error")
        monkeypatch.setattr(ft_mod, "_load_data", _raise)
        result = build_flow_toxicity_snapshot("TEST")
        assert result is None

    def test_empty_df(self, monkeypatch):
        """Empty DataFrame -> returns None."""
        import tradingagents.agents.utils.flow_toxicity_engine as ft_mod
        monkeypatch.setattr(ft_mod, "_load_data", lambda ticker: pd.DataFrame())
        result = build_flow_toxicity_snapshot("TEST")
        assert result is None


# ---------------------------------------------------------------------------
# Test 8: Scorer Integration
# ---------------------------------------------------------------------------

class MockLLM:
    def invoke(self, messages):
        class MockResponse:
            content = '{"fundamental_score": 70, "technical_score": 65, "macro_score": 60, "sentiment_score": 75, "momentum_score": 68, "confidence": 3, "score_rationales": {}}'
        return MockResponse()


class TestScorerIntegration:
    def test_scorer_blends_flow_toxicity(self, monkeypatch):
        """Flow toxicity at 20 should pull anchored_sentiment down."""
        import tradingagents.graph.aeternus_scoring as scoring_module
        monkeypatch.setattr(scoring_module, "get_ff_factors", lambda lookback_days=60: None)

        scorer = AeternusScorer(MockLLM())
        state = {"market_report": "Test"}

        # With sentiment + flow toxicity (low score = bearish)
        sentiment_metrics = {
            "composite_score": 70,
            "av_sentiment": {"score": 0.3},
            "text_sentiment": {"social_score": 70},
            "buzz": {"total_articles": 10},
            "direction": "BULLISH",
        }
        ft_metrics = {
            "composite_score": 20,
            "toxicity_level": "HIGH",
            "vpin_proxy": 0.6,
            "direction": "BEARISH",
        }

        rating_no_ft = scorer.score(state, sentiment_metrics=sentiment_metrics)
        rating_with_ft = scorer.score(state, sentiment_metrics=sentiment_metrics,
                                      flow_toxicity_metrics=ft_metrics)

        # Flow toxicity at 20 should pull sentiment DOWN
        assert rating_with_ft["breakdown"]["sentiment"] < rating_no_ft["breakdown"]["sentiment"]
        assert rating_with_ft["flow_toxicity_sub"] is not None
        assert rating_with_ft["flow_toxicity_sub"]["composite_score"] == 20
        assert rating_with_ft["flow_toxicity_sub"]["toxicity_level"] == "HIGH"

    def test_scorer_ignores_absent_flow_toxicity(self, monkeypatch):
        """When flow_toxicity_metrics is None, sentiment unchanged, sub is None."""
        import tradingagents.graph.aeternus_scoring as scoring_module
        monkeypatch.setattr(scoring_module, "get_ff_factors", lambda lookback_days=60: None)

        scorer = AeternusScorer(MockLLM())
        state = {"market_report": "Test"}

        rating1 = scorer.score(state)
        rating2 = scorer.score(state, flow_toxicity_metrics=None)

        assert rating1["breakdown"]["sentiment"] == rating2["breakdown"]["sentiment"]
        assert rating2["flow_toxicity_sub"] is None

    def test_flow_toxicity_sub_fields(self, monkeypatch):
        """flow_toxicity_sub dict has expected keys when metrics provided."""
        import tradingagents.graph.aeternus_scoring as scoring_module
        monkeypatch.setattr(scoring_module, "get_ff_factors", lambda lookback_days=60: None)

        scorer = AeternusScorer(MockLLM())
        state = {"market_report": "Test"}
        ft_metrics = {
            "composite_score": 45,
            "toxicity_level": "MODERATE",
            "vpin_proxy": 0.35,
            "direction": "NEUTRAL",
        }

        rating = scorer.score(state, flow_toxicity_metrics=ft_metrics)
        sub = rating["flow_toxicity_sub"]
        assert sub is not None
        assert sub["composite_score"] == 45
        assert sub["toxicity_level"] == "MODERATE"
        assert sub["vpin_proxy"] == 0.35
        assert sub["direction"] == "NEUTRAL"
