"""Tests for tradingagents.agents.utils.options_engine"""

import sys
import types
import pytest

# Stub chromadb before it can be imported (pydantic v1 incompatible with Python 3.14)
if "chromadb" not in sys.modules or not hasattr(sys.modules.get("chromadb", None), "__path__"):
    _stub = types.ModuleType("chromadb")
    _stub.__path__ = []
    _stub.Client = None
    _config_stub = types.ModuleType("chromadb.config")
    _config_stub.Settings = type("Settings", (), {})
    sys.modules["chromadb"] = _stub
    sys.modules["chromadb.config"] = _config_stub

from tradingagents.agents.utils.options_engine import (
    _score_put_call_ratio,
    _score_iv_skew,
    _score_oi_ratio,
    build_options_snapshot,
)
from tradingagents.graph.aeternus_scoring import AeternusScorer


# ---------------------------------------------------------------------------
# Scoring function unit tests
# ---------------------------------------------------------------------------

class TestPutCallRatioScoring:
    def test_extreme_fear(self):
        """Ratio > 1.2 -> score 20 (extreme fear)."""
        assert _score_put_call_ratio(1.5) == 20.0

    def test_mild_fear(self):
        """Ratio 0.9-1.2 -> score 40."""
        assert _score_put_call_ratio(1.0) == 40.0

    def test_neutral(self):
        """Ratio 0.6-0.9 -> score 55."""
        assert _score_put_call_ratio(0.75) == 55.0

    def test_greed(self):
        """Ratio < 0.6 -> score 75."""
        assert _score_put_call_ratio(0.4) == 75.0


class TestIVSkewScoring:
    def test_high_skew_fear(self):
        """Skew > 0.10 -> score 25 (fear premium)."""
        assert _score_iv_skew(0.15) == 25.0

    def test_moderate_skew(self):
        """Skew 0.03-0.10 -> score 55 (normal)."""
        assert _score_iv_skew(0.06) == 55.0

    def test_flat_skew_complacency(self):
        """Skew <= 0.03 -> score 70 (complacency)."""
        assert _score_iv_skew(0.01) == 70.0


class TestOIRatioScoring:
    def test_extreme_fear(self):
        assert _score_oi_ratio(1.5) == 20.0

    def test_mild_fear(self):
        assert _score_oi_ratio(1.0) == 40.0

    def test_neutral(self):
        assert _score_oi_ratio(0.75) == 55.0

    def test_greed(self):
        assert _score_oi_ratio(0.4) == 75.0


# ---------------------------------------------------------------------------
# Composite score tests
# ---------------------------------------------------------------------------

class TestSentimentComposite:
    def test_sentiment_score_fear(self):
        """High put/call + high skew -> low composite score (fear)."""
        # pc=1.5 -> 20, skew=0.15 -> 25, oi=1.3 -> 20
        # composite = 20*0.40 + 25*0.30 + 20*0.30 = 8+7.5+6 = 21.5 -> 22
        pc = _score_put_call_ratio(1.5)
        skew = _score_iv_skew(0.15)
        oi = _score_oi_ratio(1.3)
        composite = round(pc * 0.40 + skew * 0.30 + oi * 0.30)
        assert composite < 35  # FEAR territory

    def test_sentiment_score_greed(self):
        """Low put/call + flat skew -> high composite score (greed)."""
        # pc=0.4 -> 75, skew=0.01 -> 70, oi=0.5 -> 55
        pc = _score_put_call_ratio(0.4)
        skew = _score_iv_skew(0.01)
        oi = _score_oi_ratio(0.5)
        composite = round(pc * 0.40 + skew * 0.30 + oi * 0.30)
        assert composite > 65  # GREED territory


# ---------------------------------------------------------------------------
# build_options_snapshot graceful failure
# ---------------------------------------------------------------------------

class TestBuildOptionsSnapshot:
    def test_graceful_failure_no_options(self, monkeypatch):
        """Ticker with no options returns None."""
        import tradingagents.agents.utils.options_engine as opt_module

        # Mock yfinance with no options
        class MockTicker:
            options = []  # empty = no options available
            def history(self, **kwargs):
                import pandas as pd
                return pd.DataFrame({"Close": [150.0]})

        yf_mock = types.ModuleType("yfinance")
        yf_mock.Ticker = lambda t: MockTicker()
        monkeypatch.setitem(sys.modules, "yfinance", yf_mock)

        # Need to reimport to pick up mock
        import importlib
        importlib.reload(opt_module)
        result = opt_module.build_options_snapshot("FAKE")
        assert result is None

    def test_graceful_failure_exception(self, monkeypatch):
        """When yfinance raises an exception, returns None."""
        import tradingagents.agents.utils.options_engine as opt_module

        yf_mock = types.ModuleType("yfinance")
        def raise_err(t):
            raise RuntimeError("network error")
        yf_mock.Ticker = raise_err
        monkeypatch.setitem(sys.modules, "yfinance", yf_mock)

        import importlib
        importlib.reload(opt_module)
        result = opt_module.build_options_snapshot("FAKE")
        assert result is None


# ---------------------------------------------------------------------------
# Scorer integration tests
# ---------------------------------------------------------------------------

class MockLLM:
    def invoke(self, messages):
        class MockResponse:
            content = '{"fundamental_score": 70, "technical_score": 65, "macro_score": 60, "sentiment_score": 75, "momentum_score": 68, "confidence": 3, "score_rationales": {}}'
        return MockResponse()


class TestScorerOptionsIntegration:
    def test_scorer_blends_options(self, monkeypatch):
        """When options_metrics provided, sentiment score is blended 70/30."""
        import tradingagents.graph.aeternus_scoring as scoring_module

        # Mock FF factors to avoid network calls
        monkeypatch.setattr(scoring_module, "get_ff_factors", lambda lookback_days=60: None)

        scorer = AeternusScorer(MockLLM())
        state = {"market_report": "Test"}

        # Without options
        rating_no_opts = scorer.score(state)
        sentiment_no_opts = rating_no_opts["breakdown"]["sentiment"]

        # With options (low score = fear)
        options_metrics = {
            "sentiment_score": 20,
            "fear_greed": "FEAR",
            "put_call_volume_ratio": 1.5,
            "iv_skew": 0.12,
        }
        rating_with_opts = scorer.score(state, options_metrics=options_metrics)
        sentiment_with_opts = rating_with_opts["breakdown"]["sentiment"]

        # Options with score=20 should pull sentiment DOWN
        assert sentiment_with_opts < sentiment_no_opts
        assert rating_with_opts["options_sub"] is not None
        assert rating_with_opts["options_sub"]["sentiment_score"] == 20
        assert rating_with_opts["options_sub"]["fear_greed"] == "FEAR"

    def test_scorer_ignores_absent_options(self, monkeypatch):
        """When options_metrics is None, sentiment score is unchanged."""
        import tradingagents.graph.aeternus_scoring as scoring_module

        monkeypatch.setattr(scoring_module, "get_ff_factors", lambda lookback_days=60: None)

        scorer = AeternusScorer(MockLLM())
        state = {"market_report": "Test"}

        rating1 = scorer.score(state)
        rating2 = scorer.score(state, options_metrics=None)

        assert rating1["breakdown"]["sentiment"] == rating2["breakdown"]["sentiment"]
        assert rating2["options_sub"] is None
