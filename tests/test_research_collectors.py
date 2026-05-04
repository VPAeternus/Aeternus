"""Tests for research_collectors — pre-fetch vendor data with quality metadata."""

import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture
def mock_route():
    """Mock route_to_vendor for all collector tests."""
    with patch("tradingagents.graph.research_collectors.route_to_vendor") as m:
        yield m


class TestCollectMarketData:
    def test_success_all_indicators(self, mock_route):
        mock_route.side_effect = lambda method, *a, **kw: {
            "get_stock_data": "date,open,high,low,close,volume\n" * 60,
            "get_indicators": f"indicator_data for {a[1] if len(a) > 1 else ''}",
        }.get(method, "")

        from tradingagents.graph.research_collectors import collect_market_data
        result = collect_market_data("AAPL", "2026-03-01")

        assert result["price_data"]
        assert result["quality"]["price_rows"] == 60
        assert result["quality"]["indicators_fetched"] == 8
        assert result["quality"]["indicators_missing"] == []
        assert result["quality"]["fetch_errors"] == []

    def test_partial_indicator_failure(self, mock_route):
        call_count = {"n": 0}

        def side_effect(method, *a, **kw):
            if method == "get_stock_data":
                return "row\n" * 30
            if method == "get_indicators":
                call_count["n"] += 1
                if call_count["n"] % 3 == 0:
                    raise ConnectionError("timeout")
                return "data"
            return ""

        mock_route.side_effect = side_effect
        from tradingagents.graph.research_collectors import collect_market_data
        result = collect_market_data("AAPL", "2026-03-01")

        q = result["quality"]
        assert q["indicators_fetched"] < 8
        assert len(q["indicators_missing"]) > 0
        assert q["fetch_errors"] == []  # indicator failures go to missing, not errors

    def test_price_fetch_failure(self, mock_route):
        def side_effect(method, *a, **kw):
            if method == "get_stock_data":
                raise RuntimeError("API down")
            return "indicator_data"

        mock_route.side_effect = side_effect
        from tradingagents.graph.research_collectors import collect_market_data
        result = collect_market_data("AAPL", "2026-03-01")

        assert result["price_data"] == ""
        assert result["quality"]["price_rows"] == 0
        assert len(result["quality"]["fetch_errors"]) == 1

    def test_none_vendor_return_produces_empty_string(self, mock_route):
        """str(None) should NOT leak as 'None' string — must be empty."""
        mock_route.return_value = None

        from tradingagents.graph.research_collectors import collect_market_data
        result = collect_market_data("AAPL", "2026-03-01")

        assert result["price_data"] == ""
        assert result["quality"]["price_rows"] == 0
        # Indicators that returned None should be in missing, not in indicators dict
        assert result["quality"]["indicators_fetched"] == 0
        assert len(result["quality"]["indicators_missing"]) == 8

    def test_none_indicator_counted_as_missing(self, mock_route):
        """An indicator returning None should land in missing, not indicators."""
        def side_effect(method, *a, **kw):
            if method == "get_stock_data":
                return "row\n" * 10
            if method == "get_indicators":
                ind_name = a[1] if len(a) > 1 else ""
                return "data" if ind_name != "atr" else None
            return ""

        mock_route.side_effect = side_effect
        from tradingagents.graph.research_collectors import collect_market_data
        result = collect_market_data("AAPL", "2026-03-01")

        assert "atr" in result["quality"]["indicators_missing"]
        assert "atr" not in result["indicators"]


