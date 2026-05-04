# tests/test_aeternus_scoring.py

import sys
import types
import pytest
from unittest.mock import MagicMock

# Stub chromadb before it can be imported (pydantic v1 incompatible with Python 3.14)
if "chromadb" not in sys.modules or not hasattr(sys.modules.get("chromadb", None), "__path__"):
    _stub = types.ModuleType("chromadb")
    _stub.__path__ = []  # make it look like a package
    _stub.Client = None
    _config_stub = types.ModuleType("chromadb.config")
    _config_stub.Settings = type("Settings", (), {})
    sys.modules["chromadb"] = _stub
    sys.modules["chromadb.config"] = _config_stub

from tradingagents.graph.aeternus_scoring import AeternusScorer, AeternusRating, _ScorerLLMResponse


class MockLLM:
    """Mock LLM for testing."""
    
    def invoke(self, messages):
        class MockResponse:
            content = """
            {
                "fundamental_score": 75,
                "technical_score": 70,
                "macro_score": 65,
                "sentiment_score": 80,
                "momentum_score": 72,
                "confidence": 4,
                "score_rationales": {
                    "fundamental": "Strong earnings",
                    "technical": "Uptrend",
                    "macro": "Favorable conditions",
                    "sentiment": "Positive",
                    "momentum": "Strong"
                }
            }
            """
        return MockResponse()


def test_aeternus_rating_schema():
    """Test that score() returns AeternusRating with all required fields."""
    scorer = AeternusScorer(MockLLM())
    state = {
        "ticker": "AAPL",
        "date": "2024-05-10",
        "market_report": "Test report",
    }
    
    rating = scorer.score(state, ticker="AAPL", date="2024-05-10", price_at_rating=150.0)
    
    # Check all required fields exist
    assert "ticker" in rating
    assert "date" in rating
    assert "aeternus_score" in rating
    assert "rating" in rating
    assert "confidence" in rating
    assert "breakdown" in rating
    assert "rationales" in rating
    assert "price_at_rating" in rating
    assert "price_target" in rating
    assert "catalyst" in rating
    assert "confidence_factors" in rating
    assert "timestamp" in rating
    
    # Check types
    assert isinstance(rating["ticker"], str)
    assert isinstance(rating["date"], str)
    assert isinstance(rating["aeternus_score"], float)
    assert isinstance(rating["rating"], str)
    assert isinstance(rating["confidence"], int)
    assert isinstance(rating["breakdown"], dict)
    assert isinstance(rating["rationales"], dict)
    assert isinstance(rating["confidence_factors"], dict)
    assert rating["price_at_rating"] is None or isinstance(rating["price_at_rating"], (int, float))
    assert rating["price_target"] is None or isinstance(rating["price_target"], (int, float))
    assert rating["catalyst"] is None or isinstance(rating["catalyst"], str)
    assert isinstance(rating["timestamp"], str)


def test_score_clamping():
    """Test that scores are clamped to valid ranges."""
    scorer = AeternusScorer(MockLLM())
    state = {"market_report": "Test"}
    
    rating = scorer.score(state)
    
    # Score should be 0-100
    assert 0 <= rating["aeternus_score"] <= 100
    
    # Confidence should be 1-5
    assert 1 <= rating["confidence"] <= 5
    
    # Breakdown scores should be 0-100
    for score in rating["breakdown"].values():
        assert 0 <= score <= 100


def test_state_identity_fallbacks():
    """Test ticker/date fallback from graph state keys."""
    scorer = AeternusScorer(MockLLM())
    state = {
        "company_of_interest": "MSFT",
        "trade_date": "2024-05-12",
        "market_report": "Test",
    }

    rating = scorer.score(state)

    assert rating["ticker"] == "MSFT"
    assert rating["date"] == "2024-05-12"


def test_rating_thresholds():
    """Test that _rating_from_score returns correct labels for all threshold boundaries."""
    scorer = AeternusScorer(MockLLM())
    cases = [
        (85, "Strong Buy"),
        (75, "Buy"),
        (50, "Hold"),
        (30, "Sell"),
        (10, "Strong Sell"),
    ]
    for score, expected_rating in cases:
        assert scorer._rating_from_score(score) == expected_rating, (
            f"score={score}: expected {expected_rating!r}"
        )



def test_dealflow_source_maps_subscores():
    """When source=='dealflow', subscores map directly: social_momentum→polarity, cashtag→buzz, news→catalyst."""
    scorer = AeternusScorer(MockLLM())
    metrics = {
        "source": "dealflow",
        "social_momentum": 72,
        "cashtag_momentum": 65,
        "news_catalyst": 80,
    }
    result = scorer._compute_sentiment_sub(metrics)
    assert result["polarity"] == 72
    assert result["buzz"] == 65
    assert result["catalyst"] == 80


