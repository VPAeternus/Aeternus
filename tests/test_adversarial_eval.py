"""Adversarial evaluation tests for AeternusAgents engines and scorer.

These tests import existing engines and the scorer to verify they do not produce
nonsensical outputs under boundary, edge-case, and adversarial inputs.
No production code changes are made — this is a pure test file.
"""

import sys
import types
import json
import pytest

# Stub chromadb before any project imports
if "chromadb" not in sys.modules or not hasattr(sys.modules.get("chromadb", None), "__path__"):
    _stub = types.ModuleType("chromadb")
    _stub.__path__ = []
    _stub.Client = None
    _config_stub = types.ModuleType("chromadb.config")
    _config_stub.Settings = type("Settings", (), {})
    sys.modules["chromadb"] = _stub
    sys.modules["chromadb.config"] = _config_stub

from tradingagents.agents.utils.fundamental_engine import (
    compute_ratios,
    compute_balance_sheet_metrics,
    compute_cashflow_metrics,
    compute_income_metrics,
    compute_piotroski_fscore,
    build_fundamental_snapshot,
    _safe_div,
    _num,
)
from tradingagents.graph.aeternus_scoring import AeternusScorer


# ---------------------------------------------------------------------------
# Shared mock LLM — defined once at module level for all test classes
# ---------------------------------------------------------------------------

class _MockLLM:
    """Minimal LLM stub that returns a valid JSON score payload."""

    def invoke(self, messages):
        class _Response:
            content = (
                '{"fundamental_score":50,"technical_score":50,'
                '"macro_score":50,"sentiment_score":50,"momentum_score":50,'
                '"confidence":3,"score_rationales":{}}'
            )

        return _Response()


# ===========================================================================
# TestNumericPrecision — computed values must always be within valid ranges
# ===========================================================================

class TestNumericPrecision:
    def test_fscore_always_0_to_9(self):
        """F-Score must be 0-9 regardless of input."""
        income = {
            "net_income": 100,
            "margin_trend": "improving",
            "revenue_trend": "improving",
        }
        balance = {
            "da_trend": "declining",
            "current_ratio": 2.0,
            "equity_trend": "improving",
        }
        cashflow = {
            "fcf_positive": True,
            "ocf": 200,
            "net_income": 100,
            "ocf_trend": "improving",
        }
        ratios = {"roa": 10}
        result = compute_piotroski_fscore(income, balance, cashflow, ratios)
        assert 0 <= result["fscore"] <= 9

    def test_fscore_worst_case(self):
        """F-Score with all failing criteria must still be in [0, 9]."""
        income = {
            "net_income": -100,
            "margin_trend": "declining",
            "revenue_trend": "declining",
        }
        balance = {
            "da_trend": "improving",
            "current_ratio": 0.5,
            "equity_trend": "declining",
        }
        cashflow = {
            "fcf_positive": False,
            "ocf": -50,
            "net_income": 100,
            "ocf_trend": "declining",
        }
        ratios = {"roa": -5}
        result = compute_piotroski_fscore(income, balance, cashflow, ratios)
        assert 0 <= result["fscore"] <= 9

    def test_fscore_is_integer(self):
        """F-Score must be a plain Python int, not float or None."""
        income = {
            "net_income": 100,
            "margin_trend": "stable",
            "revenue_trend": "stable",
        }
        balance = {
            "da_trend": "stable",
            "current_ratio": 1.5,
            "equity_trend": "stable",
        }
        cashflow = {
            "fcf_positive": True,
            "ocf": 150,
            "net_income": 100,
        }
        ratios = {"roa": 5}
        result = compute_piotroski_fscore(income, balance, cashflow, ratios)
        assert isinstance(result["fscore"], int)

    def test_pe_negative_allowed(self):
        """Negative P/E is valid (company losing money) and must round-trip."""
        ratios = compute_ratios({"PERatio": "-15.5"})
        assert ratios["pe"] == -15.5

    def test_pe_zero_handled(self):
        """Zero P/E should parse without error."""
        ratios = compute_ratios({"PERatio": "0"})
        assert ratios["pe"] == 0.0

    def test_sentiment_composite_bounded(self):
        """Sentiment snapshot composite_score must be bounded [0, 100]."""
        from tradingagents.agents.utils.sentiment_engine import build_sentiment_snapshot

        result = build_sentiment_snapshot(
            av_news_raw="{}",
            xai_social_raw="",
            ticker="TEST",
        )
        composite = result.get("composite_score", 50)
        assert 0 <= composite <= 100

    def test_roe_extreme_values_no_crash(self):
        """Extreme ROE values should not crash ratio computation."""
        ratios = compute_ratios({"ReturnOnEquityTTM": "999.99"})
        assert ratios["roe"] == 999.99

        ratios_neg = compute_ratios({"ReturnOnEquityTTM": "-500"})
        assert ratios_neg["roe"] == -500.0


