from tradingagents.research.fundamental_autoresearch.score import score_feature_row


def test_score_feature_row_returns_stable_subscores_and_total():
    features = {
        "ticker": "AAPL",
        "effective_market_date": "2026-01-30",
        "revenue_growth_yoy_pct": 8.5,
        "fcf_growth_yoy_pct": 11.0,
        "share_count_change_pct": -1.5,
        "equity_change_pct": 6.0,
        "gross_margin": 0.47,
        "operating_margin": 0.31,
        "debt_to_equity": 1.25,
        "current_ratio": 1.10,
        "ev_to_sales": 6.2,
        "earnings_yield": 0.045,
        "data_coverage_score": 0.92,
    }

    result = score_feature_row(features)

    assert result.ticker == "AAPL"
    assert result.score_version == "baseline_v1"
    assert result.fundamental_score > 0
    assert result.growth_score > 0
    assert result.quality_score > 0
    assert result.health_score > 0
    assert result.capital_discipline_score > 0
    assert result.valuation_score > 0


def test_score_feature_row_penalizes_sparse_inputs():
    rich_result = score_feature_row(
        {
            "ticker": "AAPL",
            "effective_market_date": "2026-01-30",
            "revenue_growth_yoy_pct": 8.5,
            "fcf_growth_yoy_pct": 11.0,
            "share_count_change_pct": -1.5,
            "equity_change_pct": 6.0,
            "gross_margin": 0.47,
            "operating_margin": 0.31,
            "debt_to_equity": 1.25,
            "current_ratio": 1.10,
            "ev_to_sales": 6.2,
            "earnings_yield": 0.045,
            "data_coverage_score": 0.92,
        }
    )
    sparse_result = score_feature_row(
        {
            "ticker": "AAPL",
            "effective_market_date": "2026-01-30",
            "revenue_growth_yoy_pct": None,
            "fcf_growth_yoy_pct": None,
            "share_count_change_pct": None,
            "equity_change_pct": None,
            "gross_margin": None,
            "operating_margin": None,
            "debt_to_equity": None,
            "current_ratio": None,
            "ev_to_sales": None,
            "earnings_yield": None,
            "data_coverage_score": 0.05,
        }
    )

    assert sparse_result.fundamental_score < rich_result.fundamental_score


def test_score_feature_row_supports_named_baseline_strategies():
    features = {
        "ticker": "AAPL",
        "effective_market_date": "2026-01-30",
        "revenue_growth_yoy_pct": 8.5,
        "fcf_growth_yoy_pct": 11.0,
        "share_count_change_pct": -1.5,
        "equity_change_pct": 6.0,
        "gross_margin": 0.47,
        "operating_margin": 0.31,
        "debt_to_equity": 1.25,
        "current_ratio": 1.10,
        "ev_to_sales": 6.2,
        "earnings_yield": 0.045,
        "data_coverage_score": 0.92,
    }

    baseline = score_feature_row(features, strategy="baseline_v1")
    growth = score_feature_row(features, strategy="growth_only")
    quality = score_feature_row(features, strategy="quality_only")
    inverted_growth = score_feature_row(features, strategy="growth_only_inverted")
    inverted_quality = score_feature_row(features, strategy="quality_only_inverted")

    assert baseline.score_version == "baseline_v1"
    assert growth.score_version == "growth_only"
    assert quality.score_version == "quality_only"
    assert inverted_growth.score_version == "growth_only_inverted"
    assert inverted_quality.score_version == "quality_only_inverted"
    assert growth.fundamental_score != quality.fundamental_score
    assert inverted_growth.fundamental_score < growth.fundamental_score
    expected_total = round((0.5 + (0.5 * features["data_coverage_score"])) * 100.0, 4)
    assert round(growth.fundamental_score + inverted_growth.fundamental_score, 4) == expected_total
    assert round(quality.fundamental_score + inverted_quality.fundamental_score, 4) == expected_total


def test_score_feature_row_uses_acceleration_tension_and_stress_features():
    base_features = {
        "ticker": "AAPL",
        "effective_market_date": "2026-01-30",
        "revenue_growth_yoy_pct": 8.5,
        "fcf_growth_yoy_pct": 11.0,
        "revenue_growth_acceleration_pct": 1.0,
        "fcf_growth_acceleration_pct": 1.0,
        "share_count_change_pct": -1.5,
        "equity_change_pct": 6.0,
        "gross_margin": 0.47,
        "operating_margin": 0.31,
        "margin_change_pct": 0.5,
        "quality_valuation_tension": 1.0,
        "debt_to_equity": 1.25,
        "current_ratio": 1.10,
        "liquidity_stress_score": 0.2,
        "leverage_stress_score": 0.4,
        "ev_to_sales": 6.2,
        "earnings_yield": 0.045,
        "data_coverage_score": 0.92,
    }
    stressed_features = {
        **base_features,
        "revenue_growth_acceleration_pct": -8.0,
        "fcf_growth_acceleration_pct": -6.0,
        "quality_valuation_tension": 4.5,
        "margin_change_pct": -2.0,
        "liquidity_stress_score": 1.6,
        "leverage_stress_score": 1.8,
    }

    base_result = score_feature_row(base_features)
    stressed_result = score_feature_row(stressed_features)

    assert base_result.growth_score > stressed_result.growth_score
    assert base_result.quality_score > stressed_result.quality_score
    assert base_result.health_score > stressed_result.health_score