def test_computed_source_unchanged():
    """When source != 'dealflow', existing logic is used (composite_score → polarity etc)."""
    scorer = AeternusScorer(MockLLM())
    metrics = {
        "source": "computed",
        "composite_score": 68,
        "buzz": {"total_articles": 20, "source_quality": "high"},
        "text_sentiment": {"catalyst_score": 55, "direction": "BULLISH"},
        "direction": "BULLISH",
    }
    result = scorer._compute_sentiment_sub(metrics)
    # composite_score 68 → polarity 68
    assert result["polarity"] == 68
    # 20 articles → score 70, high quality +10 = 80
    assert result["buzz"] == 80
    # catalyst_score 55 clamped + direction alignment bonus 10 = 65
    assert result["catalyst"] == 65


def test_macro_anchored_overrides_llm():
    """When macro_metrics provided with subscores, anchored score replaces LLM macro score."""
    scorer = AeternusScorer(MockLLM())
    state = {"market_report": "Test"}
    macro_metrics = {
        "regime": "BULL",
        "data_coverage": 0.9,
        "subscores": {
            "regime_fit": 78,
            "monetary_stress": 55,
            "rate_headwind": 42,
            "commodity_cycle": 60,
        },
    }
    rating = scorer.score(state, macro_metrics=macro_metrics)
    # Anchored macro = 78*0.25 + 55*0.25 + 42*0.25 + 60*0.25 = 58.75 → 59
    assert rating["breakdown"]["macro"] == 59
    assert rating["macro_sub"] is not None
    assert rating["macro_sub"]["regime_fit"] == 78
    assert rating["macro_sub"]["monetary_stress"] == 55
    assert rating["macro_sub"]["rate_headwind"] == 42
    assert rating["macro_sub"]["commodity_cycle"] == 60


def test_macro_sub_scores_structure():
    """Verify macro_sub has 4 keys, all clamped 0-100."""
    scorer = AeternusScorer(MockLLM())
    metrics = {
        "subscores": {
            "regime_fit": 150,  # should clamp to 100
            "monetary_stress": -10,  # should clamp to 0
            "rate_headwind": 42,
            "commodity_cycle": 60,
        }
    }
    result = scorer._compute_macro_sub(metrics)
    assert set(result.keys()) == {"regime_fit", "monetary_stress", "rate_headwind", "commodity_cycle"}
    assert result["regime_fit"] == 100
    assert result["monetary_stress"] == 0
    assert 0 <= result["rate_headwind"] <= 100
    assert 0 <= result["commodity_cycle"] <= 100


def test_macro_absent_falls_back_to_llm():
    """When no macro_metrics provided, LLM score is used (65 from MockLLM)."""
    scorer = AeternusScorer(MockLLM())
    state = {"market_report": "Test"}
    rating = scorer.score(state)
    assert rating["breakdown"]["macro"] == 65  # MockLLM returns 65
    assert rating["macro_sub"] is None


def test_coherence_replaces_technical():
    """Breakdown has 'coherence' key, no 'technical'."""
    scorer = AeternusScorer(MockLLM())
    state = {"market_report": "Test"}
    rating = scorer.score(state)
    assert "coherence" in rating["breakdown"]
    assert "technical" not in rating["breakdown"]
    assert set(rating["breakdown"].keys()) == {"fundamental", "coherence", "macro", "sentiment", "momentum"}


def test_regime_adaptive_weights_bear():
    """BEAR regime uses different weights than NEUTRAL."""
    scorer = AeternusScorer(MockLLM())
    state = {"market_report": "Test"}
    macro_metrics = {"regime": "BEAR", "data_coverage": 0.9, "subscores": {"regime_fit": 30, "monetary_stress": 40, "rate_headwind": 60, "commodity_cycle": 50}}
    rating = scorer.score(state, macro_metrics=macro_metrics)
    assert rating["weight_regime"] == "BEAR"
    assert rating["regime_weights"]["coherence"] == 0.30
    assert rating["regime_weights"]["macro"] == 0.25


