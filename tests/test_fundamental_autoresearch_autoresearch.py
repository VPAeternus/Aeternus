import json

from tradingagents.research.fundamental_autoresearch.autoresearch import (
    build_signal_registry_rows,
)
from tradingagents.research.fundamental_autoresearch.autoresearch import (
    run_constrained_autoresearch,
)


def _sample_rows():
    return [
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
            "return_20d": 0.05,
            "return_60d": 0.10,
            "return_120d": 0.14,
            "return_252d": 0.20,
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
            "return_20d": 0.04,
            "return_60d": 0.08,
            "return_120d": 0.12,
            "return_252d": 0.16,
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
            "return_20d": 0.02,
            "return_60d": 0.03,
            "return_120d": 0.04,
            "return_252d": 0.06,
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
            "return_20d": 0.01,
            "return_60d": 0.01,
            "return_120d": 0.02,
            "return_252d": 0.03,
        },
    ]


def test_run_constrained_autoresearch_returns_ranked_leaderboard_and_best_strategy():
    experiment = run_constrained_autoresearch(
        _sample_rows(),
        dataset_name="sec_large_cap_v1",
        top_n=5,
        robustness_top_n=0,
    )

    assert experiment["strategy_count"] >= 5
    assert len(experiment["leaderboard"]) == 5
    assert experiment["best_strategy"]["strategy"] == experiment["leaderboard"][0]["strategy"]
    assert (
        experiment["leaderboard"][0]["primary_metric_value"]
        >= experiment["leaderboard"][-1]["primary_metric_value"]
    )
    assert experiment["top_robustness"] == {}


def test_run_constrained_autoresearch_can_include_top_strategy_robustness():
    experiment = run_constrained_autoresearch(
        _sample_rows(),
        dataset_name="sec_large_cap_v1",
        top_n=3,
        robustness_top_n=2,
    )

    assert len(experiment["leaderboard"]) == 3
    assert len(experiment["top_robustness"]) == 2
    assert set(experiment["top_robustness"]) == {
        row["strategy"] for row in experiment["leaderboard"][:2]
    }
    first_payload = experiment["top_robustness"][experiment["leaderboard"][0]["strategy"]]
    assert "by_horizon" in first_payload
    assert "60d" in first_payload["by_horizon"]


def test_run_constrained_autoresearch_keeps_health_dominant_when_capital_discipline_is_present():
    experiment = run_constrained_autoresearch(
        _sample_rows(),
        dataset_name="sec_large_cap_v1",
        top_n=10,
        robustness_top_n=0,
    )

    assert any(row["weights"]["capital_discipline"] > 0 for row in experiment["leaderboard"])
    for row in experiment["leaderboard"]:
        if row["weights"]["capital_discipline"] > 0:
            assert row["weights"]["health"] >= row["weights"]["capital_discipline"]


def test_run_constrained_autoresearch_can_surface_capital_discipline_strategies():
    experiment = run_constrained_autoresearch(
        _sample_rows(),
        dataset_name="sec_large_cap_v1",
        top_n=20,
        robustness_top_n=0,
    )

    capital_rows = [
        row for row in experiment["leaderboard"] if row["weights"]["capital_discipline"] > 0
    ]
    assert capital_rows
    assert any("capital_discipline_" in row["strategy"] for row in capital_rows)
    for row in capital_rows:
        assert row["weights"]["health"] >= row["weights"]["capital_discipline"]


def test_run_constrained_autoresearch_adds_gate_status_for_robust_rows(monkeypatch):
    def fake_run_constrained_search(rows, *, dataset_name):
        return [
            {
                "strategy": "winner",
                "weights": {"health": 0.5, "growth": -0.1, "quality": -0.4, "capital_discipline": 0.0, "valuation": 0.0},
                "primary_metric_name": "rank_ic_60d_sector_neutral",
                "primary_metric_value": 0.09,
                "coverage_ratio": 0.95,
                "observations": 1200,
            },
            {
                "strategy": "runner_up",
                "weights": {"health": 0.4, "growth": -0.1, "quality": -0.5, "capital_discipline": 0.0, "valuation": 0.0},
                "primary_metric_name": "rank_ic_60d_sector_neutral",
                "primary_metric_value": 0.08,
                "coverage_ratio": 0.95,
                "observations": 1200,
            },
        ]

    def fake_robustness(rows, *, strategy):
        return {
            "by_horizon": {
                "20d": {"primary_metric_value": 0.05},
                "60d": {"primary_metric_value": 0.09},
                "120d": {"primary_metric_value": 0.10},
            },
            "by_era": {
                "2010_2019": {"primary_metric_value": 0.04, "observations": 400},
                "2020_2026": {"primary_metric_value": 0.09, "observations": 800},
            },
            "by_sector": {
                "Technology": {"primary_metric_value": 0.12, "observations": 400},
                "Financials": {"primary_metric_value": 0.08, "observations": 300},
                "Healthcare": {"primary_metric_value": 0.03, "observations": 300},
            },
        }

    monkeypatch.setattr(
        "tradingagents.research.fundamental_autoresearch.autoresearch.run_constrained_search",
        fake_run_constrained_search,
    )
    monkeypatch.setattr(
        "tradingagents.research.fundamental_autoresearch.autoresearch.evaluate_strategy_robustness",
        fake_robustness,
    )

    experiment = run_constrained_autoresearch(
        _sample_rows(),
        dataset_name="sec_large_cap_v1",
        top_n=2,
        robustness_top_n=2,
    )

    assert experiment["leaderboard"][0]["gate_status"] == "PASSED"
    assert experiment["best_strategy"]["strategy"] == "winner"
    assert experiment["best_strategy"]["recommended_status"] == "shadow"
    assert experiment["registry_rows"][0]["strategy"] == "winner"


def test_build_signal_registry_rows_marks_missing_robustness_as_pending():
    rows = [
        {
            "strategy": "winner",
            "primary_metric_name": "rank_ic_60d_sector_neutral",
            "primary_metric_value": 0.09,
            "coverage_ratio": 0.95,
            "observations": 1200,
        }
    ]

    registry_rows = build_signal_registry_rows(rows, top_robustness={})

    assert registry_rows[0]["gate_status"] == "PENDING"
    assert registry_rows[0]["recommended_status"] == "candidate"
