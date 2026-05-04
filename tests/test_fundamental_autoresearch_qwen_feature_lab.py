from tradingagents.research.fundamental_autoresearch.qwen_feature_lab import (
    expand_qwen_feature_lab_components,
    QwenFeatureLabError,
    normalize_qwen_feature_lab_proposal,
    run_qwen_feature_lab,
)


def _sample_rows():
    return [
        {
            "ticker": "AAPL",
            "effective_market_date": "2026-01-30",
            "sector": "Technology",
            "revenue_growth_yoy_pct": 12.0,
            "fcf_growth_yoy_pct": 10.0,
            "revenue_growth_acceleration_pct": 4.0,
            "fcf_growth_acceleration_pct": 3.0,
            "share_count_change_pct": -1.0,
            "equity_change_pct": 6.0,
            "gross_margin": 0.46,
            "operating_margin": 0.30,
            "margin_change_pct": 1.2,
            "debt_to_equity": 1.0,
            "current_ratio": 1.1,
            "ev_to_sales": 6.0,
            "earnings_yield": 0.04,
            "quality_valuation_tension": 1.5,
            "liquidity_stress_score": 0.3,
            "leverage_stress_score": 0.2,
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
            "revenue_growth_acceleration_pct": 1.0,
            "fcf_growth_acceleration_pct": 1.0,
            "share_count_change_pct": -0.5,
            "equity_change_pct": 5.0,
            "gross_margin": 0.42,
            "operating_margin": 0.27,
            "margin_change_pct": 0.4,
            "debt_to_equity": 0.9,
            "current_ratio": 1.2,
            "ev_to_sales": 5.5,
            "earnings_yield": 0.038,
            "quality_valuation_tension": 1.0,
            "liquidity_stress_score": 0.2,
            "leverage_stress_score": 0.2,
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
            "revenue_growth_acceleration_pct": -1.0,
            "fcf_growth_acceleration_pct": -0.5,
            "share_count_change_pct": -0.8,
            "equity_change_pct": 2.0,
            "gross_margin": 0.22,
            "operating_margin": 0.12,
            "margin_change_pct": 0.2,
            "debt_to_equity": 0.6,
            "current_ratio": 1.0,
            "ev_to_sales": 3.0,
            "earnings_yield": 0.06,
            "quality_valuation_tension": 0.5,
            "liquidity_stress_score": 0.1,
            "leverage_stress_score": 0.1,
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
            "revenue_growth_acceleration_pct": -2.0,
            "fcf_growth_acceleration_pct": -1.0,
            "share_count_change_pct": 0.5,
            "equity_change_pct": 1.0,
            "gross_margin": 0.18,
            "operating_margin": 0.09,
            "margin_change_pct": -0.2,
            "debt_to_equity": 0.7,
            "current_ratio": 0.95,
            "ev_to_sales": 3.4,
            "earnings_yield": 0.05,
            "quality_valuation_tension": 0.4,
            "liquidity_stress_score": 0.2,
            "leverage_stress_score": 0.1,
            "data_coverage_score": 0.9,
            "return_20d": 0.01,
            "return_60d": 0.01,
            "return_120d": 0.02,
            "return_252d": 0.03,
        },
    ]


def test_normalize_qwen_feature_lab_proposal_extracts_component_combo():
    normalized = normalize_qwen_feature_lab_proposal(
        {
            "components": [
                "growth_acceleration",
                "margin_expansion",
            ]
        }
    )

    assert normalized == ("growth_acceleration", "margin_expansion")


def test_expand_qwen_feature_lab_components_returns_valid_weight_sets():
    configs = expand_qwen_feature_lab_components(
        ("growth_acceleration", "margin_expansion")
    )

    assert configs
    for normalized in configs:
        assert normalized["health"] > 0
        assert normalized["growth"] < 0
        assert normalized["quality"] < 0
        assert normalized["growth_acceleration"] >= 0
        assert normalized["margin_expansion"] >= 0
        absolute_sum = sum(abs(value) for value in normalized.values())
        assert round(absolute_sum, 6) == 1.0


def test_run_qwen_feature_lab_scores_valid_proposals(monkeypatch):
    def _fake_request(**kwargs):
        return {
            "model": "qwen-test",
            "raw_content": "{}",
            "proposals": [
                {
                    "components": [
                        "growth_acceleration",
                        "margin_expansion",
                    ],
                },
                {
                    "components": [
                        "quality_tension_inverse",
                        "balance_sheet_resilience",
                    ],
                },
                {
                    "components": [],
                },
            ],
        }

    monkeypatch.setattr(
        "tradingagents.research.fundamental_autoresearch.qwen_feature_lab.request_qwen_feature_lab_proposals",
        _fake_request,
    )

    result = run_qwen_feature_lab(
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


def test_run_qwen_feature_lab_raises_when_no_valid_proposals(monkeypatch):
    def _fake_request(**kwargs):
        return {
            "model": "qwen-test",
            "raw_content": "{}",
            "proposals": [
                {
                    "components": [],
                },
            ],
        }

    monkeypatch.setattr(
        "tradingagents.research.fundamental_autoresearch.qwen_feature_lab.request_qwen_feature_lab_proposals",
        _fake_request,
    )

    try:
        run_qwen_feature_lab(
            _sample_rows(),
            dataset_name="sec_large_cap_v1",
            base_url="http://127.0.0.1:8090/v1",
            model="mlx-qwen-test",
            proposal_count=1,
        )
    except QwenFeatureLabError as exc:
        assert "No valid Qwen feature-lab proposals" in str(exc)
    else:
        raise AssertionError("Expected QwenFeatureLabError")
