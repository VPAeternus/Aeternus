from tradingagents.research.fundamental_autoresearch.evaluate import (
    compare_baseline_strategies,
    evaluate_scored_rows,
)


def test_evaluate_scored_rows_reports_sector_neutral_primary_metric_and_coverage():
    rows = [
        {"ticker": "AAPL", "sector": "Technology", "fundamental_score": 90, "return_20d": 0.04, "return_60d": 0.10, "return_120d": 0.12, "return_252d": 0.18},
        {"ticker": "MSFT", "sector": "Technology", "fundamental_score": 80, "return_20d": 0.03, "return_60d": 0.08, "return_120d": 0.10, "return_252d": 0.15},
        {"ticker": "XOM", "sector": "Energy", "fundamental_score": 70, "return_20d": 0.02, "return_60d": 0.05, "return_120d": 0.06, "return_252d": 0.09},
        {"ticker": "CVX", "sector": "Energy", "fundamental_score": 60, "return_20d": 0.01, "return_60d": 0.03, "return_120d": 0.04, "return_252d": 0.06},
    ]

    summary = evaluate_scored_rows(rows, dataset_name="sec_large_cap_v1", score_version="baseline_v1")

    assert summary.dataset_name == "sec_large_cap_v1"
    assert summary.score_version == "baseline_v1"
    assert summary.primary_metric_name == "rank_ic_60d_sector_neutral"
    assert summary.primary_metric_value > 0
    assert summary.coverage_ratio == 1.0
    assert summary.observations == 4


def test_evaluate_scored_rows_handles_partial_forward_return_coverage():
    rows = [
        {"ticker": "AAPL", "sector": "Technology", "fundamental_score": 90, "return_60d": 0.10},
        {"ticker": "MSFT", "sector": "Technology", "fundamental_score": 80, "return_60d": None},
    ]

    summary = evaluate_scored_rows(rows, dataset_name="sec_large_cap_v1", score_version="baseline_v1")

    assert summary.coverage_ratio == 0.5
    assert summary.observations == 1


def test_compare_baseline_strategies_returns_ranked_results():
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

    results = compare_baseline_strategies(rows, dataset_name="sec_large_cap_v1")

    assert results
    assert results[0]["primary_metric_value"] >= results[-1]["primary_metric_value"]
    assert "baseline_v1" in {row["strategy"] for row in results}
    assert "growth_only" in {row["strategy"] for row in results}
    assert "growth_only_inverted" in {row["strategy"] for row in results}
    assert "quality_only_inverted" in {row["strategy"] for row in results}
