from tradingagents.research.fundamental_autoresearch.qwen_autoresearch import (
    QwenAutoresearchError,
    normalize_qwen_weight_proposal,
    run_qwen_autoresearch,
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


def test_normalize_qwen_weight_proposal_enforces_signs_and_absolute_sum():
    normalized = normalize_qwen_weight_proposal(
        {
            "health": 0.9,
            "growth": 0.25,
            "quality": 0.5,
            "capital_discipline": -0.1,
            "valuation": -0.2,
        }
    )

    assert normalized is not None
    assert normalized["health"] > 0
    assert normalized["growth"] <= 0
    assert normalized["quality"] <= 0
    assert normalized["capital_discipline"] >= 0
    assert normalized["valuation"] >= 0
    absolute_sum = (
        normalized["health"]
        + abs(normalized["growth"])
        + abs(normalized["quality"])
        + normalized["capital_discipline"]
        + normalized["valuation"]
    )
    assert round(absolute_sum, 6) == 1.0
    assert normalized["health"] >= max(
        abs(normalized["growth"]),
        abs(normalized["quality"]),
        normalized["capital_discipline"],
        normalized["valuation"],
    )


def test_run_qwen_autoresearch_skips_invalid_proposals_and_ranks_valid_ones(monkeypatch):
    def _fake_request(**kwargs):
        return {
            "model": "qwen-test",
            "raw_content": "{}",
            "proposals": [
                {"health": 0.8, "growth": 0.1, "quality": 0.1},
                {"health": 0.6, "growth": 0.2, "quality": 0.1, "capital_discipline": 0.1},
                {"health": 0.2, "growth": 0.7, "quality": 0.1},
            ],
        }

    monkeypatch.setattr(
        "tradingagents.research.fundamental_autoresearch.qwen_autoresearch.request_qwen_weight_proposals",
        _fake_request,
    )

    result = run_qwen_autoresearch(
        _sample_rows(),
        dataset_name="sec_large_cap_v1",
        base_url="http://127.0.0.1:8090/v1",
        model="mlx-qwen-test",
        proposal_count=3,
    )

    assert result["proposal_count"] == 3
    assert result["accepted_count"] == 2
    assert result["rejected_count"] == 1
    assert len(result["leaderboard"]) == 2
    assert result["best_strategy"]["strategy"] == result["leaderboard"][0]["strategy"]
    assert result["leaderboard"][0]["primary_metric_value"] >= result["leaderboard"][1]["primary_metric_value"]


def test_run_qwen_autoresearch_raises_when_no_valid_proposals(monkeypatch):
    def _fake_request(**kwargs):
        return {
            "model": "qwen-test",
            "raw_content": "{}",
            "proposals": [
                {"health": 0.1, "growth": 0.8, "quality": 0.1},
            ],
        }

    monkeypatch.setattr(
        "tradingagents.research.fundamental_autoresearch.qwen_autoresearch.request_qwen_weight_proposals",
        _fake_request,
    )

    try:
        run_qwen_autoresearch(
            _sample_rows(),
            dataset_name="sec_large_cap_v1",
            base_url="http://127.0.0.1:8090/v1",
            model="mlx-qwen-test",
            proposal_count=1,
        )
    except QwenAutoresearchError as exc:
        assert "No valid Qwen proposals" in str(exc)
    else:
        raise AssertionError("Expected QwenAutoresearchError")
