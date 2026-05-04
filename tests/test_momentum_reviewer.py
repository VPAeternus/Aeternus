"""Tests for tradingagents.agents.analysts.momentum_reviewer"""

import json
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

from tradingagents.agents.analysts.momentum_reviewer import create_momentum_reviewer


# --- Factory Helpers ---

def _fake_metrics():
    """Create a realistic momentum metrics dict for testing."""
    return {
        "regime": "ABOVE_BOTH",
        "signal_state": "long",
        "accel_percentile": 0.72,
        "accel_value": 0.005,
        "invested_pct_2y": 91.5,
        "days_of_history": 6800,
        "subscores": {
            "trend_strength": 88,
            "momentum_health": 70,
            "regime_quality": 78,
            "volume_confirmation": 55,
        },
        "composite_score": 78,
        "direction": "BULLISH",
        "data_coverage": 1.0,
    }


def _fake_state():
    """Create a realistic state dict for testing."""
    return {
        "company_of_interest": "AAPL",
        "trade_date": "2026-02-23",
        "market_report": "Price above SMA200. RSI at 62. MACD positive.",
        "fundamentals_report": "Revenue growing 12% YoY. Strong FCF.",
        "dealflow_context": {},
    }


# --- Mock LLM ---

class _MockLLM:
    """Mock LLM that returns a fixed review text."""
    def invoke(self, messages):
        return type("Response", (), {"content": "Mock momentum review critique."})()


# --- Tests for create_momentum_reviewer ---

