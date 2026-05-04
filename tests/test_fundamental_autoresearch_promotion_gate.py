from tradingagents.research.fundamental_autoresearch.promotion_gate import evaluate_promotion_gate


def test_promotion_gate_passes_when_thresholds_are_met():
    result = evaluate_promotion_gate(
        {
            "strategy": "health_0p5__inv_growth_0p1__inv_quality_0p4",
            "primary_metric_name": "rank_ic_60d_sector_neutral",
            "primary_metric_value": 0.087029,
            "coverage_ratio": 0.99,
            "observations": 1588,
        },
        robustness={
            "by_horizon": {
                "20d": {"primary_metric_value": 0.056397},
                "60d": {"primary_metric_value": 0.087029},
                "120d": {"primary_metric_value": 0.092488},
            },
            "by_era": {
                "2010_2019": {"primary_metric_value": 0.048837, "observations": 500},
                "2020_2026": {"primary_metric_value": 0.094574, "observations": 1000},
            },
            "by_sector": {
                "Technology": {"primary_metric_value": 0.119599, "observations": 400},
                "Financials": {"primary_metric_value": 0.111963, "observations": 200},
                "Healthcare": {"primary_metric_value": 0.035696, "observations": 200},
            },
        },
    )

    assert result["gate_status"] == "PASSED"
    assert result["recommended_status"] == "shadow"
    assert result["failed_checks"] == []


def test_promotion_gate_fails_on_low_coverage():
    result = evaluate_promotion_gate(
        {
            "strategy": "weak_coverage",
            "primary_metric_name": "rank_ic_60d_sector_neutral",
            "primary_metric_value": 0.09,
            "coverage_ratio": 0.42,
            "observations": 120,
        },
        robustness={
            "by_horizon": {
                "20d": {"primary_metric_value": 0.03},
                "60d": {"primary_metric_value": 0.09},
                "120d": {"primary_metric_value": 0.10},
            },
            "by_era": {
                "2020_2026": {"primary_metric_value": 0.09, "observations": 120},
            },
            "by_sector": {
                "Technology": {"primary_metric_value": 0.09, "observations": 120},
            },
        },
    )

    assert result["gate_status"] == "FAILED"
    assert "coverage_ratio" in result["failed_checks"]
