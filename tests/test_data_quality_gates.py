import sys
import types
import pytest
from unittest.mock import MagicMock

# Stub chromadb
if "chromadb" not in sys.modules or not hasattr(sys.modules.get("chromadb", None), "__path__"):
    _stub = types.ModuleType("chromadb")
    _stub.__path__ = []
    _stub.Client = None
    _config_stub = types.ModuleType("chromadb.config")
    _config_stub.Settings = type("Settings", (), {})
    sys.modules["chromadb"] = _stub
    sys.modules["chromadb.config"] = _config_stub

from tradingagents.graph.aeternus_scoring import AeternusScorer, MIN_ANCHOR_COVERAGE


class _MockLLM:
    """Mock LLM that returns valid scorer JSON."""
    def invoke(self, messages):
        class R:
            content = '{"fundamental_score":60,"technical_score":55,"macro_score":50,"sentiment_score":65,"momentum_score":58,"confidence":3,"score_rationales":{}}'
        return R()


def _base_state():
    return {"ticker": "TEST", "date": "2025-01-01", "market_report": "x", "sentiment_report": "x", "news_report": "x", "fundamentals_report": "x"}


def _high_coverage_fundamental():
    """Fundamental metrics with data_coverage above threshold."""
    return {
        "data_coverage": 0.8,
        "ratios": {"pe": 20, "forward_pe": 18, "peg": 1.5, "roe": 15, "roa": 8,
                   "quarterly_revenue_growth_yoy": 10, "quarterly_earnings_growth_yoy": 12},
        "balance": {"current_ratio": 1.8, "debt_to_equity": 0.9, "da_trend": "stable",
                    "equity_trend": "improving"},
        "cashflow": {"fcf_positive": True, "ocf": 5000, "net_income": 4000, "ocf_trend": "improving"},
        "income": {"net_income": 4000, "margin_trend": "improving", "revenue_trend": "improving",
                   "revenue_growth_qoq": 5},
        "piotroski": {"fscore": 7, "missing_criteria": 1},
    }


def _low_coverage_fundamental():
    m = _high_coverage_fundamental()
    m["data_coverage"] = 0.2
    return m


def _high_coverage_sentiment():
    return {"data_coverage": 0.7, "composite_score": 65, "buzz": {"total_articles": 20, "source_quality": "medium"}, "text_sentiment": {"social_score": 60, "catalyst_score": 55}}


def _low_coverage_sentiment():
    m = _high_coverage_sentiment()
    m["data_coverage"] = 0.1
    return m


def _high_coverage_macro():
    return {"data_coverage": 0.9, "regime": "NEUTRAL", "subscores": {"regime_fit": 60, "monetary_stress": 55, "rate_headwind": 50, "commodity_cycle": 65}}


def _low_coverage_macro():
    m = _high_coverage_macro()
    m["data_coverage"] = 0.3
    return m


def _high_coverage_momentum():
    return {"data_coverage": 0.85, "subscores": {"trend_strength": 70, "momentum_health": 65, "regime_quality": 60, "volume_confirmation": 55}}


def _low_coverage_momentum():
    m = _high_coverage_momentum()
    m["data_coverage"] = 0.15
    return m


class TestMinAnchorCoverageConstant:
    def test_equals_0_4(self):
        assert MIN_ANCHOR_COVERAGE == 0.4

    def test_matches_epistemic_threshold(self):
        """Should match epistemic._coverage_to_tier LOW boundary."""
        from tradingagents.graph.epistemic import _coverage_to_tier
        assert _coverage_to_tier(MIN_ANCHOR_COVERAGE) != "LOW"
        assert _coverage_to_tier(MIN_ANCHOR_COVERAGE - 0.01) == "LOW"


class TestFundamentalGate:
    def test_high_coverage_anchors(self):
        scorer = AeternusScorer(_MockLLM())
        rating = scorer.score(_base_state(), fundamental_metrics=_high_coverage_fundamental())
        assert rating["fundamental_sub"] is not None
        assert rating["data_quality_gate"]["fundamental"] is False

    def test_low_coverage_falls_back(self):
        scorer = AeternusScorer(_MockLLM())
        rating = scorer.score(_base_state(), fundamental_metrics=_low_coverage_fundamental())
        assert rating["fundamental_sub"] is None
        assert rating["data_quality_gate"]["fundamental"] is True

    def test_exactly_0_4_passes(self):
        m = _high_coverage_fundamental()
        m["data_coverage"] = 0.4
        scorer = AeternusScorer(_MockLLM())
        rating = scorer.score(_base_state(), fundamental_metrics=m)
        assert rating["fundamental_sub"] is not None
        assert rating["data_quality_gate"]["fundamental"] is False


