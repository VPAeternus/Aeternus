"""Tests for the 3-tier content generation pipeline."""
import json
import os
from pathlib import Path

import pytest


def _sample_report():
    """Build a minimal but complete analysis_report dict for testing."""
    return {
        "company_of_interest": "TEST",
        "trade_date": "2026-01-15",
        "fundamentals_report": "TEST has strong fundamentals with revenue growth of 20% and improving margins. The Piotroski F-Score is 7 out of 9.",
        "market_report": "TEST is in an ABOVE_200_BELOW_50 regime with bullish momentum acceleration.",
        "sentiment_report": "Sentiment is neutral with limited social media coverage.",
        "news_report": "No major catalysts identified in the near term.",
        "legacy_removed_state": {
            "bull_history": "The bull case rests on exceptional earnings growth of 25% YoY and expanding margins. The balance sheet is fortress-grade with zero debt. Revenue acceleration is confirmed across all segments.",
            "bear_history": "The bear case highlights elevated valuation at 35x forward P/E with macro headwinds from rising rates. Insider selling has increased in recent quarters.",
            "history": "Both sides agree on fundamental quality. The discussion centers on whether the premium valuation is justified given macro uncertainty.",
            "judge_decision": "VERDICT: TEST is a BUY at current levels on a 6-12 month horizon. The earnings growth of 25% justifies the premium multiple. Conviction 3/5.",
            "current_response": "",
        },
        "legacy_removed_state": {
            "risky_history": "Aggressive view: position at 6-8% given strong fundamentals.",
            "safe_history": "Conservative view: cap at 3% due to valuation risk.",
            "neutral_history": "Balanced view: 4-5% is appropriate with stop below 200-day MA.",
            "history": "",
            "judge_decision": "RISK VERDICT: A 4-5% initial position is appropriate given the risk/reward profile.",
        },
        "trader_investment_decision": "Initiate LONG position in TEST.",
        "investment_plan": "Entry at 4%, scale to 6% on confirmation.",
        "final_trade_decision": "BUY — Conviction 3/5. Strong earnings growth justifies premium. Stop below 200-day MA.",
        "structured_trader_verdict": {
            "decision": "BUY",
            "conviction": 3,
            "reasoning": "Strong fundamentals with earnings growth of 25%.",
            "invalidation_conditions": [
                {"condition": "Daily close below 200-day MA", "price_level": None},
                {"condition": "Earnings growth drops below 10%", "price_level": None},
            ],
            "scenarios": [
                {"name": "bull", "probability": 0.4, "outcome": "Stock rises 25% on earnings acceleration."},
                {"name": "base", "probability": 0.35, "outcome": "Sideways for 60 days then moderate gains."},
                {"name": "bear", "probability": 0.25, "outcome": "Multiple compression to 28x on rate fears."},
            ],
            "milestones": [],
            "position_size_pct": 0.04,
        },
        "fundamental_metrics": {},
        "sentiment_metrics": {},
        "macro_metrics": {},
        "momentum_metrics": {},
        "aeternus_score": {
            "rating_id": "test-id-123",
            "ticker": "TEST",
            "date": "2026-01-15",
            "aeternus_score": 65.5,
            "rating": "Buy",
            "confidence": 4,
            "breakdown": {
                "fundamental": 78,
                "coherence": 60,
                "macro": 55,
                "sentiment": 50,
                "momentum": 58,
            },
            "regime_weights": {
                "fundamental": 0.30,
                "coherence": 0.25,
                "macro": 0.20,
                "sentiment": 0.15,
                "momentum": 0.10,
            },
            "weight_regime": "NEUTRAL",
            "alpha_decomposition": {
                "factor_predicted": 52.0,
                "alpha_residual": 13.5,
                "interpretation": "Significant alpha",
                "factor_source": "fama_french",
            },
            "fundamental_sub": {"quality": 80, "growth": 75, "health": 85, "valuation": 65},
            "sentiment_sub": {"polarity": 55, "buzz": 40, "catalyst": 30},
            "macro_sub": {"regime_fit": 55, "monetary_stress": 60, "rate_headwind": 50, "commodity_cycle": 52},
            "momentum_sub": {"trend_strength": 65, "momentum_health": 40, "regime_quality": 70, "volume_confirmation": 55},
            "coherence_sub": {"directional_alignment": 70, "conviction_strength": 50, "interaction_patterns": 60, "narrative_stability": 55},
            "options_sub": None,
            "flow_toxicity_sub": None,
            "epistemic_summary": {"overall_confidence": "MEDIUM", "weakest_pillar": "sentiment"},
        },
        "dealflow_context": {},
        "messages": [],
    }


class TestGenerateHookPost:
    def test_under_280_chars(self):
        from tradingagents.graph.content_posts import generate_hook_post
        report = _sample_report()
        post = generate_hook_post(report)
        assert len(post) <= 280, f"Hook post is {len(post)} chars, should be <=280"

    def test_contains_ticker(self):
        from tradingagents.graph.content_posts import generate_hook_post
        report = _sample_report()
        post = generate_hook_post(report)
        assert "$TEST" in post

    def test_contains_decision(self):
        from tradingagents.graph.content_posts import generate_hook_post
        report = _sample_report()
        post = generate_hook_post(report)
        assert "BUY" in post

    def test_contains_score(self):
        from tradingagents.graph.content_posts import generate_hook_post
        report = _sample_report()
        post = generate_hook_post(report)
        assert "65.50" in post

    def test_ends_with_analysis_to_follow(self):
        from tradingagents.graph.content_posts import generate_hook_post
        report = _sample_report()
        post = generate_hook_post(report)
        assert post.strip().endswith("Analysis to follow.")

    def test_contains_alpha(self):
        from tradingagents.graph.content_posts import generate_hook_post
        report = _sample_report()
        post = generate_hook_post(report)
        assert "Alpha" in post


