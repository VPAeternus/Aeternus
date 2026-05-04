import sys
import types
import pytest

# Stub chromadb
if "chromadb" not in sys.modules or not hasattr(sys.modules.get("chromadb", None), "__path__"):
    _stub = types.ModuleType("chromadb")
    _stub.__path__ = []
    _stub.Client = None
    _config_stub = types.ModuleType("chromadb.config")
    _config_stub.Settings = type("Settings", (), {})
    sys.modules["chromadb"] = _stub
    sys.modules["chromadb.config"] = _config_stub

from tradingagents.graph.model_router import (
    is_large_cap,
    select_analyst_tier,
    get_llm_for_tier,
    should_use_dynamic_routing,
    _LARGE_CAP_TICKERS,
    _LOW_COVERAGE_THRESHOLD,
)


class TestIsLargeCap:
    def test_aapl_is_large_cap(self):
        assert is_large_cap("AAPL") is True

    def test_spy_is_large_cap(self):
        assert is_large_cap("SPY") is True

    def test_unknown_not_large_cap(self):
        assert is_large_cap("ZZZZ") is False

    def test_case_insensitive(self):
        assert is_large_cap("aapl") is True
        assert is_large_cap("Msft") is True

    def test_whitespace_handled(self):
        assert is_large_cap("  AAPL  ") is True

    def test_large_cap_set_not_empty(self):
        assert len(_LARGE_CAP_TICKERS) >= 50


class TestSelectAnalystTier:
    def test_low_coverage_returns_deep(self):
        assert select_analyst_tier(0.2, "AAPL") == "deep"

    def test_high_coverage_large_cap_returns_quick(self):
        assert select_analyst_tier(0.8, "AAPL") == "quick"

    def test_high_coverage_small_cap_returns_deep(self):
        assert select_analyst_tier(0.8, "ZZZZ") == "deep"

    def test_threshold_boundary_below(self):
        assert select_analyst_tier(0.39, "AAPL") == "deep"

    def test_threshold_boundary_at(self):
        assert select_analyst_tier(0.4, "AAPL") == "quick"

    def test_empty_ticker_returns_quick(self):
        # Empty ticker treated as falsy, so coverage-based decision applies
        assert select_analyst_tier(0.8, "") == "quick"
        assert select_analyst_tier(0.8) == "quick"

    def test_zero_coverage_returns_deep(self):
        assert select_analyst_tier(0.0, "AAPL") == "deep"

    def test_full_coverage_large_cap(self):
        assert select_analyst_tier(1.0, "MSFT") == "quick"


class TestGetLLMForTier:
    def test_deep_returns_deep_llm(self):
        quick = "quick_model"
        deep = "deep_model"
        assert get_llm_for_tier("deep", quick, deep) == "deep_model"

    def test_quick_returns_quick_llm(self):
        quick = "quick_model"
        deep = "deep_model"
        assert get_llm_for_tier("quick", quick, deep) == "quick_model"

    def test_unknown_tier_returns_quick(self):
        quick = "quick_model"
        deep = "deep_model"
        assert get_llm_for_tier("invalid", quick, deep) == "quick_model"

    def test_works_with_mock_objects(self):
        from unittest.mock import MagicMock
        quick = MagicMock(name="quick")
        deep = MagicMock(name="deep")
        assert get_llm_for_tier("deep", quick, deep) is deep
        assert get_llm_for_tier("quick", quick, deep) is quick


class TestShouldUseDynamicRouting:
    def test_default_is_false(self):
        assert should_use_dynamic_routing({}) is False

    def test_enabled_true(self):
        assert should_use_dynamic_routing({"analyst_dynamic_routing": True}) is True

    def test_explicit_false(self):
        assert should_use_dynamic_routing({"analyst_dynamic_routing": False}) is False

    def test_truthy_value(self):
        assert should_use_dynamic_routing({"analyst_dynamic_routing": 1}) is True

    def test_falsy_value(self):
        assert should_use_dynamic_routing({"analyst_dynamic_routing": 0}) is False


class TestThresholdConsistency:
    def test_matches_scorer_threshold(self):
        """Model router threshold should match scorer MIN_ANCHOR_COVERAGE."""
        from tradingagents.graph.aeternus_scoring import MIN_ANCHOR_COVERAGE
        assert _LOW_COVERAGE_THRESHOLD == MIN_ANCHOR_COVERAGE

    def test_matches_epistemic_threshold(self):
        """Should match epistemic LOW boundary."""
        from tradingagents.graph.epistemic import _coverage_to_tier
        assert _coverage_to_tier(_LOW_COVERAGE_THRESHOLD) != "LOW"
        assert _coverage_to_tier(_LOW_COVERAGE_THRESHOLD - 0.01) == "LOW"

    def test_threshold_is_0_4(self):
        assert _LOW_COVERAGE_THRESHOLD == 0.4