# ===========================================================================
# TestBoundaryValues — outputs must stay within documented bounds
# ===========================================================================

class TestBoundaryValues:
    def test_data_coverage_bounded(self):
        """build_fundamental_snapshot data_coverage must be in [0, 1]."""
        result = build_fundamental_snapshot("{}", "{}", "{}", "{}")
        assert 0.0 <= result["data_coverage"] <= 1.0

    def test_empty_input_coverage_is_zero_or_low(self):
        """Empty inputs should yield very low data_coverage (all fields missing)."""
        result = build_fundamental_snapshot("{}", "{}", "{}", "{}")
        assert result["data_coverage"] <= 0.1

    def test_fundamental_sub_quality_bounded(self):
        """All sub-scores returned by _compute_fundamental_sub must be [0, 100]."""
        scorer = AeternusScorer(_MockLLM())
        metrics = {
            "piotroski": {"fscore": 9, "missing_criteria": 0},
            "ratios": {
                "roe": 99,
                "pe": 5,
                "forward_pe": 4,
                "peg": 0.5,
                "quarterly_revenue_growth_yoy": 50,
            },
            "balance": {
                "current_ratio": 5.0,
                "debt_to_equity": 0.1,
                "da_trend": "declining",
                "equity_trend": "improving",
            },
            "cashflow": {
                "fcf_positive": True,
                "ocf": 1000,
                "net_income": 500,
                "ocf_trend": "improving",
            },
            "income": {
                "net_income": 500,
                "margin_trend": "improving",
                "revenue_trend": "improving",
                "revenue_growth_qoq": 30,
            },
            "data_coverage": 0.9,
        }
        sub = scorer._compute_fundamental_sub(metrics)
        for key in ("quality", "growth", "health", "valuation"):
            assert 0 <= sub[key] <= 100, f"{key}={sub[key]} out of bounds"

    def test_fundamental_sub_health_bounded_negative_cr(self):
        """Health sub-score should handle negative current_ratio gracefully."""
        scorer = AeternusScorer(_MockLLM())
        metrics = {
            "piotroski": {"fscore": 0},
            "ratios": {"roe": -50},
            "balance": {"current_ratio": -1.0, "debt_to_equity": 10.0},
            "cashflow": {"fcf_positive": False, "ocf_trend": "declining"},
            "income": {"margin_trend": "declining", "revenue_trend": "declining"},
            "data_coverage": 0.5,
        }
        sub = scorer._compute_fundamental_sub(metrics)
        assert 0 <= sub["health"] <= 100

    def test_macro_clamp_helper(self):
        """_clamp_score must bound any value to [0, 100] and handle non-numeric input."""
        scorer = AeternusScorer(_MockLLM())
        assert scorer._clamp_score(150) == 100
        assert scorer._clamp_score(-20) == 0
        assert scorer._clamp_score(50) == 50
        assert scorer._clamp_score("invalid") == 50


# ===========================================================================
# TestNaNPropagation — NaN/None inputs must not propagate silently
# ===========================================================================