class TestCollectNewsData:
    def test_success(self, mock_route):
        mock_route.side_effect = lambda method, *a, **kw: {
            "get_news": "Company news article content " * 50,
            "get_global_news": "Global macro news " * 30,
        }.get(method, "")

        from tradingagents.graph.research_collectors import collect_news_data
        result = collect_news_data("AAPL", "2026-03-01")

        q = result["quality"]
        assert q["company_news_available"] is True
        assert q["global_news_available"] is True
        assert q["company_news_chars"] > 0
        assert q["global_news_chars"] > 0
        assert q["fetch_errors"] == []

    def test_company_news_failure(self, mock_route):
        def side_effect(method, *a, **kw):
            if method == "get_news":
                raise RuntimeError("API error")
            return "global news content"

        mock_route.side_effect = side_effect
        from tradingagents.graph.research_collectors import collect_news_data
        result = collect_news_data("AAPL", "2026-03-01")

        q = result["quality"]
        assert q["company_news_available"] is False
        assert q["global_news_available"] is True
        assert len(q["fetch_errors"]) == 1

    def test_empty_responses(self, mock_route):
        mock_route.return_value = ""
        from tradingagents.graph.research_collectors import collect_news_data
        result = collect_news_data("AAPL", "2026-03-01")

        q = result["quality"]
        assert q["company_news_available"] is False
        assert q["global_news_available"] is False

    def test_none_vendor_return_produces_empty_string(self, mock_route):
        """str(None) should NOT leak as 'None' — must be empty."""
        mock_route.return_value = None
        from tradingagents.graph.research_collectors import collect_news_data
        result = collect_news_data("AAPL", "2026-03-01")

        assert result["company_news"] == ""
        assert result["global_news"] == ""
        q = result["quality"]
        assert q["company_news_available"] is False
        assert q["global_news_available"] is False


class TestCollectFundamentalsData:
    @patch("tradingagents.dataflows.y_finance.get_ticker_info")
    @patch("tradingagents.agents.utils.fundamental_engine.compute_yfinance_snapshot")
    @patch("tradingagents.agents.utils.fundamental_engine.build_fundamental_snapshot")
    def test_success(self, mock_build, mock_yf, mock_info, mock_route):
        mock_route.return_value = '{"data": "raw"}'
        mock_build.return_value = {
            "data_coverage": 0.85,
            "piotroski": {"fscore": 7},
            "ratios": {},
        }
        mock_info.return_value = {"symbol": "AAPL"}
        mock_yf.return_value = {"forward_pe": 25.0, "pb": 12.0, "ev_ebitda": None}

        from tradingagents.graph.research_collectors import collect_fundamentals_data
        result = collect_fundamentals_data("AAPL", "2026-03-01")

        q = result["quality"]
        assert q["data_coverage"] == 0.85
        assert q["piotroski_available"] is True
        assert q["valuation_fields"] == 2  # forward_pe and pb, not ev_ebitda (None)
        assert q["fetch_errors"] == []
        assert result["snapshot"]
        assert result["valuation"]

    @patch("tradingagents.dataflows.y_finance.get_ticker_info")
    @patch("tradingagents.agents.utils.fundamental_engine.compute_yfinance_snapshot")
    @patch("tradingagents.agents.utils.fundamental_engine.build_fundamental_snapshot")
    def test_snapshot_failure(self, mock_build, mock_yf, mock_info, mock_route):
        mock_route.side_effect = RuntimeError("API down")
        mock_info.return_value = {"symbol": "AAPL"}
        mock_yf.return_value = {"forward_pe": 25.0}

        from tradingagents.graph.research_collectors import collect_fundamentals_data
        result = collect_fundamentals_data("AAPL", "2026-03-01")

        q = result["quality"]
        assert q["data_coverage"] == 0.0
        assert q["piotroski_available"] is False
        assert len(q["fetch_errors"]) >= 1

    @patch("tradingagents.dataflows.y_finance.get_ticker_info")
    @patch("tradingagents.agents.utils.fundamental_engine.compute_yfinance_snapshot")
    @patch("tradingagents.agents.utils.fundamental_engine.build_fundamental_snapshot")
    def test_payload_guard_caps_large_snapshot(self, mock_build, mock_yf, mock_info, mock_route):
        """Snapshot must be capped at 12k chars — same guard as the tool path."""
        mock_route.return_value = '{"data": "raw"}'
        # Build a snapshot that will serialize to >12k chars
        mock_build.return_value = {
            "data_coverage": 0.9,
            "piotroski": {"fscore": 5},
            "big_field": "x" * 20000,
        }
        mock_info.return_value = {"symbol": "AAPL"}
        mock_yf.return_value = {"forward_pe": 25.0}

        from tradingagents.graph.research_collectors import collect_fundamentals_data
        result = collect_fundamentals_data("AAPL", "2026-03-01")

        assert len(result["snapshot"]) <= 12000
