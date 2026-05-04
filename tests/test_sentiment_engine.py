"""Tests for tradingagents.agents.utils.sentiment_engine"""

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

from tradingagents.agents.utils.sentiment_engine import (
    _direction_from_score,
    extract_av_sentiment,
    score_text_sentiment,
    build_sentiment_snapshot,
)


# --- Factories ---

def _av_article(**overrides):
    base = {
        "overall_sentiment_score": "0.5",
        "ticker_sentiment": [
            {
                "ticker": "AAPL",
                "ticker_sentiment_score": "0.5",
                "relevance_score": "0.8",
            }
        ],
        "topics": [
            {
                "topic": "Earnings",
                "relevance_score": "0.6",
            }
        ],
    }
    base.update(overrides)
    return base


def _av_feed(*articles):
    """Wrap articles in AV feed format and return as JSON string."""
    if not articles:
        articles = []
    return json.dumps({"feed": list(articles)})


# --- Tests for _direction_from_score ---

class TestDirectionFromScore:
    def test_bullish(self):
        assert _direction_from_score(70) == "BULLISH"

    def test_bearish(self):
        assert _direction_from_score(30) == "BEARISH"

    def test_neutral(self):
        assert _direction_from_score(50) == "NEUTRAL"

    def test_boundary_bullish(self):
        assert _direction_from_score(60) == "BULLISH"

    def test_boundary_bearish(self):
        assert _direction_from_score(40) == "BEARISH"


# --- Tests for extract_av_sentiment ---

class TestExtractAvSentiment:
    def test_happy_path(self):
        articles = [
            _av_article(overall_sentiment_score="0.6"),
            _av_article(overall_sentiment_score="0.5"),
            _av_article(overall_sentiment_score="0.4"),
        ]
        feed = _av_feed(*articles)
        result = extract_av_sentiment(feed, "AAPL")

        assert result is not None
        assert result["social_score"] > 50
        assert result["article_count"] == 3

    def test_empty_response(self):
        result = extract_av_sentiment("", "AAPL")
        assert result is None

    def test_none_response(self):
        result = extract_av_sentiment(None, "AAPL")
        assert result is None

    def test_not_av_format(self):
        payload = json.dumps({"items": []})
        result = extract_av_sentiment(payload, "AAPL")
        assert result is None

    def test_no_articles(self):
        feed = _av_feed()
        result = extract_av_sentiment(feed, "AAPL")
        assert result is None

    def test_negative_sentiment(self):
        articles = [
            _av_article(
                overall_sentiment_score="-0.5",
                ticker_sentiment=[
                    {
                        "ticker": "AAPL",
                        "ticker_sentiment_score": "-0.5",
                        "relevance_score": "0.8",
                    }
                ],
            ),
            _av_article(
                overall_sentiment_score="-0.6",
                ticker_sentiment=[
                    {
                        "ticker": "AAPL",
                        "ticker_sentiment_score": "-0.6",
                        "relevance_score": "0.8",
                    }
                ],
            ),
        ]
        feed = _av_feed(*articles)
        result = extract_av_sentiment(feed, "AAPL")

        assert result is not None
        assert result["social_score"] < 50

    def test_catalyst_detection(self):
        articles = [
            _av_article(
                topics=[
                    {"topic": "Earnings", "relevance_score": "0.9"},
                    {"topic": "Other", "relevance_score": "0.3"},
                ]
            )
        ]
        feed = _av_feed(*articles)
        result = extract_av_sentiment(feed, "AAPL")

        assert result is not None
        assert result["catalyst_score"] > 20

    def test_ticker_specific_score(self):
        articles = [
            _av_article(
                ticker_sentiment=[
                    {
                        "ticker": "AAPL",
                        "ticker_sentiment_score": "0.8",
                        "relevance_score": "0.9",
                    }
                ]
            )
        ]
        feed = _av_feed(*articles)
        result = extract_av_sentiment(feed, "AAPL")

        assert result is not None
        assert result["social_score"] > 60  # 0.8 -> score > 60

    def test_extra_fields(self):
        articles = [_av_article()]
        feed = _av_feed(*articles)
        result = extract_av_sentiment(feed, "AAPL")

        assert result is not None
        assert "avg_score" in result
        assert "label" in result
        assert "relevance_weighted_score" in result
        assert "article_count" in result


# --- Tests for score_text_sentiment ---

class TestScoreTextSentiment:
    def test_empty_text(self):
        result = score_text_sentiment("", "AAPL")
        assert result["social_score"] == 50.0
        assert result["direction"] == "NEUTRAL"

    def test_bullish_text(self):
        text = "AAPL beat expectations and raised guidance"
        result = score_text_sentiment(text, "AAPL")

        assert result["social_score"] > 50
        assert result["direction"] == "BULLISH"

    def test_bearish_text(self):
        text = "AAPL missed expectations and lowered guidance"
        result = score_text_sentiment(text, "AAPL")

        assert result["social_score"] < 50
        assert result["direction"] == "BEARISH"

    def test_negation(self):
        text = "AAPL did not beat expectations"
        result = score_text_sentiment(text, "AAPL")

        # Negation should flip the sentiment, making it less bullish
        assert result["social_score"] < 60  # Not fully bullish

    def test_catalyst_detection(self):
        text = "AAPL earnings and FDA approval next week"
        result = score_text_sentiment(text, "AAPL")

        assert result["catalyst_score"] > 20

    def test_mixed_signals(self):
        text = "AAPL beat expectations but also has downside risk"
        result = score_text_sentiment(text, "AAPL")

        # Mixed signals should result in neutral or near-neutral
        assert 40 <= result["social_score"] <= 60 or result["direction"] == "NEUTRAL"


# --- Tests for build_sentiment_snapshot ---

class TestBuildSentimentSnapshot:
    def test_with_av_and_text(self):
        av_articles = [_av_article()]
        av_feed = _av_feed(*av_articles)
        text = "AAPL beat expectations and growth accelerated"

        result = build_sentiment_snapshot(av_feed, text, "AAPL")

        assert result["composite_score"] is not None
        assert result["data_coverage"] == 1.0  # both sources present
        assert "composite_score" in result

    def test_av_only(self):
        av_articles = [_av_article()]
        av_feed = _av_feed(*av_articles)

        result = build_sentiment_snapshot(av_feed, "", "AAPL")

        assert result["composite_score"] is not None
        assert result["buzz"]["source_quality"] == "high"
        assert result["data_coverage"] == 0.5

    def test_text_only(self):
        text = "AAPL beat expectations and raised guidance"

        result = build_sentiment_snapshot("", text, "AAPL")

        assert result["composite_score"] is not None
        assert result["buzz"]["source_quality"] == "medium"
        assert result["data_coverage"] == 0.5

    def test_no_data(self):
        result = build_sentiment_snapshot("", "", "AAPL")

        assert result["composite_score"] == 50.0
        assert result["buzz"]["source_quality"] == "low"
        assert result["data_coverage"] == 0.0

    def test_snapshot_keys(self):
        av_articles = [_av_article()]
        av_feed = _av_feed(*av_articles)
        text = "AAPL beat expectations"

        result = build_sentiment_snapshot(av_feed, text, "AAPL")

        expected_keys = [
            "av_sentiment",
            "text_sentiment",
            "buzz",
            "composite_score",
            "direction",
            "data_coverage",
        ]
        for key in expected_keys:
            assert key in result
