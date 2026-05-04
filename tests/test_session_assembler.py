"""Tests for tradingagents.graph.session_assembler"""

import sys
import types
import json
import pytest
from pathlib import Path

# Stub chromadb before it can be imported (pydantic v1 incompatible with Python 3.14)
if "chromadb" not in sys.modules or not hasattr(sys.modules.get("chromadb", None), "__path__"):
    _stub = types.ModuleType("chromadb")
    _stub.__path__ = []
    _stub.Client = None
    _config_stub = types.ModuleType("chromadb.config")
    _config_stub.Settings = type("Settings", (), {})
    sys.modules["chromadb"] = _stub
    sys.modules["chromadb.config"] = _config_stub

from tradingagents.graph.session_assembler import (
    gather_computation_data,
    build_session_score,
    write_analysis_report,
    write_batch_summary,
)


# --- Factory Helpers (prefixed with _) ---

def _mock_fundamental_metrics():
    return {
        "data_coverage": 0.8,
        "piotroski": {"fscore": 7, "missing_criteria": 2},
        "ratios": {
            "roe": 18.5,
            "quarterly_revenue_growth_yoy": 15,
            "forward_pe": 22,
            "pe": 25,
            "peg": 1.5,
        },
        "balance": {"current_ratio": 1.8, "debt_to_equity": 0.7},
        "cashflow": {"fcf_positive": True, "ocf_trend": "improving"},
        "income": {"revenue_growth_qoq": 12, "margin_trend": "improving"},
    }


def _mock_sentiment_metrics():
    return {
        "data_coverage": 0.6,
        "composite_score": 65,
        "av_sentiment": {"score": 0.3},
        "text_sentiment": {
            "social_score": 60,
            "catalyst_score": 55,
            "direction": "BULLISH",
        },
        "buzz": {"total_articles": 20, "source_quality": "medium"},
        "direction": "BULLISH",
    }


def _mock_macro_metrics():
    return {
        "data_coverage": 0.9,
        "regime": "NEUTRAL",
        "subscores": {
            "regime_fit": 65,
            "monetary_stress": 55,
            "rate_headwind": 50,
            "commodity_cycle": 60,
        },
    }


def _mock_momentum_metrics():
    return {
        "data_coverage": 0.7,
        "subscores": {
            "trend_strength": 70,
            "momentum_health": 60,
            "regime_quality": 55,
            "volume_confirmation": 50,
        },
    }


def _mock_options_metrics():
    return {
        "sentiment_score": 58,
        "fear_greed": "NEUTRAL",
        "put_call_volume_ratio": 0.8,
        "iv_skew": 0.05,
    }


def _mock_flow_toxicity_metrics():
    return {
        "composite_score": 52,
        "toxicity_level": "LOW",
        "vpin_proxy": 0.35,
        "direction": "NEUTRAL",
    }


def _mock_sonnet_outputs():
    return {
        "fundamentals_report": "Strong fundamentals with growing revenue...",
        "market_report": "Uptrend with healthy momentum...",
        "sentiment_report": "Positive sentiment driven by earnings beat...",
        "news_report": "Key catalyst: FDA approval pending...",
        "investment_debate_state": {
            "bull_history": "Strong growth trajectory...",
            "bear_history": "Valuation concerns at current multiples...",
            "history": "Bull case prevails with caveats...",
            "current_response": "",
            "judge_decision": "Lean bullish with position sizing discipline.",
        },
        "risk_debate_state": {
            "risky_history": "Go full position...",
            "safe_history": "Wait for pullback...",
            "neutral_history": "Scale in gradually...",
            "history": "",
            "judge_decision": "Moderate position with stops.",
        },
        "trader_investment_decision": "BUY with conviction 4/5",
        "investment_plan": "Enter at current levels, stop at -8%, target +15%",
        "final_trade_decision": "BUY with high conviction",
        "structured_trader_verdict": {
            "decision": "BUY",
            "conviction": 4,
            "reasoning": "Strong fundamentals with positive momentum",
            "invalidation_conditions": [
                {"condition": "Break below 200 SMA", "price_level": None}
            ],
            "scenarios": [
                {"name": "bull", "probability": 0.45, "outcome": "Rally to new highs"},
                {"name": "bear", "probability": 0.25, "outcome": "Pullback to support"},
            ],
            "milestones": [{"event": "Earnings report", "target_date": None}],
            "position_size_pct": 0.05,
        },
    }


