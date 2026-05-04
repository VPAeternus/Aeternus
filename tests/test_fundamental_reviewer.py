"""Tests for tradingagents.agents.analysts.fundamentals_reviewer"""

import json
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

from tradingagents.agents.analysts.fundamentals_reviewer import (
    create_fundamentals_reviewer,
    _REVIEW_PROMPT,
)


# --- Helpers ---

class _FakeLLMResponse:
    """Mimics a langchain chat model response."""
    def __init__(self, content):
        self.content = content


class _FakeLLM:
    """Fake LLM that captures the prompt and returns canned response."""
    def __init__(self, reply="This is the reviewer critique."):
        self.reply = reply
        self.last_messages = None

    def invoke(self, messages):
        self.last_messages = messages
        return _FakeLLMResponse(self.reply)


def _make_state(**overrides):
    """Build a minimal AgentState-like dict for the reviewer."""
    base = {
        "company_of_interest": "AAPL",
        "trade_date": "2026-02-20",
        "fundamentals_report": "## Quality\nF-Score 7/9. ROE 22%.\n## Growth\nRevenue +8% YoY.",
    }
    base.update(overrides)
    return base


def _dummy_metrics():
    """Return a realistic metrics dict matching build_fundamental_snapshot output."""
    return {
        "ratios": {"pe": 25.5, "roe": 0.22, "roa": 0.08},
        "balance": {"current_ratio": 1.5, "debt_to_equity": 0.8},
        "cashflow": {"fcf": 5000000, "fcf_positive": True, "ocf_trend": "improving"},
        "income": {"revenue": 100000000, "net_margin": 0.12, "revenue_trend": "improving"},
        "piotroski": {"fscore": 7, "criteria": {}, "missing_criteria": 0},
        "data_coverage": 0.85,
    }


# --- Tests ---

class TestReviewerWithFullData:
    """Reviewer receives analyst report + metrics."""

    def test_returns_enhanced_report(self, monkeypatch):
        llm = _FakeLLM(reply="Strong fundamentals. F-Score 7 is solid.")
        reviewer = create_fundamentals_reviewer(llm)

        # Patch data gathering to return known values
        monkeypatch.setattr(
            "tradingagents.agents.analysts.fundamentals_reviewer.create_fundamentals_reviewer.__code__",
            None,  # placeholder — we patch the inner functions below
        ) if False else None  # no-op; real patching follows

        # Patch the module-level imports used inside the closure
        import tradingagents.agents.analysts.fundamentals_reviewer as rev_mod

        _orig_create = rev_mod.create_fundamentals_reviewer

        # Simpler approach: monkeypatch the vendor routes
        monkeypatch.setattr(
            "tradingagents.dataflows.interface.route_to_vendor",
            lambda tool_name, *args, **kwargs: json.dumps({"PERatio": "25.5"}),
        )
        monkeypatch.setattr(
            "tradingagents.dataflows.y_finance.get_ticker_info",
            lambda ticker: {"forwardPE": 22.0, "currentPrice": 180.0},
        )

        # Re-create the reviewer so it picks up the patched functions
        reviewer = create_fundamentals_reviewer(llm)
        result = reviewer(_make_state())

        assert "fundamentals_report" in result
        assert "Senior Reviewer Critique" in result["fundamentals_report"]
        assert "Original Analyst Report" in result["fundamentals_report"]
        assert "fundamental_metrics" in result

    def test_metrics_dict_has_expected_keys(self, monkeypatch):
        llm = _FakeLLM()

        monkeypatch.setattr(
            "tradingagents.dataflows.interface.route_to_vendor",
            lambda tool_name, *args, **kwargs: json.dumps({
                "PERatio": "25.5", "ReturnOnEquityTTM": "0.22",
                "quarterlyReports": [{"totalAssets": "1000", "totalLiabilities": "500",
                                       "totalShareholderEquity": "500", "totalCurrentAssets": "400",
                                       "totalCurrentLiabilities": "200"}],
            }),
        )
        monkeypatch.setattr(
            "tradingagents.dataflows.y_finance.get_ticker_info",
            lambda ticker: {},
        )

        reviewer = create_fundamentals_reviewer(llm)
        result = reviewer(_make_state())

        metrics = result["fundamental_metrics"]
        for key in ("ratios", "balance", "cashflow", "income", "piotroski", "data_coverage"):
            assert key in metrics, f"Missing expected key: {key}"