class TestCreateMomentumReviewer:
    def test_reviewer_returns_two_keys(self, monkeypatch):
        """Node returns exactly market_report and momentum_metrics."""
        # Mock the momentum engine to return fake metrics
        def mock_build_snapshot(ticker, trade_date):
            return _fake_metrics()

        monkeypatch.setattr(
            "tradingagents.agents.utils.momentum_engine.build_momentum_snapshot",
            mock_build_snapshot,
        )

        mock_llm = _MockLLM()
        node = create_momentum_reviewer(mock_llm)

        state = _fake_state()
        result = node(state)

        # Must have exactly these two keys
        assert set(result.keys()) == {"market_report", "momentum_metrics"}

    def test_market_report_is_enhanced(self, monkeypatch):
        """Returned market_report contains both reviewer critique and original report."""
        def mock_build_snapshot(ticker, trade_date):
            return _fake_metrics()

        monkeypatch.setattr(
            "tradingagents.agents.utils.momentum_engine.build_momentum_snapshot",
            mock_build_snapshot,
        )

        mock_llm = _MockLLM()
        node = create_momentum_reviewer(mock_llm)

        state = _fake_state()
        result = node(state)

        market_report = result["market_report"]
        
        # Must contain reviewer critique header
        assert "## Senior Momentum Reviewer Critique" in market_report
        
        # Must contain original report
        assert "## Original Market Report" in market_report
        assert "Price above SMA200" in market_report
        
        # Critique must appear before original report
        assert market_report.index("Senior Momentum Reviewer Critique") < market_report.index("Original Market Report")

    def test_momentum_metrics_populated(self, monkeypatch):
        """momentum_metrics contains the computed metrics dict."""
        metrics = _fake_metrics()
        
        def mock_build_snapshot(ticker, trade_date):
            return metrics

        monkeypatch.setattr(
            "tradingagents.agents.utils.momentum_engine.build_momentum_snapshot",
            mock_build_snapshot,
        )

        mock_llm = _MockLLM()
        node = create_momentum_reviewer(mock_llm)

        state = _fake_state()
        result = node(state)

        returned_metrics = result["momentum_metrics"]
        
        # All original metrics should be present
        assert returned_metrics["regime"] == "ABOVE_BOTH"
        assert returned_metrics["signal_state"] == "long"
        assert returned_metrics["accel_percentile"] == 0.72
        assert returned_metrics["composite_score"] == 78
        assert returned_metrics["direction"] == "BULLISH"
        assert returned_metrics["subscores"]["trend_strength"] == 88

    def test_graceful_degradation_on_engine_failure(self, monkeypatch):
        """When build_momentum_snapshot raises, node still returns valid dict with empty metrics."""
        def mock_build_snapshot_fail(ticker, trade_date):
            raise Exception("Momentum engine unavailable")

        monkeypatch.setattr(
            "tradingagents.agents.utils.momentum_engine.build_momentum_snapshot",
            mock_build_snapshot_fail,
        )

        mock_llm = _MockLLM()
        node = create_momentum_reviewer(mock_llm)

        state = _fake_state()
        result = node(state)

        # Even with engine failure, must return valid structure
        assert "market_report" in result
        assert "momentum_metrics" in result
        assert isinstance(result["momentum_metrics"], dict)
        # Metrics dict should be empty when engine fails
        assert result["momentum_metrics"] == {}
        
        # Report should still have the critique
        assert "## Senior Momentum Reviewer Critique" in result["market_report"]

    def test_dealflow_fast_path(self, monkeypatch):
        """When dealflow_context has price_momentum subscore, uses _metrics_from_dealflow
        with real engine sub-scores for the 4 dimensions."""
        # Mock engine to return independent sub-scores
        call_log = []
        def mock_build_snapshot(ticker, trade_date):
            call_log.append("engine_called")
            return {
                "subscores": {
                    "trend_strength": 80,
                    "momentum_health": 65,
                    "regime_quality": 70,
                    "volume_confirmation": 55,
                },
                "composite_score": 68,
                "direction": "BULLISH",
                "data_coverage": 1.0,
            }

        monkeypatch.setattr(
            "tradingagents.agents.utils.momentum_engine.build_momentum_snapshot",
            mock_build_snapshot,
        )

        mock_llm = _MockLLM()
        node = create_momentum_reviewer(mock_llm)

        state = _fake_state()
        state["dealflow_context"] = {
            "subscores": {
                "price_momentum": 75,
                "other_score": 50,
            },
            "deal_flow_score": 78,
            "why_now": "Strong price acceleration",
        }

        result = node(state)

        # Engine IS called for independent sub-scores
        assert len(call_log) == 1

        # Metrics should be derived from dealflow composite + engine sub-scores
        metrics = result["momentum_metrics"]
        assert metrics.get("source") == "dealflow"
        assert metrics["composite_score"] == 75  # dealflow composite preserved
        assert metrics["direction"] == "BULLISH"  # 75 >= 60

        # subscores come from engine, NOT the composite
        assert metrics["subscores"]["trend_strength"] == 80
        assert metrics["subscores"]["momentum_health"] == 65
        assert metrics["subscores"]["regime_quality"] == 70
        assert metrics["subscores"]["volume_confirmation"] == 55

    def test_dealflow_engine_fallback(self, monkeypatch):
        """When engine fails, dealflow path falls back to composite for all sub-scores."""
        def mock_build_snapshot(ticker, trade_date):
            raise RuntimeError("engine unavailable")

        monkeypatch.setattr(
            "tradingagents.agents.utils.momentum_engine.build_momentum_snapshot",
            mock_build_snapshot,
        )

        mock_llm = _MockLLM()
        node = create_momentum_reviewer(mock_llm)

        state = _fake_state()
        state["dealflow_context"] = {
            "subscores": {"price_momentum": 75},
            "deal_flow_score": 78,
        }

        result = node(state)
        metrics = result["momentum_metrics"]
        assert metrics.get("source") == "dealflow"
        assert metrics["composite_score"] == 75
        # Fallback: all sub-scores equal composite
        for key in ("trend_strength", "momentum_health", "regime_quality", "volume_confirmation"):
            assert metrics["subscores"][key] == 75

    def test_no_market_report(self, monkeypatch):
        """Test when state has no market_report."""
        def mock_build_snapshot(ticker, trade_date):
            return _fake_metrics()

        monkeypatch.setattr(
            "tradingagents.agents.utils.momentum_engine.build_momentum_snapshot",
            mock_build_snapshot,
        )

        mock_llm = _MockLLM()
        node = create_momentum_reviewer(mock_llm)

        state = _fake_state()
        state["market_report"] = ""

        result = node(state)

        # Should still have valid structure
        assert "market_report" in result
        assert "momentum_metrics" in result
        
        # Report should just be the critique without "Original Market Report" section
        market_report = result["market_report"]
        assert "## Senior Momentum Reviewer Critique" in market_report
        assert "## Original Market Report" not in market_report

    def test_metrics_included_in_llm_prompt(self, monkeypatch):
        """Verify computed metrics are included in the LLM prompt."""
        call_log = []
        
        class CaptureLLM:
            def invoke(self, messages):
                call_log.append(messages)
                return type("Response", (), {"content": "Mock review."})()

        metrics = _fake_metrics()
        def mock_build_snapshot(ticker, trade_date):
            return metrics

        monkeypatch.setattr(
            "tradingagents.agents.utils.momentum_engine.build_momentum_snapshot",
            mock_build_snapshot,
        )

        node = create_momentum_reviewer(CaptureLLM())
        state = _fake_state()
        result = node(state)

        assert len(call_log) > 0
        messages = call_log[0]
        
        # Find the human message
        human_message = [m for m in messages if m[0] == "human"]
        assert len(human_message) > 0
        
        content = human_message[0][1]
        # Check that metrics are in JSON format in the prompt
        assert "Computed Momentum Metrics" in content
        assert "0.72" in content  # accel_percentile
        assert "trend_strength" in content

    def test_system_prompt_is_set(self, monkeypatch):
        """Verify system prompt is included in messages."""
        call_log = []
        
        class CaptureLLM:
            def invoke(self, messages):
                call_log.append(messages)
                return type("Response", (), {"content": "Mock review."})()

        def mock_build_snapshot(ticker, trade_date):
            return _fake_metrics()

        monkeypatch.setattr(
            "tradingagents.agents.utils.momentum_engine.build_momentum_snapshot",
            mock_build_snapshot,
        )

        node = create_momentum_reviewer(CaptureLLM())
        state = _fake_state()
        result = node(state)

        messages = call_log[0]
        
        # First message should be system prompt
        assert messages[0][0] == "system"
        system_content = messages[0][1]
        
        # Check key phrases from the review prompt
        assert "Regime Classification" in system_content
        assert "Acceleration Percentile" in system_content
        assert "Signal State" in system_content
        assert "Trend Quality" in system_content or "invested_pct_2y" in system_content

    def test_fundamentals_context_included(self, monkeypatch):
        """Test that fundamentals context is included in the LLM prompt."""
        call_log = []
        
        class CaptureLLM:
            def invoke(self, messages):
                call_log.append(messages)
                return type("Response", (), {"content": "Mock review."})()

        def mock_build_snapshot(ticker, trade_date):
            return _fake_metrics()

        monkeypatch.setattr(
            "tradingagents.agents.utils.momentum_engine.build_momentum_snapshot",
            mock_build_snapshot,
        )

        node = create_momentum_reviewer(CaptureLLM())
        state = _fake_state()
        state["fundamentals_report"] = "Strong revenue growth with improving margins."
        
        result = node(state)

        messages = call_log[0]
        human_message = [m for m in messages if m[0] == "human"]
        assert len(human_message) > 0
        
        content = human_message[0][1]
        assert "Fundamentals Context" in content
        assert "revenue growth" in content

    def test_dealflow_context_in_prompt(self, monkeypatch):
        """Verify Deal Flow Signals appear in prompt when dealflow_context provided."""
        call_log = []
        
        class CaptureLLM:
            def invoke(self, messages):
                call_log.append(messages)
                return type("Response", (), {"content": "Mock review."})()

        mock_llm = CaptureLLM()
        node = create_momentum_reviewer(mock_llm)

        state = _fake_state()
        state["dealflow_context"] = {
            "subscores": {
                "price_momentum": 75,
                "earnings_estimate": 60,
            },
            "deal_flow_score": 78,
            "why_now": "Breakout from consolidation pattern",
        }

        result = node(state)

        messages = call_log[0]
        human_message = [m for m in messages if m[0] == "human"][0][1]
        
        assert "Deal Flow Signals" in human_message
        assert "75" in human_message  # price_momentum
        assert "Breakout from consolidation" in human_message

    def test_market_report_truncation(self, monkeypatch):
        """Test that very long market reports are truncated in the prompt."""
        call_log = []
        
        class CaptureLLM:
            def invoke(self, messages):
                call_log.append(messages)
                return type("Response", (), {"content": "Mock review."})()

        def mock_build_snapshot(ticker, trade_date):
            return _fake_metrics()

        monkeypatch.setattr(
            "tradingagents.agents.utils.momentum_engine.build_momentum_snapshot",
            mock_build_snapshot,
        )

        node = create_momentum_reviewer(CaptureLLM())
        state = _fake_state()
        state["market_report"] = "X" * 1500  # Long report

        result = node(state)

        messages = call_log[0]
        human_message = [m for m in messages if m[0] == "human"][0][1]
        
        # Report should be truncated in prompt (1000 char limit)
        # But full report should be in result
        assert len(result["market_report"]) > 1500
        assert "truncated" in human_message  # Truncation marker in prompt

    def test_no_metrics_fallback(self, monkeypatch):
        """Test graceful handling when no metrics are available."""
        def mock_build_snapshot_empty(ticker, trade_date):
            return {}

        monkeypatch.setattr(
            "tradingagents.agents.utils.momentum_engine.build_momentum_snapshot",
            mock_build_snapshot_empty,
        )

        call_log = []
        class CaptureLLM:
            def invoke(self, messages):
                call_log.append(messages)
                return type("Response", (), {"content": "Mock review."})()

        node = create_momentum_reviewer(CaptureLLM())
        state = _fake_state()
        result = node(state)

        messages = call_log[0]
        human_message = [m for m in messages if m[0] == "human"][0][1]
        
        # Should indicate metrics unavailable
        assert "unavailable" in human_message.lower() or "Computed Momentum Metrics" in human_message

    def test_response_without_content_attribute(self, monkeypatch):
        """Test handling of LLM responses without .content attribute."""
        def mock_build_snapshot(ticker, trade_date):
            return _fake_metrics()

        monkeypatch.setattr(
            "tradingagents.agents.utils.momentum_engine.build_momentum_snapshot",
            mock_build_snapshot,
        )

        class BadLLM:
            def invoke(self, messages):
                # Return object without .content attribute
                return type("Response", (), {})()

        node = create_momentum_reviewer(BadLLM())
        state = _fake_state()
        result = node(state)

        # Should gracefully handle missing .content
        assert "market_report" in result
        assert isinstance(result["market_report"], str)

    def test_company_and_date_in_prompt(self, monkeypatch):
        """Verify company and date info is included in the prompt."""
        call_log = []
        
        class CaptureLLM:
            def invoke(self, messages):
                call_log.append(messages)
                return type("Response", (), {"content": "Mock review."})()

        def mock_build_snapshot(ticker, trade_date):
            return _fake_metrics()

        monkeypatch.setattr(
            "tradingagents.agents.utils.momentum_engine.build_momentum_snapshot",
            mock_build_snapshot,
        )

        node = create_momentum_reviewer(CaptureLLM())
        state = {
            "company_of_interest": "NVDA",
            "trade_date": "2026-03-15",
            "market_report": "Some report",
            "fundamentals_report": "",
            "dealflow_context": {},
        }
        
        result = node(state)

        messages = call_log[0]
        human_message = [m for m in messages if m[0] == "human"][0][1]
        
        assert "NVDA" in human_message
        assert "2026-03-15" in human_message

    def test_dealflow_neutral_direction(self, monkeypatch):
        """Test _metrics_from_dealflow direction classification."""
        mock_llm = _MockLLM()
        node = create_momentum_reviewer(mock_llm)

        state = _fake_state()
        state["dealflow_context"] = {
            "subscores": {
                "price_momentum": 50,  # Between 40 and 60 = NEUTRAL
            },
        }

        result = node(state)
        
        assert result["momentum_metrics"]["direction"] == "NEUTRAL"

    def test_dealflow_bearish_direction(self, monkeypatch):
        """Test _metrics_from_dealflow bearish classification."""
        mock_llm = _MockLLM()
        node = create_momentum_reviewer(mock_llm)

        state = _fake_state()
        state["dealflow_context"] = {
            "subscores": {
                "price_momentum": 35,  # Below 40 = BEARISH
            },
        }

        result = node(state)
        
        assert result["momentum_metrics"]["direction"] == "BEARISH"

    def test_empty_dealflow_context_uses_vendor(self, monkeypatch):
        """Test that empty dealflow_context falls back to vendor routes."""
        metrics = _fake_metrics()
        
        def mock_build_snapshot(ticker, trade_date):
            return metrics

        monkeypatch.setattr(
            "tradingagents.agents.utils.momentum_engine.build_momentum_snapshot",
            mock_build_snapshot,
        )

        mock_llm = _MockLLM()
        node = create_momentum_reviewer(mock_llm)

        state = _fake_state()
        state["dealflow_context"] = {}  # Empty, no price_momentum

        result = node(state)
        
        # Should use vendor metrics
        assert result["momentum_metrics"]["regime"] == "ABOVE_BOTH"
        assert result["momentum_metrics"].get("source") != "dealflow"

    def test_dealflow_without_price_momentum_uses_vendor(self, monkeypatch):
        """Test that dealflow_context without price_momentum key uses vendor."""
        metrics = _fake_metrics()
        
        def mock_build_snapshot(ticker, trade_date):
            return metrics

        monkeypatch.setattr(
            "tradingagents.agents.utils.momentum_engine.build_momentum_snapshot",
            mock_build_snapshot,
        )

        mock_llm = _MockLLM()
        node = create_momentum_reviewer(mock_llm)

        state = _fake_state()
        state["dealflow_context"] = {
            "subscores": {
                "other_score": 50,
                # No price_momentum key
            }
        }

        result = node(state)
        
        # Should use vendor metrics
        assert result["momentum_metrics"]["regime"] == "ABOVE_BOTH"
        assert result["momentum_metrics"].get("source") != "dealflow"
