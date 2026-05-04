"""Tests for analyst bypass pattern — pre-fetched data + quality gate prompts."""

import pytest
from unittest.mock import MagicMock, patch


def _make_llm_mock(return_text="Mock report"):
    """Create a mock LLM that captures the prompt it receives."""
    llm = MagicMock()
    response = MagicMock()
    response.content = return_text
    llm.invoke = MagicMock(return_value=response)
    return llm


class TestMarketAnalystBypass:
    def test_uses_prefetched_data(self):
        from tradingagents.agents.analysts.market_analyst import create_market_analyst
        llm = _make_llm_mock()
        node = create_market_analyst(llm)

        state = {
            "trade_date": "2026-03-01",
            "company_of_interest": "AAPL",
            "market_raw": {
                "price_data": "date,close\n2026-02-28,150\n",
                "indicators": {"rsi": "RSI: 55", "macd": "MACD: 0.5"},
                "quality": {
                    "price_rows": 1,
                    "indicators_fetched": 2,
                    "indicators_missing": ["atr", "boll_ub"],
                    "fetch_errors": [],
                },
            },
        }

        result = node(state)
        assert "market_report" in result

        prompt = llm.invoke.call_args[0][0]
        assert "DATA QUALITY" in prompt
        assert "Price rows: 1" in prompt
        assert "2/8 fetched" in prompt
        assert "atr" in prompt

    @patch("tradingagents.agents.analysts.market_analyst.get_stock_data")
    @patch("tradingagents.agents.analysts.market_analyst.get_indicators")
    def test_fallback_without_prefetched(self, mock_ind, mock_stock):
        from tradingagents.agents.analysts.market_analyst import create_market_analyst
        llm = _make_llm_mock()
        node = create_market_analyst(llm)

        mock_stock.invoke.return_value = "price data"
        mock_ind.invoke.return_value = "indicator data"

        state = {
            "trade_date": "2026-03-01",
            "company_of_interest": "AAPL",
        }

        result = node(state)
        assert "market_report" in result
        mock_stock.invoke.assert_called_once()
        assert mock_ind.invoke.call_count > 0

        prompt = llm.invoke.call_args[0][0]
        assert "DATA QUALITY" not in prompt


class TestNewsAnalystBypass:
    def test_uses_prefetched_data(self):
        from tradingagents.agents.analysts.news_analyst import create_news_analyst
        llm = _make_llm_mock()
        node = create_news_analyst(llm)

        state = {
            "trade_date": "2026-03-01",
            "company_of_interest": "AAPL",
            "news_raw": {
                "company_news": "AAPL earnings beat expectations",
                "global_news": "Fed holds rates steady",
                "quality": {
                    "company_news_chars": 35,
                    "global_news_chars": 22,
                    "company_news_available": True,
                    "global_news_available": True,
                    "fetch_errors": [],
                },
            },
        }

        result = node(state)
        assert "news_report" in result

        prompt = llm.invoke.call_args[0][0]
        assert "DATA QUALITY" in prompt
        assert "available" in prompt
        assert "35 chars" in prompt

    @patch("tradingagents.agents.analysts.news_analyst.get_news")
    @patch("tradingagents.agents.analysts.news_analyst.get_global_news")
    def test_fallback_without_prefetched(self, mock_global, mock_news):
        from tradingagents.agents.analysts.news_analyst import create_news_analyst
        llm = _make_llm_mock()
        node = create_news_analyst(llm)

        mock_news.invoke.return_value = "company news"
        mock_global.invoke.return_value = "global news"

        state = {
            "trade_date": "2026-03-01",
            "company_of_interest": "AAPL",
        }

        result = node(state)
        assert "news_report" in result
        mock_news.invoke.assert_called_once()
        mock_global.invoke.assert_called_once()

        prompt = llm.invoke.call_args[0][0]
        assert "DATA QUALITY" not in prompt


class TestFundamentalsAnalystBypass:
    def test_uses_prefetched_data(self):
        from tradingagents.agents.analysts.fundamentals_analyst import create_fundamentals_analyst
        llm = _make_llm_mock()
        node = create_fundamentals_analyst(llm)

        state = {
            "trade_date": "2026-03-01",
            "company_of_interest": "AAPL",
            "fundamentals_raw": {
                "snapshot": '{"piotroski": {"fscore": 7}, "data_coverage": 0.85}',
                "valuation": '{"forward_pe": 25.0}',
                "quality": {
                    "data_coverage": 0.85,
                    "piotroski_available": True,
                    "valuation_fields": 1,
                    "fetch_errors": [],
                },
            },
        }

        result = node(state)
        assert "fundamentals_report" in result

        prompt = llm.invoke.call_args[0][0]
        assert "DATA QUALITY" in prompt
        assert "0.85" in prompt
        assert "available" in prompt

    @patch("tradingagents.agents.analysts.fundamentals_analyst.get_fundamental_snapshot")
    @patch("tradingagents.agents.analysts.fundamentals_analyst.get_valuation_context")
    def test_fallback_without_prefetched(self, mock_val, mock_snap):
        from tradingagents.agents.analysts.fundamentals_analyst import create_fundamentals_analyst
        llm = _make_llm_mock()
        node = create_fundamentals_analyst(llm)

        mock_snap.invoke.return_value = '{"data": "snapshot"}'
        mock_val.invoke.return_value = '{"forward_pe": 25.0}'

        state = {
            "trade_date": "2026-03-01",
            "company_of_interest": "AAPL",
        }

        result = node(state)
        assert "fundamentals_report" in result
        mock_snap.invoke.assert_called_once()
        mock_val.invoke.assert_called_once()

        prompt = llm.invoke.call_args[0][0]
        assert "DATA QUALITY" not in prompt