def test_regime_adaptive_weights_default():
    """Unknown regime falls back to NEUTRAL weights."""
    scorer = AeternusScorer(MockLLM())
    state = {"market_report": "Test"}
    macro_metrics = {"regime": "TOTALLY_UNKNOWN", "data_coverage": 0.9, "subscores": {"regime_fit": 50, "monetary_stress": 50, "rate_headwind": 50, "commodity_cycle": 50}}
    rating = scorer.score(state, macro_metrics=macro_metrics)
    assert rating["weight_regime"] == "TOTALLY_UNKNOWN"
    assert rating["regime_weights"]["fundamental"] == 0.30
    assert rating["regime_weights"]["coherence"] == 0.25


def test_alpha_decomposition_present():
    """Alpha decomposition dict has required keys."""
    scorer = AeternusScorer(MockLLM())
    state = {"market_report": "Test"}
    rating = scorer.score(state)
    ad = rating["alpha_decomposition"]
    assert ad is not None
    assert "factor_predicted" in ad
    assert "alpha_residual" in ad
    assert "interpretation" in ad
    assert isinstance(ad["factor_predicted"], float)
    assert isinstance(ad["alpha_residual"], float)
    assert isinstance(ad["interpretation"], str)


def test_fundamental_overlay_present_and_advisory():
    scorer = AeternusScorer(MockLLM())
    state = {"market_report": "Test"}
    fundamental_metrics = {
        "data_coverage": 0.9,
        "piotroski": {"fscore": 7},
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

    rating = scorer.score(state, fundamental_metrics=fundamental_metrics)

    expected_score = round(
        (rating["fundamental_sub"]["health"] * 0.5)
        + ((100 - rating["fundamental_sub"]["quality"]) * 0.4)
        + ((100 - rating["fundamental_sub"]["growth"]) * 0.1),
        2,
    )

    assert rating["fundamental_overlay_score"] == expected_score
    assert rating["fundamental_overlay_label"] in {
        "UNDERAPPRECIATED_RESILIENCE",
        "BALANCED",
        "CROWDING_RISK",
    }
    assert isinstance(rating["fundamental_overlay_notes"], str)
    assert rating["fundamental_shadow_strategy"] == "health_0p5__inv_growth_0p1__inv_quality_0p4"
    assert rating["fundamental_shadow_gate_status"] in {"PASSED", "PENDING"}
    assert rating["fundamental_shadow_recommended_status"] in {"shadow", "candidate"}
    assert rating["breakdown"]["fundamental"] != rating["fundamental_overlay_score"]


def test_fundamental_overlay_absent_when_fundamentals_gated():
    scorer = AeternusScorer(MockLLM())
    state = {"market_report": "Test"}
    fundamental_metrics = {
        "data_coverage": 0.1,
        "piotroski": {"fscore": 7},
        "ratios": {"roe": 18.5},
    }

    rating = scorer.score(state, fundamental_metrics=fundamental_metrics)

    assert rating["fundamental_sub"] is None
    assert rating["fundamental_overlay_score"] is None
    assert rating["fundamental_overlay_label"] is None
    assert rating["fundamental_overlay_notes"] is None
    assert rating["fundamental_shadow_strategy"] == "health_0p5__inv_growth_0p1__inv_quality_0p4"
    assert rating["fundamental_shadow_gate_status"] in {"PASSED", "PENDING"}


def test_catalyst_timeline_structure():
    """Catalyst timeline has correct keys when present (or is None)."""
    scorer = AeternusScorer(MockLLM())
    state = {"market_report": "Test"}
    rating = scorer.score(state, ticker="AAPL")
    ct = rating["catalyst_timeline"]
    # catalyst_timeline can be None if yfinance fails, or a dict with expected keys
    if ct is not None:
        assert "days_to_earnings" in ct
        assert "days_to_dividend" in ct
        assert "earnings_proximity" in ct
        assert "event_density_30d" in ct


def test_coherence_sub_structure():
    """coherence_sub has 4 expected sub-score keys."""
    scorer = AeternusScorer(MockLLM())
    state = {"market_report": "Test"}
    rating = scorer.score(state)
    cs = rating["coherence_sub"]
    assert cs is not None
    assert set(cs.keys()) == {"directional_alignment", "conviction_strength", "interaction_patterns", "narrative_stability"}
    for v in cs.values():
        assert isinstance(v, int)
        assert 0 <= v <= 100


def test_structured_output_used_when_available():
    """When with_structured_output succeeds, data is extracted from Pydantic model."""
    pydantic_result = _ScorerLLMResponse(
        fundamental_score=72,
        technical_score=68,
        macro_score=61,
        sentiment_score=77,
        momentum_score=55,
        confidence=4,
        score_rationales={
            "fundamental": "Strong earnings",
            "technical": "Uptrend",
            "macro": "Favorable",
            "sentiment": "Positive",
            "momentum": "Moderate",
        },
    )

    structured_llm_mock = MagicMock()
    structured_llm_mock.invoke.return_value = pydantic_result

    mock_llm = MagicMock()
    mock_llm.with_structured_output.return_value = structured_llm_mock

    scorer = AeternusScorer(mock_llm)
    state = {"market_report": "Test"}
    rating = scorer.score(state)

    # Structured output path was taken
    mock_llm.with_structured_output.assert_called_once_with(_ScorerLLMResponse)
    structured_llm_mock.invoke.assert_called_once()
    # Free-form invoke should NOT have been called
    mock_llm.invoke.assert_not_called()

    # Data extracted correctly from Pydantic model
    assert rating["breakdown"]["macro"] == 61
    assert rating["breakdown"]["sentiment"] == 77
    assert rating["rationales"]["fundamental"] == "Strong earnings"


def test_sentiment_low_coverage_flag_true():
    """When buzz < 40, _sentiment_low_coverage should be True in data_quality_gate."""
    scorer = AeternusScorer(MockLLM())
    state = {"market_report": "Test"}
    sentiment_metrics = {
        "data_coverage": 0.9,
        "source": "dealflow",
        "social_momentum": 35,
        "cashtag_momentum": 25,  # buzz < 40
        "news_catalyst": 50,
    }
    rating = scorer.score(state, sentiment_metrics=sentiment_metrics)
    assert rating["data_quality_gate"]["sentiment_low_coverage"] is True


def test_sentiment_low_coverage_flag_false():
    """When buzz >= 40, _sentiment_low_coverage should be False."""
    scorer = AeternusScorer(MockLLM())
    state = {"market_report": "Test"}
    sentiment_metrics = {
        "data_coverage": 0.9,
        "source": "dealflow",
        "social_momentum": 60,
        "cashtag_momentum": 55,  # buzz >= 40
        "news_catalyst": 70,
    }
    rating = scorer.score(state, sentiment_metrics=sentiment_metrics)
    assert rating["data_quality_gate"]["sentiment_low_coverage"] is False


def test_fallback_to_free_form_on_error():
    """When with_structured_output raises Exception, fallback to _safe_parse_json is used."""
    mock_llm = MagicMock()
    mock_llm.with_structured_output.side_effect = Exception("unsupported")

    class _FallbackResponse:
        content = '{"fundamental_score": 60, "macro_score": 55, "sentiment_score": 45, "momentum_score": 50, "confidence": 3, "score_rationales": {}}'

    mock_llm.invoke.return_value = _FallbackResponse()

    scorer = AeternusScorer(mock_llm)
    state = {"market_report": "Fallback test"}
    rating = scorer.score(state)

    # with_structured_output was attempted
    mock_llm.with_structured_output.assert_called_once_with(_ScorerLLMResponse)
    # Free-form invoke was used as fallback
    mock_llm.invoke.assert_called_once()

    # Scores from fallback JSON
    assert rating["breakdown"]["fundamental"] == 60
    assert rating["breakdown"]["macro"] == 55
    assert rating["breakdown"]["sentiment"] == 45


# --- Ensemble / debate voice extraction tests ---

def test_quant_only_fallback_no_debate_data():
    """Without debate data, quant-only path fires and ensemble fields reflect it."""
    scorer = AeternusScorer(MockLLM())
    state = {"market_report": "Test"}
    rating = scorer.score(state)
    # No debate voices → ensemble_model_scores has None for debate voices
    assert rating["ensemble_model_scores"]["research_debate"] is None
    assert rating["ensemble_model_scores"]["trader_verdict"] is None
    assert rating["ensemble_model_scores"]["risk_verdict"] is None
    # quant_only_score should equal aeternus_score when no debate voices
    assert rating["quant_only_score"] == rating["aeternus_score"]


def test_research_debate_score_structured():
    """Structured judge_decision string → correct 0-100 score."""
    scorer = AeternusScorer(MockLLM())
    state = {
        "market_report": "Test",
        "investment_debate_state": {
            "judge_decision": "Decision: BUY | Conviction: 4/5 | Bull Strength: 4/5 | Bear Strength: 2/5"
        },
    }
    score = scorer._extract_research_debate_score(state)
    # 65 + (4-3)*5 + (4-2)*3 = 65 + 5 + 6 = 76
    assert score == 76


def test_research_debate_score_sell():
    scorer = AeternusScorer(MockLLM())
    state = {
        "market_report": "Test",
        "investment_debate_state": {
            "judge_decision": "Decision: SELL | Conviction: 5/5 | Bull Strength: 2/5 | Bear Strength: 5/5"
        },
    }
    score = scorer._extract_research_debate_score(state)
    # 35 + (5-3)*5 + (2-5)*3 = 35 + 10 + (-9) = 36
    assert score == 36


def test_research_debate_score_fallback_keyword():
    """When no judge_decision, falls back to keyword scan on investment_plan."""
    scorer = AeternusScorer(MockLLM())
    state = {
        "market_report": "Test",
        "investment_plan": "We recommend a BUY with strong conviction",
    }
    score = scorer._extract_research_debate_score(state)
    # BUY keyword, default conviction=3, default strengths=3/3
    # 65 + 0 + 0 = 65
    assert score == 65


def test_research_debate_score_none():
    """Returns None when no debate data at all."""
    scorer = AeternusScorer(MockLLM())
    state = {"market_report": "Test"}
    assert scorer._extract_research_debate_score(state) is None


def test_trader_verdict_score():
    scorer = AeternusScorer(MockLLM())
    state = {
        "market_report": "Test",
        "structured_trader_verdict": {
            "decision": "BUY",
            "conviction": 4,
            "position_size_pct": 0.07,
            "scenarios": [
                {"probability": 0.4, "target_return_pct": 15},
                {"probability": 0.4, "target_return_pct": 5},
                {"probability": 0.2, "target_return_pct": -10},
            ],
        },
    }
    score = scorer._extract_trader_verdict_score(state)
    # direction: 65, conviction: +5, size: round((0.07-0.05)*100)=2, scenario EV: 0.4*15+0.4*5+0.2*(-10)=6, mod=min(8,12)=8
    # Wait: scenario_ev = 0.4*15 + 0.4*5 + 0.2*(-10) = 6+2-2 = 6, mod = round(6*2) = 12 → clamped to 8
    # Total: 65+5+2+8 = 80
    assert score == 80


def test_trader_verdict_score_none_when_missing():
    scorer = AeternusScorer(MockLLM())
    state = {"market_report": "Test"}
    assert scorer._extract_trader_verdict_score(state) is None


def test_risk_verdict_score():
    scorer = AeternusScorer(MockLLM())
    state = {
        "market_report": "Test",
        "structured_verdict": {
            "decision": "BUY",
            "conviction": 4,
            "hedge_directive": "NO_CHANGE",
            "max_position_pct": 0.07,
            "drawdown_mode": False,
            "dissent_records": [],
        },
    }
    score = scorer._extract_risk_verdict_score(state)
    # 65 + 5 + 0 + 0 + 0 + round((0.07-0.05)*60)=1 = 71
    assert score == 71


def test_risk_verdict_score_bearish():
    scorer = AeternusScorer(MockLLM())
    state = {
        "market_report": "Test",
        "structured_verdict": {
            "decision": "HOLD",
            "conviction": 2,
            "hedge_directive": "INCREASE_HEDGE",
            "max_position_pct": 0.03,
            "drawdown_mode": True,
            "dissent_records": [
                {"dissent_strength": 3},
                {"dissent_strength": 3},
            ],
        },
    }
    score = scorer._extract_risk_verdict_score(state)
    # 50 + (-5) + (-5) + (-3-3=-6) + (-8) + round((0.03-0.05)*60)=-1 = 25
    assert score == 25


def test_ensemble_blend_with_debate_voices():
    """When debate voices present, ensemble score differs from quant-only."""
    scorer = AeternusScorer(MockLLM())
    state = {
        "market_report": "Test",
        "investment_debate_state": {
            "judge_decision": "Decision: SELL | Conviction: 5/5 | Bull Strength: 1/5 | Bear Strength: 5/5"
        },
        "structured_trader_verdict": {
            "decision": "SELL",
            "conviction": 5,
            "position_size_pct": 0.02,
            "scenarios": [],
        },
        "structured_verdict": {
            "decision": "SELL",
            "conviction": 5,
            "hedge_directive": "INCREASE_HEDGE",
            "max_position_pct": 0.02,
            "drawdown_mode": False,
            "dissent_records": [],
        },
    }
    rating = scorer.score(state)
    # All debate voices say SELL — score should be lower than quant-only
    assert rating["ensemble_model_scores"]["research_debate"] is not None
    assert rating["ensemble_model_scores"]["trader_verdict"] is not None
    assert rating["ensemble_model_scores"]["risk_verdict"] is not None
    assert rating["aeternus_score"] < rating["quant_only_score"]
    assert rating["ensemble_weights"] is not None
    assert abs(sum(rating["ensemble_weights"].values()) - 1.0) < 1e-4