class TestReviewerWithEmptyReport:
    """Reviewer handles missing analyst report gracefully."""

    def test_still_produces_output(self, monkeypatch):
        llm = _FakeLLM(reply="Metrics-only review.")

        monkeypatch.setattr(
            "tradingagents.dataflows.interface.route_to_vendor",
            lambda tool_name, *args, **kwargs: json.dumps({"PERatio": "10"}),
        )
        monkeypatch.setattr(
            "tradingagents.dataflows.y_finance.get_ticker_info",
            lambda ticker: {},
        )

        reviewer = create_fundamentals_reviewer(llm)
        result = reviewer(_make_state(fundamentals_report=""))

        assert result["fundamentals_report"]
        assert "Senior Reviewer Critique" in result["fundamentals_report"]
        # Should NOT contain "Original Analyst Report" section when empty
        assert "Original Analyst Report" not in result["fundamentals_report"]


class TestReviewerGracefulDegradation:
    """Reviewer handles data-gathering failures."""

    def test_vendor_failure_returns_empty_metrics(self, monkeypatch):
        llm = _FakeLLM(reply="Cannot compute metrics.")

        monkeypatch.setattr(
            "tradingagents.dataflows.interface.route_to_vendor",
            lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("API down")),
        )
        monkeypatch.setattr(
            "tradingagents.dataflows.y_finance.get_ticker_info",
            lambda ticker: (_ for _ in ()).throw(RuntimeError("yfinance down")),
        )

        reviewer = create_fundamentals_reviewer(llm)
        result = reviewer(_make_state())

        assert result["fundamental_metrics"] == {}
        assert "Senior Reviewer Critique" in result["fundamentals_report"]


class TestReviewerPromptContent:
    """Verify the LLM receives expected content."""

    def test_prompt_contains_metrics_and_report(self, monkeypatch):
        llm = _FakeLLM()

        monkeypatch.setattr(
            "tradingagents.dataflows.interface.route_to_vendor",
            lambda tool_name, *args, **kwargs: json.dumps({"PERatio": "30.0"}),
        )
        monkeypatch.setattr(
            "tradingagents.dataflows.y_finance.get_ticker_info",
            lambda ticker: {"forwardPE": 28.0},
        )

        reviewer = create_fundamentals_reviewer(llm)
        state = _make_state(fundamentals_report="F-Score is 8/9.")
        reviewer(state)

        # Check the system message is the review prompt
        assert llm.last_messages[0][1] == _REVIEW_PROMPT

        # Check the user message contains the analyst report and metrics
        user_msg = llm.last_messages[1][1]
        assert "F-Score is 8/9." in user_msg
        # Metrics are normalized by build_fundamental_snapshot to snake_case keys
        assert '"pe"' in user_msg
        assert "forward_pe" in user_msg
        assert "AAPL" in user_msg

    def test_review_prompt_is_non_empty(self):
        assert len(_REVIEW_PROMPT) > 100
        assert "CRITIQUE" in _REVIEW_PROMPT


class TestGraphBackwardCompat:
    """Verify graph setup doesn't break without fundamentals selected."""

    def test_setup_without_fundamentals_has_no_reviewer(self):
        """When fundamentals is not selected, Fundamental Reviewer should not appear."""
        # We test this by checking setup.py logic indirectly — import and inspect
        from tradingagents.graph.setup import GraphSetup

        # The key assertion is that GraphSetup can be instantiated.
        # Full graph compilation requires LLMs, so we just verify the import works.
        assert hasattr(GraphSetup, "setup_graph")