class TestGenerateAnalysisPost:
    def test_contains_bull_bear(self):
        from tradingagents.graph.content_posts import generate_analysis_post
        report = _sample_report()
        post = generate_analysis_post(report)
        assert "THE CASE FOR:" in post
        assert "THE CASE AGAINST:" in post

    def test_contains_pillar_scores(self):
        from tradingagents.graph.content_posts import generate_analysis_post
        report = _sample_report()
        post = generate_analysis_post(report)
        assert "Fundamental" in post
        assert "Coherence" in post

    def test_ends_with_cta(self):
        from tradingagents.graph.content_posts import generate_analysis_post
        report = _sample_report()
        post = generate_analysis_post(report)
        assert "Here is the article and full analysis if anyone wants details." in post

    def test_contains_rating(self):
        from tradingagents.graph.content_posts import generate_analysis_post
        report = _sample_report()
        post = generate_analysis_post(report)
        assert "Buy" in post
        assert "65.50" in post


class TestGenerateArticle:
    def test_has_all_sections(self):
        from tradingagents.graph.content_posts import generate_article
        report = _sample_report()
        article = generate_article(report)
        assert "## Fundamental Analysis" in article
        assert "## Technical & Momentum Analysis" in article
        assert "## Sentiment & Social Analysis" in article
        assert "## The Bull Case" in article
        assert "## The Bear Case" in article
        assert "## Risk Assessment" in article
        assert "## Score Breakdown" in article

    def test_has_scenarios_table(self):
        from tradingagents.graph.content_posts import generate_article
        report = _sample_report()
        article = generate_article(report)
        assert "## Scenarios" in article
        assert "Bull" in article
        assert "40%" in article

    def test_has_invalidation(self):
        from tradingagents.graph.content_posts import generate_article
        report = _sample_report()
        article = generate_article(report)
        assert "## What Would Change This View" in article
        assert "200-day MA" in article

    def test_has_disclaimer(self):
        from tradingagents.graph.content_posts import generate_article
        report = _sample_report()
        article = generate_article(report)
        assert "not financial advice" in article.lower()

    def test_word_count_reasonable(self):
        from tradingagents.graph.content_posts import generate_article
        report = _sample_report()
        article = generate_article(report)
        word_count = len(article.split())
        assert word_count >= 200, f"Article too short: {word_count} words"


class TestGenerateAllPosts:
    def test_saves_files(self, tmp_path, monkeypatch):
        from tradingagents.graph.content_posts import generate_all_posts
        monkeypatch.chdir(tmp_path)
        report = _sample_report()
        result = generate_all_posts("TEST", "2026-01-15", report=report)

        assert "hook" in result
        assert "analysis" in result
        assert "article" in result
        assert "paths" in result

        # Verify files exist
        for key in ("hook", "analysis", "article"):
            path = Path(result["paths"][key])
            assert path.exists(), f"{key} file not created at {path}"

    def test_hook_file_content_matches(self, tmp_path, monkeypatch):
        from tradingagents.graph.content_posts import generate_all_posts
        monkeypatch.chdir(tmp_path)
        report = _sample_report()
        result = generate_all_posts("TEST", "2026-01-15", report=report)

        hook_content = Path(result["paths"]["hook"]).read_text()
        assert hook_content == result["hook"]

    def test_directory_structure(self, tmp_path, monkeypatch):
        from tradingagents.graph.content_posts import generate_all_posts
        monkeypatch.chdir(tmp_path)
        report = _sample_report()
        generate_all_posts("TEST", "2026-01-15", report=report)

        posts_dir = tmp_path / "results" / "TEST" / "2026-01-15" / "posts"
        assert posts_dir.exists()
        assert (posts_dir / "post_1_hook.txt").exists()
        assert (posts_dir / "post_2_analysis.txt").exists()
        assert (posts_dir / "post_3_article.md").exists()

    def test_loads_from_disk(self, tmp_path, monkeypatch):
        from tradingagents.graph.content_posts import generate_all_posts
        monkeypatch.chdir(tmp_path)
        report = _sample_report()

        # Write report to expected location
        report_dir = tmp_path / "results" / "TEST" / "2026-01-15"
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "analysis_report.json").write_text(json.dumps(report))

        # Call without providing report — should load from disk
        result = generate_all_posts("TEST", "2026-01-15")
        assert "$TEST" in result["hook"]
        assert "BUY" in result["hook"]


class TestHelpers:
    def test_first_sentence(self):
        from tradingagents.graph.content_posts import _first_sentence
        assert _first_sentence("Hello world. More text.") == "Hello world."
        assert _first_sentence("Single sentence") == "Single sentence"
        assert _first_sentence("") == ""

    def test_trim_to_words(self):
        from tradingagents.graph.content_posts import _trim_to_words
        text = "Word " * 200
        result = _trim_to_words(text, 50)
        assert len(result.split()) <= 51  # Allow for partial word

    def test_safe_get(self):
        from tradingagents.graph.content_posts import _safe_get
        d = {"a": {"b": {"c": 42}}}
        assert _safe_get(d, "a", "b", "c") == 42
        assert _safe_get(d, "a", "x", default="nope") == "nope"
        assert _safe_get(None, "a", default="nope") == "nope"
