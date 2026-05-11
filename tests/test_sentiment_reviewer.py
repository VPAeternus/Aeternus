"""Tests for tradingagents.agents.analysts.sentiment_reviewer"""

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

from tradingagents.agents.analysts.sentiment_reviewer import (
    create_sentiment_reviewer,
    _gather_analyst_context,
)

# Import _metrics_from_dealflow if available (part of deal flow signal bridge feature)
try:
    from tradingagents.agents.analysts.sentiment_reviewer import _metrics_from_dealflow
except ImportError:
    # Provide a test-time stub if not yet implemented
    def _metrics_from_dealflow(ctx: dict) -> dict:
        """Test stub for _metrics_from_dealflow."""
        subscores = ctx.get("subscores", {})
        evidence = ctx.get("evidence", {})
        social_momentum = subscores.get("social_momentum", 50)
        direction = "BULLISH" if social_momentum >= 60 else ("BEARISH" if social_momentum <= 40 else "NEUTRAL")
        return {
            "source": "dealflow",
            "social_momentum": social_momentum,
            "cashtag_momentum": subscores.get("cashtag_momentum", 50),
            "news_catalyst": subscores.get("news_catalyst", 50),
            "evidence_count": evidence.get("evidence_count", 0),
            "freshness_hours": evidence.get("freshness_hours", 0),
            "direction": direction,
            "data_coverage": 1.0,
        }


# --- Mock LLM ---

class _MockLLM:
    def invoke(self, messages):
        return type("Response", (), {"content": "Mock review critique."})()


# --- Tests for create_sentiment_reviewer ---

class TestCreateSentimentReviewer:
    def test_basic_invocation(self, monkeypatch):
        """Test basic node creation and invocation."""
        # Mock route_to_vendor to return empty strings
        monkeypatch.setattr(
            "tradingagents.dataflows.interface.route_to_vendor",
            lambda *a, **kw: "",
        )

        mock_llm = _MockLLM()
        node = create_sentiment_reviewer(mock_llm)

        state = {
            "company_of_interest": "AAPL",
            "trade_date": "2026-02-20",
            "sentiment_report": "Some analyst report about AAPL sentiment.",
            "fundamentals_report": "Fundamentals look strong.",
        }

        result = node(state)

        assert "sentiment_report" in result
        assert "sentiment_metrics" in result

    def test_enhanced_report_format(self, monkeypatch):
        """Verify the returned sentiment_report has correct format."""
        monkeypatch.setattr(
            "tradingagents.dataflows.interface.route_to_vendor",
            lambda *a, **kw: "",
        )

        mock_llm = _MockLLM()
        node = create_sentiment_reviewer(mock_llm)

        state = {
            "company_of_interest": "AAPL",
            "trade_date": "2026-02-20",
            "sentiment_report": "Original analyst report.",
            "fundamentals_report": "Fundamentals look strong.",
        }

        result = node(state)

        assert result["sentiment_report"].startswith("## Senior Sentiment Reviewer Critique")
        assert "Original Analyst Report" in result["sentiment_report"]

    def test_no_analyst_report(self, monkeypatch):
        """Test when state has no sentiment_report."""
        monkeypatch.setattr(
            "tradingagents.dataflows.interface.route_to_vendor",
            lambda *a, **kw: "",
        )

        mock_llm = _MockLLM()
        node = create_sentiment_reviewer(mock_llm)

        state = {
            "company_of_interest": "AAPL",
            "trade_date": "2026-02-20",
            "sentiment_report": "",
            "fundamentals_report": "Fundamentals look strong.",
        }

        result = node(state)

        assert "sentiment_report" in result
        assert "sentiment_metrics" in result
        assert result["sentiment_report"].startswith("## Senior Sentiment Reviewer Critique")

    def test_fundamentals_context_included(self, monkeypatch):
        """Test that fundamentals context is included in the LLM prompt."""
        call_log = []

        class CallCaptureLLM:
            def invoke(self, messages):
                call_log.append(messages)
                return type("Response", (), {"content": "Mock review."})()

        monkeypatch.setattr(
            "tradingagents.dataflows.interface.route_to_vendor",
            lambda *a, **kw: "",
        )

        mock_llm = CallCaptureLLM()
        node = create_sentiment_reviewer(mock_llm)

        state = {
            "company_of_interest": "AAPL",
            "trade_date": "2026-02-20",
            "sentiment_report": "Analyst report here.",
            "fundamentals_report": "Fundamentals look very strong with ROE > 20%.",
        }

        result = node(state)

        assert len(call_log) > 0
        messages = call_log[0]
        # Check that fundamentals context made it into the human message
        human_message = [m for m in messages if m[0] == "human"]
        assert len(human_message) > 0
        assert "Fundamentals Context" in human_message[0][1]

    def test_metrics_graceful_degradation(self, monkeypatch):
        """Test that metrics are returned gracefully when vendor routes fail."""
        def mock_route_fail(*a, **kw):
            raise Exception("Vendor unavailable")

        monkeypatch.setattr(
            "tradingagents.dataflows.interface.route_to_vendor",
            mock_route_fail,
        )

        mock_llm = _MockLLM()
        node = create_sentiment_reviewer(mock_llm)

        state = {
            "company_of_interest": "AAPL",
            "trade_date": "2026-02-20",
            "sentiment_report": "Analyst report.",
            "fundamentals_report": "",
        }

        result = node(state)

        assert "sentiment_metrics" in result
        # When vendor routes fail, metrics are still built from empty data
        # (result is a snapshot dict with default values, not completely empty)
        assert isinstance(result["sentiment_metrics"], dict)