class TestNaNPropagation:
    def test_empty_overview_no_nan_ratios(self):
        """Empty overview dict must yield None (not NaN) for every ratio."""
        ratios = compute_ratios({})
        for key, val in ratios.items():
            assert val is None, f"{key} should be None for empty input, got {val}"

    def test_empty_reports_no_nan_balance(self):
        """Empty report list must return an error sentinel, not crash."""
        result = compute_balance_sheet_metrics([])
        assert result.get("error") == "no_data"

    def test_safe_div_zero_denominator(self):
        """Division by zero must return None, not raise."""
        assert _safe_div(10, 0) is None
        assert _safe_div(0, 0) is None

    def test_safe_div_none_inputs(self):
        """None numerator or denominator must return None."""
        assert _safe_div(None, 5) is None
        assert _safe_div(5, None) is None

    def test_num_nan_string(self):
        """_num('nan') should return None or a float, never raise an exception."""
        result = _num("nan")
        # float("nan") is valid Python; implementation may return it or None
        assert result is None or isinstance(result, float)

    def test_piotroski_all_none_no_nan(self):
        """All-None inputs should produce fscore=0 and missing_criteria=9."""
        income = {"net_income": None, "margin_trend": None, "revenue_trend": None}
        balance = {"da_trend": None, "current_ratio": None, "equity_trend": None}
        cashflow = {"fcf_positive": None, "ocf": None, "net_income": None}
        ratios = {"roa": None}
        result = compute_piotroski_fscore(income, balance, cashflow, ratios)
        assert isinstance(result["fscore"], int)
        assert result["fscore"] == 0
        assert result["missing_criteria"] == 9


# ===========================================================================
# TestImpossibleStates — extreme and contradictory scores must not crash
# ===========================================================================

class TestImpossibleStates:
    def test_quality_100_growth_0_coherence_survives(self):
        """Extreme sub-score combinations should not crash coherence engine."""
        from tradingagents.graph.coherence_engine import build_coherence_snapshot

        pillar_composites = {
            "fundamental": 100,
            "macro": 50,
            "sentiment": 50,
            "momentum": 50,
            "coherence": 50,
        }
        fundamental_sub = {"quality": 100, "growth": 0, "health": 50, "valuation": 50}
        result = build_coherence_snapshot(
            pillar_composites, fundamental_sub=fundamental_sub
        )
        assert "composite_score" in result
        assert 0 <= result["composite_score"] <= 100

    def test_all_zero_scores_bounded(self):
        """All-zero pillar scores should produce a composite in [0, 100]."""
        from tradingagents.graph.coherence_engine import build_coherence_snapshot

        pillars = {
            "fundamental": 0,
            "macro": 0,
            "sentiment": 0,
            "momentum": 0,
            "coherence": 0,
        }
        result = build_coherence_snapshot(pillars)
        assert 0 <= result["composite_score"] <= 100

    def test_all_100_scores_bounded(self):
        """All-100 pillar scores should produce a composite in [0, 100]."""
        from tradingagents.graph.coherence_engine import build_coherence_snapshot

        pillars = {
            "fundamental": 100,
            "macro": 100,
            "sentiment": 100,
            "momentum": 100,
            "coherence": 100,
        }
        result = build_coherence_snapshot(pillars)
        assert 0 <= result["composite_score"] <= 100

    def test_negative_current_ratio_no_crash(self):
        """Negative current ratio (e.g., negative equity) should not crash balance sheet metrics."""
        reports = [
            {
                "totalCurrentAssets": "-1000",
                "totalCurrentLiabilities": "500",
                "totalAssets": "1000",
                "totalLiabilities": "2000",
                "totalShareholderEquity": "-1000",
            }
        ]
        result = compute_balance_sheet_metrics(reports)
        # -2.0 is valid math and should be returned as-is
        assert result["current_ratio"] is not None

    def test_empty_strings_no_crash(self):
        """All empty-string values should produce None ratios without crashing."""
        overview = {
            k: ""
            for k in [
                "PERatio",
                "PEGRatio",
                "EVToEBITDA",
                "ReturnOnEquityTTM",
                "ReturnOnAssetsTTM",
                "GrossProfitTTM",
                "RevenueTTM",
            ]
        }
        ratios = compute_ratios(overview)
        for val in ratios.values():
            assert val is None


