from tradingagents.graph.thesis_check import ThesisChecker


class MockLLM:
    def __init__(self, content: str):
        self._content = content

    def invoke(self, messages):
        class MockResponse:
            def __init__(self, content):
                self.content = content

        return MockResponse(self._content)


def test_thesis_check_valid_json():
    checker = ThesisChecker(
        MockLLM(
            """
            {
                "thesis_change": "YES",
                "reason": "Macro regime changed and momentum weakened.",
                "daily_signals": ["MACD rollover", "Negative sentiment trend"],
                "confidence": 4
            }
            """
        )
    )

    state = {
        "company_of_interest": "AAPL",
        "trade_date": "2026-02-05",
        "market_report": "Market report",
        "sentiment_report": "Sentiment report",
        "news_report": "News report",
        "investment_plan": "Investment plan",
        "final_trade_decision": "Buy",
    }

    result = checker.check(state)
    assert result["ticker"] == "AAPL"
    assert result["date"] == "2026-02-05"
    assert result["thesis_change"] == "YES"
    assert "Macro regime changed" in result["reason"]
    assert isinstance(result["daily_signals"], list)
    assert result["confidence"] == 4


def test_thesis_check_fallback_on_invalid_response():
    checker = ThesisChecker(MockLLM("not json"))
    result = checker.check({"company_of_interest": "TSLA", "trade_date": "2026-02-05"})

    assert result["thesis_change"] == "NO"
    assert isinstance(result["reason"], str)
    assert isinstance(result["daily_signals"], list)
    assert 1 <= result["confidence"] <= 5