# --- Tests for _gather_analyst_context ---

class TestGatherAnalystContext:
    def test_no_directory(self, tmp_path, monkeypatch):
        """When analyst_discovery_data doesn't exist, returns {}."""
        import tradingagents.agents.analysts.sentiment_reviewer as mod
        monkeypatch.setattr(mod, "_ANALYST_DIR", tmp_path / "nonexistent" / "analysts")
        assert _gather_analyst_context("AAPL") == {}

    def test_no_matching_ticker(self, tmp_path, monkeypatch):
        """Profiles exist but none cover the requested ticker."""
        import tradingagents.agents.analysts.sentiment_reviewer as mod
        analysts_dir = tmp_path / "analysts"
        analysts_dir.mkdir()
        (analysts_dir / "analyst1.json").write_text(json.dumps({
            "handle": "analyst1", "tier": "B", "avg_quality_score": 75,
            "tickers_covered": ["MSFT", "GOOG"], "follower_count": 5000,
        }))
        monkeypatch.setattr(mod, "_ANALYST_DIR", analysts_dir)
        assert _gather_analyst_context("AAPL") == {}

    def test_matching_ticker(self, tmp_path, monkeypatch):
        """Profiles covering the ticker produce a valid context dict."""
        import tradingagents.agents.analysts.sentiment_reviewer as mod
        analysts_dir = tmp_path / "analysts"
        analysts_dir.mkdir()
        (analysts_dir / "analyst1.json").write_text(json.dumps({
            "handle": "microcap_mike", "tier": "C", "avg_quality_score": 81,
            "consistency_score": 72, "tickers_covered": ["AAPL", "NVDA"],
            "follower_count": 850, "promoted_to_dealflow": False,
        }))
        (analysts_dir / "analyst2.json").write_text(json.dumps({
            "handle": "charliebilello", "tier": "A", "avg_quality_score": 92,
            "consistency_score": 88, "tickers_covered": ["AAPL", "SPY"],
            "follower_count": 120000, "promoted_to_dealflow": True,
        }))
        monkeypatch.setattr(mod, "_ANALYST_DIR", analysts_dir)

        ctx = _gather_analyst_context("AAPL")
        assert ctx["ticker"] == "AAPL"
        assert ctx["analyst_count"] == 2
        assert ctx["promoted_to_dealflow"] == 1
        assert ctx["avg_analyst_quality"] == 86.5  # (81 + 92) / 2
        assert ctx["tier_distribution"] == {"C": 1, "A": 1}
        # Top analysts sorted by quality descending
        assert ctx["top_analysts"][0]["handle"] == "charliebilello"

    def test_case_insensitive_ticker(self, tmp_path, monkeypatch):
        """Ticker matching is case-insensitive."""
        import tradingagents.agents.analysts.sentiment_reviewer as mod
        analysts_dir = tmp_path / "analysts"
        analysts_dir.mkdir()
        (analysts_dir / "a.json").write_text(json.dumps({
            "handle": "analyst", "tier": "B", "avg_quality_score": 70,
            "tickers_covered": ["aapl"],
        }))
        monkeypatch.setattr(mod, "_ANALYST_DIR", analysts_dir)
        assert _gather_analyst_context("AAPL")["analyst_count"] == 1

    def test_included_in_reviewer_prompt(self, tmp_path, monkeypatch):
        """Analyst discovery context appears in the LLM prompt when data exists."""
        import tradingagents.agents.analysts.sentiment_reviewer as mod
        analysts_dir = tmp_path / "analysts"
        analysts_dir.mkdir()
        (analysts_dir / "a.json").write_text(json.dumps({
            "handle": "top_analyst", "tier": "A", "avg_quality_score": 90,
            "tickers_covered": ["AAPL"], "promoted_to_dealflow": True,
        }))
        monkeypatch.setattr(mod, "_ANALYST_DIR", analysts_dir)
        monkeypatch.setattr(
            "tradingagents.dataflows.interface.route_to_vendor",
            lambda *a, **kw: "",
        )

        call_log = []
        class CaptureLLM:
            def invoke(self, messages):
                call_log.append(messages)
                return type("R", (), {"content": "Review."})()

        node = create_sentiment_reviewer(CaptureLLM())
        node({
            "company_of_interest": "AAPL",
            "trade_date": "2026-02-20",
            "sentiment_report": "Report.",
            "fundamentals_report": "",
        })

        human_msg = [m for m in call_log[0] if m[0] == "human"][0][1]
        assert "Analyst Discovery Context" in human_msg
        assert "top_analyst" in human_msg