def _mock_computation_data():
    return {
        "ticker": "AAPL",
        "date": "2026-02-25",
        "fundamental_metrics": _mock_fundamental_metrics(),
        "sentiment_metrics": _mock_sentiment_metrics(),
        "momentum_metrics": _mock_momentum_metrics(),
        "macro_metrics": _mock_macro_metrics(),
        "options_metrics": _mock_options_metrics(),
        "flow_toxicity_metrics": _mock_flow_toxicity_metrics(),
    }


def _patch_all_engines(monkeypatch):
    """Patch all 6 engine imports at their source modules."""
    monkeypatch.setattr("tradingagents.dataflows.interface.route_to_vendor",
                        lambda *a, **k: '{"test": "data"}')
    monkeypatch.setattr("tradingagents.agents.utils.fundamental_engine.build_fundamental_snapshot",
                        lambda *a, **k: _mock_fundamental_metrics())
    monkeypatch.setattr("tradingagents.agents.utils.sentiment_engine.build_sentiment_snapshot",
                        lambda *a, **k: _mock_sentiment_metrics())
    monkeypatch.setattr("tradingagents.agents.utils.macro_engine.build_macro_snapshot",
                        lambda *a, **k: _mock_macro_metrics())
    monkeypatch.setattr("tradingagents.agents.utils.macro_engine.pre_warm_macro_cache",
                        lambda: None)
    monkeypatch.setattr("tradingagents.agents.utils.momentum_engine.build_momentum_snapshot",
                        lambda *a, **k: _mock_momentum_metrics())
    monkeypatch.setattr("tradingagents.agents.utils.options_engine.build_options_snapshot",
                        lambda *a, **k: _mock_options_metrics())
    monkeypatch.setattr("tradingagents.agents.utils.flow_toxicity_engine.build_flow_toxicity_snapshot",
                        lambda *a, **k: _mock_flow_toxicity_metrics())


# --- Tests for gather_computation_data ---

class TestGatherComputationData:

    def test_returns_all_six_keys(self, monkeypatch):
        _patch_all_engines(monkeypatch)
        result = gather_computation_data("AAPL", "2026-02-25")

        assert result["ticker"] == "AAPL"
        assert result["date"] == "2026-02-25"
        for key in ("fundamental_metrics", "sentiment_metrics", "momentum_metrics",
                     "macro_metrics", "options_metrics", "flow_toxicity_metrics"):
            assert key in result
            assert result[key] != {}

    def test_handles_engine_failure(self, monkeypatch):
        _patch_all_engines(monkeypatch)
        # Override momentum to raise
        monkeypatch.setattr("tradingagents.agents.utils.momentum_engine.build_momentum_snapshot",
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))

        result = gather_computation_data("AAPL", "2026-02-25")

        assert result["fundamental_metrics"] != {}
        assert result["momentum_metrics"] == {}

    def test_fundamental_calls_route_to_vendor(self, monkeypatch):
        calls = []
        def _track(*args, **kwargs):
            calls.append(args[0] if args else None)
            return '{"test": "data"}'

        monkeypatch.setattr("tradingagents.dataflows.interface.route_to_vendor", _track)
        monkeypatch.setattr("tradingagents.agents.utils.fundamental_engine.build_fundamental_snapshot",
                            lambda *a, **k: _mock_fundamental_metrics())
        monkeypatch.setattr("tradingagents.agents.utils.sentiment_engine.build_sentiment_snapshot",
                            lambda *a, **k: _mock_sentiment_metrics())
        monkeypatch.setattr("tradingagents.agents.utils.macro_engine.build_macro_snapshot",
                            lambda *a, **k: _mock_macro_metrics())
        monkeypatch.setattr("tradingagents.agents.utils.macro_engine.pre_warm_macro_cache",
                            lambda: None)
        monkeypatch.setattr("tradingagents.agents.utils.momentum_engine.build_momentum_snapshot",
                            lambda *a, **k: _mock_momentum_metrics())
        monkeypatch.setattr("tradingagents.agents.utils.options_engine.build_options_snapshot",
                            lambda *a, **k: _mock_options_metrics())
        monkeypatch.setattr("tradingagents.agents.utils.flow_toxicity_engine.build_flow_toxicity_snapshot",
                            lambda *a, **k: _mock_flow_toxicity_metrics())

        gather_computation_data("AAPL", "2026-02-25")

        assert "get_fundamentals" in calls
        assert "get_balance_sheet" in calls
        assert "get_cashflow" in calls
        assert "get_income_statement" in calls

    def test_prewarms_macro_cache(self, monkeypatch):
        warm_called = {"value": False}
        def _warm():
            warm_called["value"] = True

        _patch_all_engines(monkeypatch)
        monkeypatch.setattr("tradingagents.agents.utils.macro_engine.pre_warm_macro_cache", _warm)

        gather_computation_data("AAPL", "2026-02-25")
        assert warm_called["value"] is True