class TestSentimentGate:
    def test_high_coverage_anchors(self):
        scorer = AeternusScorer(_MockLLM())
        rating = scorer.score(_base_state(), sentiment_metrics=_high_coverage_sentiment())
        assert rating["sentiment_sub"] is not None
        assert rating["data_quality_gate"]["sentiment"] is False

    def test_low_coverage_falls_back(self):
        scorer = AeternusScorer(_MockLLM())
        rating = scorer.score(_base_state(), sentiment_metrics=_low_coverage_sentiment())
        assert rating["sentiment_sub"] is None
        assert rating["data_quality_gate"]["sentiment"] is True


class TestMacroGate:
    def test_high_coverage_anchors(self):
        scorer = AeternusScorer(_MockLLM())
        rating = scorer.score(_base_state(), macro_metrics=_high_coverage_macro())
        assert rating["macro_sub"] is not None
        assert rating["data_quality_gate"]["macro"] is False

    def test_low_coverage_falls_back(self):
        scorer = AeternusScorer(_MockLLM())
        rating = scorer.score(_base_state(), macro_metrics=_low_coverage_macro())
        assert rating["macro_sub"] is None
        assert rating["data_quality_gate"]["macro"] is True


class TestMomentumGate:
    def test_high_coverage_anchors(self):
        scorer = AeternusScorer(_MockLLM())
        rating = scorer.score(_base_state(), momentum_metrics=_high_coverage_momentum())
        assert rating["momentum_sub"] is not None
        assert rating["data_quality_gate"]["momentum"] is False

    def test_low_coverage_falls_back(self):
        scorer = AeternusScorer(_MockLLM())
        rating = scorer.score(_base_state(), momentum_metrics=_low_coverage_momentum())
        assert rating["momentum_sub"] is None
        assert rating["data_quality_gate"]["momentum"] is True


class TestDataQualityGateField:
    def test_field_present(self):
        scorer = AeternusScorer(_MockLLM())
        rating = scorer.score(_base_state())
        assert "data_quality_gate" in rating

    def test_all_high_coverage_all_false(self):
        scorer = AeternusScorer(_MockLLM())
        rating = scorer.score(
            _base_state(),
            fundamental_metrics=_high_coverage_fundamental(),
            sentiment_metrics=_high_coverage_sentiment(),
            macro_metrics=_high_coverage_macro(),
            momentum_metrics=_high_coverage_momentum(),
        )
        gate = rating["data_quality_gate"]
        assert all(v is False for v in gate.values())

    def test_all_low_coverage_all_true(self):
        scorer = AeternusScorer(_MockLLM())
        rating = scorer.score(
            _base_state(),
            fundamental_metrics=_low_coverage_fundamental(),
            sentiment_metrics=_low_coverage_sentiment(),
            macro_metrics=_low_coverage_macro(),
            momentum_metrics=_low_coverage_momentum(),
        )
        gate = rating["data_quality_gate"]
        assert all(v is True for v in gate.values())

    def test_four_keys(self):
        scorer = AeternusScorer(_MockLLM())
        rating = scorer.score(_base_state())
        gate = rating["data_quality_gate"]
        assert set(gate.keys()) == {"fundamental", "sentiment", "macro", "momentum"}

    def test_none_metrics_not_gated(self):
        """When metrics are None (not provided), gate should be False (not triggered)."""
        scorer = AeternusScorer(_MockLLM())
        rating = scorer.score(_base_state())
        gate = rating["data_quality_gate"]
        assert gate["fundamental"] is False
        assert gate["sentiment"] is False
        assert gate["macro"] is False
        assert gate["momentum"] is False


class TestBackwardsCompatibility:
    def test_none_metrics_unchanged(self):
        """score() with no metrics should work exactly as before."""
        scorer = AeternusScorer(_MockLLM())
        rating = scorer.score(_base_state())
        assert rating["fundamental_sub"] is None
        assert rating["sentiment_sub"] is None
        assert rating["macro_sub"] is None
        assert rating["momentum_sub"] is None

    def test_options_unaffected(self):
        """Options metrics don't have a data quality gate."""
        scorer = AeternusScorer(_MockLLM())
        opts = {"sentiment_score": 55, "fear_greed": "NEUTRAL"}
        rating = scorer.score(_base_state(), options_metrics=opts)
        assert rating["options_sub"] is not None

    def test_flow_toxicity_unaffected(self):
        """Flow toxicity doesn't have a data quality gate."""
        scorer = AeternusScorer(_MockLLM())
        ft = {"composite_score": 45, "toxicity_level": "LOW"}
        rating = scorer.score(_base_state(), flow_toxicity_metrics=ft)
        assert rating["flow_toxicity_sub"] is not None
