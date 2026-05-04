from tradingagents.research.fundamental_autoresearch.robustness import evaluate_strategy_robustness


def test_evaluate_strategy_robustness_reports_horizon_era_and_sector_slices():
    rows = [
        {
            "ticker": "AAPL",
            "effective_market_date": "2012-01-30",
            "sector": "Technology",
            "fundamental_score": 90,
            "return_20d": 0.05,
            "return_60d": 0.10,
            "return_120d": 0.15,
            "return_252d": 0.20,
        },
        {
            "ticker": "MSFT",
            "effective_market_date": "2013-01-30",
            "sector": "Technology",
            "fundamental_score": 80,
            "return_20d": 0.03,
            "return_60d": 0.08,
            "return_120d": 0.10,
            "return_252d": 0.14,
        },
        {
            "ticker": "XOM",
            "effective_market_date": "2023-01-30",
            "sector": "Energy",
            "fundamental_score": 70,
            "return_20d": 0.01,
            "return_60d": 0.03,
            "return_120d": 0.04,
            "return_252d": 0.06,
        },
        {
            "ticker": "CVX",
            "effective_market_date": "2024-01-30",
            "sector": "Energy",
            "fundamental_score": 60,
            "return_20d": 0.00,
            "return_60d": 0.01,
            "return_120d": 0.02,
            "return_252d": 0.03,
        },
    ]

    payload = evaluate_strategy_robustness(
        rows,
        strategy="health_0p5__inv_growth_0p1__inv_quality_0p4",
    )

    assert payload["strategy"] == "health_0p5__inv_growth_0p1__inv_quality_0p4"
    assert "20d" in payload["by_horizon"]
    assert "60d" in payload["by_horizon"]
    assert "2010_2019" in payload["by_era"]
    assert "2020_2026" in payload["by_era"]
    assert "Technology" in payload["by_sector"]
    assert "Energy" in payload["by_sector"]