# ===========================================================================
# TestTickerDisambiguation — universe membership and integrity checks
# ===========================================================================

class TestTickerDisambiguation:
    def test_meta_in_akg_universe(self):
        """META (Facebook) should be present in the AKG-sourced universe."""
        from tradingagents.dealflow.akg_universe import build_universe_from_akg
        rows = build_universe_from_akg()
        symbols = {r["symbol"] for r in rows}
        assert "META" in symbols

    def test_brk_b_in_akg_universe(self):
        """Berkshire Hathaway B-shares should be present in AKG universe."""
        from tradingagents.dealflow.akg_universe import build_universe_from_akg
        rows = build_universe_from_akg()
        symbols = {r["symbol"] for r in rows}
        assert "BRK-B" in symbols

    def test_googl_in_akg_universe(self):
        """Alphabet should be present in AKG universe under GOOGL."""
        from tradingagents.dealflow.akg_universe import build_universe_from_akg
        rows = build_universe_from_akg()
        symbols = {r["symbol"] for r in rows}
        assert "GOOGL" in symbols

    def test_no_duplicates_in_akg_universe(self):
        """AKG universe must contain no duplicate symbols."""
        from tradingagents.dealflow.akg_universe import build_universe_from_akg
        rows = build_universe_from_akg()
        symbols = [r["symbol"] for r in rows]
        assert len(symbols) == len(set(symbols))

    def test_no_overlap_equity_etf(self):
        """No symbol should be both Equity and ETF in AKG universe."""
        from tradingagents.dealflow.akg_universe import build_universe_from_akg
        rows = build_universe_from_akg()
        equities = {r["symbol"] for r in rows if r["asset_class"] == "Equity"}
        etfs = {r["symbol"] for r in rows if r["asset_class"] == "ETF"}
        overlap = equities & etfs
        assert len(overlap) == 0, f"Overlap between equities and ETFs: {overlap}"


# ===========================================================================
# TestScorerEdgeCases — scorer robustness and rating threshold correctness
# ===========================================================================

class TestScorerEdgeCases:
    def test_all_none_metrics_valid_rating(self):
        """scorer.score() with no optional metrics must still return a valid rating."""
        scorer = AeternusScorer(_MockLLM())
        state = {"ticker": "TEST", "date": "2025-01-01"}
        rating = scorer.score(state)
        assert 0 <= rating["aeternus_score"] <= 100
        assert rating["rating"] in ("Strong Buy", "Buy", "Hold", "Sell", "Strong Sell")

    def test_confidence_always_1_to_5(self):
        """Confidence field must always be clamped to [1, 5]."""
        scorer = AeternusScorer(_MockLLM())
        state = {"ticker": "TEST", "date": "2025-01-01"}
        rating = scorer.score(state)
        assert 1 <= rating["confidence"] <= 5

    def test_boundary_score_values(self):
        """Rating thresholds: >=80 Strong Buy, >=60 Buy, >=40 Hold, >=20 Sell, <20 Strong Sell."""
        scorer = AeternusScorer(_MockLLM())
        assert scorer._rating_from_score(100) == "Strong Buy"
        assert scorer._rating_from_score(80) == "Strong Buy"
        assert scorer._rating_from_score(79.9) == "Buy"
        assert scorer._rating_from_score(60) == "Buy"
        assert scorer._rating_from_score(59.9) == "Hold"
        assert scorer._rating_from_score(40) == "Hold"
        assert scorer._rating_from_score(39.9) == "Sell"
        assert scorer._rating_from_score(20) == "Sell"
        assert scorer._rating_from_score(19.9) == "Strong Sell"
        assert scorer._rating_from_score(0) == "Strong Sell"