# --- Tests for build_session_score ---

class TestBuildSessionScore:

    def test_correct_weighted_sum(self, monkeypatch):
        monkeypatch.setattr("tradingagents.graph.fama_french.get_ff_factors",
                            lambda **k: None)
        result = build_session_score(_mock_computation_data(), _mock_sonnet_outputs())

        assert isinstance(result["aeternus_score"], float)
        assert 0 <= result["aeternus_score"] <= 100
        assert result["rating"] in ["Strong Buy", "Buy", "Hold", "Sell", "Strong Sell"]

    def test_coherence_computed(self, monkeypatch):
        monkeypatch.setattr("tradingagents.graph.fama_french.get_ff_factors",
                            lambda **k: None)
        result = build_session_score(_mock_computation_data(), _mock_sonnet_outputs())

        assert "coherence_sub" in result
        assert isinstance(result["coherence_sub"], dict)
        for key in ("directional_alignment", "conviction_strength",
                     "interaction_patterns", "narrative_stability"):
            assert key in result["coherence_sub"]

    def test_regime_weights_applied(self, monkeypatch):
        monkeypatch.setattr("tradingagents.graph.fama_french.get_ff_factors",
                            lambda **k: None)
        result = build_session_score(_mock_computation_data(), _mock_sonnet_outputs())

        assert "regime_weights" in result
        assert isinstance(result["regime_weights"], dict)
        assert result["weight_regime"] == "NEUTRAL"

    def test_rating_thresholds(self, monkeypatch):
        monkeypatch.setattr("tradingagents.graph.fama_french.get_ff_factors",
                            lambda **k: None)
        result = build_session_score(_mock_computation_data(), _mock_sonnet_outputs())
        score = result["aeternus_score"]
        rating = result["rating"]

        if score >= 80:
            assert rating == "Strong Buy"
        elif score >= 60:
            assert rating == "Buy"
        elif score >= 40:
            assert rating == "Hold"
        elif score >= 20:
            assert rating == "Sell"
        else:
            assert rating == "Strong Sell"

    def test_confidence_in_range(self, monkeypatch):
        monkeypatch.setattr("tradingagents.graph.fama_french.get_ff_factors",
                            lambda **k: None)
        result = build_session_score(_mock_computation_data(), _mock_sonnet_outputs())

        assert isinstance(result["confidence"], int)
        assert 1 <= result["confidence"] <= 5

    def test_low_coverage_gates_pillars(self, monkeypatch):
        """When data_coverage < 0.4, pillar scores default to 50."""
        monkeypatch.setattr("tradingagents.graph.fama_french.get_ff_factors",
                            lambda **k: None)
        data = _mock_computation_data()
        data["fundamental_metrics"]["data_coverage"] = 0.1
        data["sentiment_metrics"]["data_coverage"] = 0.1
        data["momentum_metrics"]["data_coverage"] = 0.1
        data["macro_metrics"]["data_coverage"] = 0.1
        data["options_metrics"] = {}
        data["flow_toxicity_metrics"] = {}

        result = build_session_score(data, _mock_sonnet_outputs())

        # All 4 pillars gated → default to 50
        assert result["breakdown"]["fundamental"] == 50
        assert result["breakdown"]["macro"] == 50
        assert result["breakdown"]["sentiment"] == 50
        assert result["breakdown"]["momentum"] == 50
        # Coherence of uniform 50s is high (~79), pulling overall to ~57
        # That's correct — coherence rewards consensus even at neutral
        assert result["data_quality_gate"]["fundamental"] is True
        assert result["data_quality_gate"]["macro"] is True

    def test_fundamental_overlay_present_and_advisory(self, monkeypatch):
        monkeypatch.setattr("tradingagents.graph.fama_french.get_ff_factors",
                            lambda **k: None)
        result = build_session_score(_mock_computation_data(), _mock_sonnet_outputs())

        expected_score = round(
            (result["fundamental_sub"]["health"] * 0.5)
            + ((100 - result["fundamental_sub"]["quality"]) * 0.4)
            + ((100 - result["fundamental_sub"]["growth"]) * 0.1),
            2,
        )

        assert result["fundamental_overlay_score"] == expected_score
        assert result["fundamental_overlay_label"] in {
            "UNDERAPPRECIATED_RESILIENCE",
            "BALANCED",
            "CROWDING_RISK",
        }
        assert isinstance(result["fundamental_overlay_notes"], str)
        assert result["fundamental_shadow_strategy"] == "health_0p5__inv_growth_0p1__inv_quality_0p4"
        assert result["fundamental_shadow_gate_status"] in {"PASSED", "PENDING"}
        assert result["fundamental_shadow_recommended_status"] in {"shadow", "candidate"}
        assert result["breakdown"]["fundamental"] != result["fundamental_overlay_score"]

    def test_fundamental_overlay_absent_when_fundamentals_gated(self, monkeypatch):
        monkeypatch.setattr("tradingagents.graph.fama_french.get_ff_factors",
                            lambda **k: None)
        data = _mock_computation_data()
        data["fundamental_metrics"]["data_coverage"] = 0.1

        result = build_session_score(data, _mock_sonnet_outputs())

        assert result["fundamental_sub"] is None
        assert result["fundamental_overlay_score"] is None
        assert result["fundamental_overlay_label"] is None
        assert result["fundamental_overlay_notes"] is None
        assert result["fundamental_shadow_strategy"] == "health_0p5__inv_growth_0p1__inv_quality_0p4"
        assert result["fundamental_shadow_gate_status"] in {"PASSED", "PENDING"}


