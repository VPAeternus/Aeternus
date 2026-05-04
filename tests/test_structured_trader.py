"""Tests for structured trader output."""
import pytest
from unittest.mock import MagicMock, patch
from tradingagents.graph.verdict_schemas import (
    TraderVerdict,
    InvalidationCondition,
    ScenarioOutcome,
    ConvictionMilestone,
)
from tradingagents.agents.trader.trader import create_trader, _format_trader_verdict


def _make_state(company="AAPL"):
    """Build a minimal AgentState dict for trader tests."""
    return {
        "company_of_interest": company,
        "investment_plan": "Buy AAPL based on strong fundamentals",
        "market_report": "Market trending up",
        "sentiment_report": "Positive sentiment",
        "news_report": "No major news",
        "fundamentals_report": "Strong earnings",
        "fundamental_metrics": {},
        "sentiment_metrics": {},
        "macro_metrics": {},
        "momentum_metrics": {},
        "structured_verdict": {},
        "trade_lessons": "",
    }


class TestFormatTraderVerdict:
    def test_minimal_verdict(self):
        verdict = TraderVerdict(
            decision="BUY", conviction=4, reasoning="Strong case",
        )
        text = _format_trader_verdict(verdict)
        assert "BUY" in text
        assert "4/5" in text
        assert "FINAL TRANSACTION PROPOSAL" in text

    def test_full_verdict(self):
        verdict = TraderVerdict(
            decision="BUY",
            conviction=4,
            reasoning="Strong fundamentals",
            invalidation_conditions=[
                InvalidationCondition(
                    metric="price", operator="<", threshold=140.0,
                    description="Below support",
                ),
            ],
            scenarios=[
                ScenarioOutcome(label="BULL", probability=0.3, target_return_pct=20.0, description="Best case"),
                ScenarioOutcome(label="BASE", probability=0.5, target_return_pct=8.0, description="Likely"),
                ScenarioOutcome(label="BEAR", probability=0.2, target_return_pct=-10.0, description="Worst"),
            ],
            milestones=[
                ConvictionMilestone(trigger_type="price_above", trigger_value=200.0, new_conviction=5, action="ADD"),
            ],
            position_size_pct=0.08,
        )
        text = _format_trader_verdict(verdict)
        assert "Scenarios:" in text
        assert "BULL" in text
        assert "BASE" in text
        assert "BEAR" in text
        assert "Invalidation conditions:" in text
        assert "price < 140" in text
        assert "Milestones:" in text
        assert "8%" in text

    def test_verdict_with_target_price(self):
        verdict = TraderVerdict(
            decision="SELL", conviction=2, reasoning="Weak",
            scenarios=[
                ScenarioOutcome(label="BEAR", probability=0.6, target_price=120.0, description="Decline"),
            ],
        )
        text = _format_trader_verdict(verdict)
        assert "$120.00" in text


class TestCreateTrader:
    def test_structured_output_success(self):
        """When structured output works, both text and dict are returned."""
        mock_verdict = TraderVerdict(
            decision="BUY", conviction=4, reasoning="Good setup",
            position_size_pct=0.05,
        )

        mock_llm = MagicMock()
        mock_structured_llm = MagicMock()
        mock_structured_llm.invoke.return_value = mock_verdict
        mock_llm.with_structured_output.return_value = mock_structured_llm

        mock_memory = MagicMock()
        mock_memory.get_memories.return_value = []

        trader_fn = create_trader(mock_llm, mock_memory)
        result = trader_fn(_make_state())

        assert "trader_investment_plan" in result
        assert "BUY" in result["trader_investment_plan"]
        assert "structured_trader_verdict" in result
        assert result["structured_trader_verdict"]["decision"] == "BUY"
        assert result["structured_trader_verdict"]["conviction"] == 4

    def test_structured_output_fallback(self):
        """When structured output fails, falls back to text."""
        mock_llm = MagicMock()
        mock_llm.with_structured_output.side_effect = Exception("Schema not supported")

        mock_result = MagicMock()
        mock_result.content = "FINAL TRANSACTION PROPOSAL: **BUY**"
        mock_llm.invoke.return_value = mock_result

        mock_memory = MagicMock()
        mock_memory.get_memories.return_value = []

        trader_fn = create_trader(mock_llm, mock_memory)
        result = trader_fn(_make_state())

        assert "trader_investment_plan" in result
        assert "BUY" in result["trader_investment_plan"]
        assert result["structured_trader_verdict"] == {}

    def test_output_includes_sender(self):
        mock_verdict = TraderVerdict(
            decision="HOLD", conviction=3, reasoning="Neutral",
        )
        mock_llm = MagicMock()
        mock_structured_llm = MagicMock()
        mock_structured_llm.invoke.return_value = mock_verdict
        mock_llm.with_structured_output.return_value = mock_structured_llm

        mock_memory = MagicMock()
        mock_memory.get_memories.return_value = []

        trader_fn = create_trader(mock_llm, mock_memory)
        result = trader_fn(_make_state())

        assert result["sender"] == "Trader"

    def test_trade_lessons_injected(self):
        """Trade lessons should be included in the prompt."""
        mock_verdict = TraderVerdict(
            decision="SELL", conviction=2, reasoning="Downtrend",
        )
        mock_llm = MagicMock()
        mock_structured_llm = MagicMock()
        mock_structured_llm.invoke.return_value = mock_verdict
        mock_llm.with_structured_output.return_value = mock_structured_llm

        mock_memory = MagicMock()
        mock_memory.get_memories.return_value = []

        state = _make_state()
        state["trade_lessons"] = "Last AAPL trade lost 5% due to ignoring macro"

        trader_fn = create_trader(mock_llm, mock_memory)
        result = trader_fn(state)

        # Verify the LLM was called (lessons are in the prompt, not the output)
        assert mock_structured_llm.invoke.called
