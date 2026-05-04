from tradingagents.dealflow.themes import infer_trend_tags, is_structural_growth_theme


def test_infer_trend_tags_adds_ai_theme_cluster():
    tags = infer_trend_tags(
        subscores={
            "price_momentum": 78.0,
            "cashtag_momentum": 74.0,
            "social_momentum": 70.0,
            "news_catalyst": 62.0,
        },
        symbol="NVDA",
        sector="Technology",
        asset_class="Equity",
    )
    assert "theme-ai-infrastructure" in tags
    assert "theme-structural-growth" in tags


def test_structural_growth_theme_detector():
    assert is_structural_growth_theme(["theme-ai-infrastructure", "theme-structural-growth"]) is True
    assert is_structural_growth_theme(["balanced"]) is False