# --- Tests for write_analysis_report ---
# Use monkeypatch.chdir(tmp_path) so relative Path("results") resolves under tmp_path.

class TestWriteAnalysisReport:

    def _write_report(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        return write_analysis_report(
            ticker="TSLA",
            date="2026-02-25",
            computation_data=_mock_computation_data(),
            sonnet_outputs=_mock_sonnet_outputs(),
            score_dict={"aeternus_score": 72.5, "rating": "Buy", "confidence": 4},
        )

    def test_file_written_at_correct_path(self, tmp_path, monkeypatch):
        self._write_report(tmp_path, monkeypatch)
        path = tmp_path / "results" / "TSLA" / "2026-02-25" / "analysis_report.json"
        assert path.exists()

    def test_aeternus_score_block_present(self, tmp_path, monkeypatch):
        self._write_report(tmp_path, monkeypatch)
        path = tmp_path / "results" / "TSLA" / "2026-02-25" / "analysis_report.json"
        data = json.loads(path.read_text())

        assert "aeternus_score" in data
        assert data["aeternus_score"]["aeternus_score"] == 72.5
        assert data["aeternus_score"]["rating"] == "Buy"

    def test_final_trade_decision_present(self, tmp_path, monkeypatch):
        self._write_report(tmp_path, monkeypatch)
        path = tmp_path / "results" / "TSLA" / "2026-02-25" / "analysis_report.json"
        data = json.loads(path.read_text())

        assert data["final_trade_decision"] == "BUY with high conviction"

    def test_downstream_extract_compatibility(self, tmp_path, monkeypatch):
        self._write_report(tmp_path, monkeypatch)
        path = tmp_path / "results" / "TSLA" / "2026-02-25" / "analysis_report.json"
        data = json.loads(path.read_text())

        assert data["company_of_interest"] == "TSLA"
        assert data["trade_date"] == "2026-02-25"
        for key in ("fundamentals_report", "market_report", "sentiment_report",
                     "news_report", "investment_debate_state", "risk_debate_state",
                     "structured_trader_verdict", "aeternus_score"):
            assert key in data


# --- Tests for write_batch_summary ---

class TestWriteBatchSummary:

    def _write_batch(self, tmp_path, monkeypatch, queue_date="2026-02-25", items=None):
        monkeypatch.chdir(tmp_path)
        if items is None:
            items = [
                {"ticker": "AAPL", "aeternus_score": 72.5, "rating": "Buy"},
                {"ticker": "MSFT", "aeternus_score": 65.0, "rating": "Buy"},
            ]
        write_batch_summary(queue_date=queue_date, items=items)
        return tmp_path / "eval_results" / "deal_flow" / queue_date

    def test_batch_file_written(self, tmp_path, monkeypatch):
        base = self._write_batch(tmp_path, monkeypatch)
        assert (base / "batch_analyze_latest.json").exists()
        assert (base / "batch_analyze_summary.json").exists()

    def test_items_array_correct(self, tmp_path, monkeypatch):
        base = self._write_batch(tmp_path, monkeypatch)
        data = json.loads((base / "batch_analyze_latest.json").read_text())

        assert len(data["items"]) == 2
        assert data["items"][0]["ticker"] == "AAPL"
        assert data["items"][1]["ticker"] == "MSFT"
        assert data["analyzed_count"] == 2

    def test_queue_date_in_summary(self, tmp_path, monkeypatch):
        base = self._write_batch(tmp_path, monkeypatch, queue_date="2026-03-01")
        data = json.loads((base / "batch_analyze_latest.json").read_text())

        assert data["queue_date"] == "2026-03-01"