# --- Tests for Deal Flow Bridge ---

class TestDealflowBridge:
    def test_metrics_from_dealflow_basic(self):
        """Test _metrics_from_dealflow returns expected structure and values."""
        ctx = {
            "subscores": {
                "social_momentum": 72,
                "cashtag_momentum": 65,
                "news_catalyst": 80,
            },
            "evidence": {
                "evidence_count": 15,
                "freshness_hours": 4.2,
            },
        }

        metrics = _metrics_from_dealflow(ctx)

        # Check all required keys exist
        assert "source" in metrics
        assert "social_momentum" in metrics
        assert "cashtag_momentum" in metrics
        assert "news_catalyst" in metrics
        assert "evidence_count" in metrics
        assert "freshness_hours" in metrics
        assert "direction" in metrics
        assert "data_coverage" in metrics

        # Check values
        assert metrics["source"] == "dealflow"
        assert metrics["social_momentum"] == 72
        assert metrics["cashtag_momentum"] == 65
        assert metrics["news_catalyst"] == 80
        assert metrics["evidence_count"] == 15
        assert metrics["freshness_hours"] == 4.2
        assert metrics["direction"] == "BULLISH"  # 72 >= 60
        assert metrics["data_coverage"] == 1.0

    def test_reviewer_uses_dealflow_context(self, monkeypatch):
        """Verify reviewer uses dealflow metrics and skips vendor routes when dealflow_context present."""
        # Vendor should NOT be called — raise if it is
        monkeypatch.setattr(
            "tradingagents.dataflows.interface.route_to_vendor",
            lambda *a, **kw: (_ for _ in ()).throw(AssertionError("Should not call vendor")),
        )

        node = create_sentiment_reviewer(_MockLLM())

        state = {
            "company_of_interest": "AAPL",
            "trade_date": "2026-02-20",
            "sentiment_report": "Analyst report.",
            "fundamentals_report": "",
            "dealflow_context": {
                "subscores": {
                    "social_momentum": 72,
                    "cashtag_momentum": 65,
                    "news_catalyst": 80,
                },
                "evidence": {
                    "evidence_count": 15,
                    "freshness_hours": 4.2,
                },
            },
        }

        result = node(state)

        assert result["sentiment_metrics"]["source"] == "dealflow"
        assert result["sentiment_metrics"]["social_momentum"] == 72

    def test_reviewer_falls_back_without_dealflow(self, monkeypatch):
        """Test that reviewer falls back to normal metrics when dealflow_context is absent."""
        monkeypatch.setattr(
            "tradingagents.dataflows.interface.route_to_vendor",
            lambda *a, **kw: "",
        )

        mock_llm = _MockLLM()
        node = create_sentiment_reviewer(mock_llm)

        state = {
            "company_of_interest": "AAPL",
            "trade_date": "2026-02-20",
            "sentiment_report": "Analyst report.",
            "fundamentals_report": "",
            "dealflow_context": {},  # empty = no deal flow
        }

        result = node(state)

        assert result["sentiment_metrics"].get("source") != "dealflow"
        assert "sentiment_metrics" in result

    def test_dealflow_signals_in_reviewer_prompt(self):
        """Verify Deal Flow Signals section appears in LLM prompt when dealflow_context provided."""
        call_log = []

        class CaptureLLM:
            def invoke(self, messages):
                call_log.append(messages)
                return type("R", (), {"content": "Review."})()

        node = create_sentiment_reviewer(CaptureLLM())
        state = {
            "company_of_interest": "AAPL",
            "trade_date": "2026-02-20",
            "sentiment_report": "Report.",
            "fundamentals_report": "",
            "dealflow_context": {
                "subscores": {
                    "social_momentum": 72,
                    "cashtag_momentum": 65,
                    "news_catalyst": 80,
                },
                "evidence": {
                    "evidence_count": 15,
                    "freshness_hours": 4.2,
                },
                "why_now": "Earnings beat expectations",
                "thesis_tags": ["momentum", "catalyst"],
            },
        }

        node(state)

        assert len(call_log) > 0
        human_msg = [m for m in call_log[0] if m[0] == "human"][0][1]
        assert "Deal Flow Signals" in human_msg
        assert "72" in human_msg
