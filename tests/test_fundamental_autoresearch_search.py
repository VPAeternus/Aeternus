from tradingagents.research.fundamental_autoresearch.search import run_constrained_search


def test_run_constrained_search_returns_ranked_weighted_results():
    rows = [
        {
            "ticker": "AAPL",
            "effective_market_date": "2026-01-30",
            "sector": "Technology",
            "revenue_growth_yoy_pct": 12.0,
            "fcf_growth_yoy_pct": 10.0,
            "share_count_change_pct": -1.0,
            "equity_change_pct": 6.0,
            "gross_margin": 0.46,
            "operating_margin": 0.30,
            "debt_to_equity": 1.0,
            "current_ratio": 1.1,
            "ev_to_sales": 6.0,
            "earnings_yield": 0.04,
            "data_coverage_score": 0.9,
            "return_60d": 0.10,
        },
        {
            "ticker": "MSFT",
            "effective_market_date": "2026-01-30",
            "sector": "Technology",
            "revenue_growth_yoy_pct": 8.0,
            "fcf_growth_yoy_pct": 7.0,
            "share_count_change_pct": -0.5,
            "equity_change_pct": 5.0,
            "gross_margin": 0.42,
            "operating_margin": 0.27,
            "debt_to_equity": 0.9,
            "current_ratio": 1.2,
            "ev_to_sales": 5.5,
            "earnings_yield": 0.038,
            "data_coverage_score": 0.9,
            "return_60d": 0.08,
        },
        {
            "ticker": "XOM",
            "effective_market_date": "2026-01-30",
            "sector": "Energy",
            "revenue_growth_yoy_pct": 2.0,
            "fcf_growth_yoy_pct": 3.0,
            "share_count_change_pct": -0.8,
            "equity_change_pct": 2.0,
            "gross_margin": 0.22,
            "operating_margin": 0.12,
            "debt_to_equity": 0.6,
            "current_ratio": 1.0,
            "ev_to_sales": 3.0,
            "earnings_yield": 0.06,
            "data_coverage_score": 0.9,
            "return_60d": 0.03,
        },
        {
            "ticker": "CVX",
            "effective_market_date": "2026-01-30",
            "sector": "Energy",
            "revenue_growth_yoy_pct": 1.0,
            "fcf_growth_yoy_pct": 1.0,
            "share_count_change_pct": 0.5,
            "equity_change_pct": 1.0,
            "gross_margin": 0.18,
            "operating_margin": 0.09,
            "debt_to_equity": 0.7,
            "current_ratio": 0.95,
            "ev_to_sales": 3.4,
            "earnings_yield": 0.05,
            "data_coverage_score": 0.9,
            "return_60d": 0.01,
        },
    ]

    results = run_constrained_search(rows, dataset_name="sec_large_cap_v1")

    assert results
    assert results[0]["primary_metric_value"] >= results[-1]["primary_metric_value"]
    assert abs(sum(abs(weight) for weight in results[0]["weights"].values()) - 1.0) < 1e-9
    assert any(any(value < 0 for value in row["weights"].values()) for row in results)
    assert any(row["weights"]["capital_discipline"] > 0 for row in results)


def test_run_constrained_search_can_emit_capital_discipline_weighted_strategies():
    rows = [
        {
            "ticker": "AAPL",
            "effective_market_date": "2026-01-30",
            "sector": "Technology",
            "revenue_growth_yoy_pct": 12.0,
            "fcf_growth_yoy_pct": 10.0,
            "share_count_change_pct": -1.0,
            "equity_change_pct": 6.0,
            "gross_margin": 0.46,
            "operating_margin": 0.30,
            "debt_to_equity": 1.0,
            "current_ratio": 1.1,
            "ev_to_sales": 6.0,
            "earnings_yield": 0.04,
            "data_coverage_score": 0.9,
            "return_60d": 0.10,
        },
        {
            "ticker": "MSFT",
            "effective_market_date": "2026-01-30",
            "sector": "Technology",
            "revenue_growth_yoy_pct": 8.0,
            "fcf_growth_yoy_pct": 7.0,
            "share_count_change_pct": -0.5,
            "equity_change_pct": 5.0,
            "gross_margin": 0.42,
            "operating_margin": 0.27,
            "debt_to_equity": 0.9,
            "current_ratio": 1.2,
            "ev_to_sales": 5.5,
            "earnings_yield": 0.038,
            "data_coverage_score": 0.9,
            "return_60d": 0.08,
        },
    ]

    results = run_constrained_search(rows, dataset_name="sec_large_cap_v1")

    capital_rows = [row for row in results if row["weights"]["capital_discipline"] > 0]
    assert capital_rows
    assert any("capital_discipline_" in row["strategy"] for row in capital_rows)
    for row in capital_rows:
        assert row["weights"]["health"] >= row["weights"]["capital_discipline"]
