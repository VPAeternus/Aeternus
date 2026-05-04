def test_build_research_conversion_integrity_report_groups_and_portfolio_conversion():
    from tradingagents.dealflow.research_conversion_integrity import (
        build_research_conversion_integrity_report,
    )

    batch_summary = {
        "requested": 4,
        "processed": 4,
        "include_unselected": True,
        "quick_unselected": True,
        "per_item_timeout_seconds": 420,
        "items": [
            {
                "symbol": "AAPL",
                "selected_for_deep": True,
                "analysis_mode": "DEEP",
                "status": "SUCCESS",
                "analysis_report_found": True,
                "aeternus_score": 71.2,
                "recommendation": "BUY",
                "realized_horizons": {"5d": 0.03},
            },
            {
                "symbol": "NVDA",
                "selected_for_deep": True,
                "analysis_mode": "DEEP",
                "status": "SUCCESS_CACHED",
                "analysis_report_found": True,
                "aeternus_score": 68.0,
                "recommendation": "BUY",
                "realized_horizons": {},
            },
            {
                "symbol": "PLTR",
                "selected_for_deep": False,
                "analysis_mode": "QUICK",
                "status": "SUCCESS_QUICK",
                "analysis_report_found": True,
                "aeternus_score": 62.0,
                "recommendation": "HOLD",
                "realized_horizons": {"5d": 0.01},
            },
            {
                "symbol": "AMD",
                "selected_for_deep": False,
                "analysis_mode": "QUICK",
                "status": "FAILED",
                "analysis_report_found": False,
                "aeternus_score": None,
                "recommendation": "UNKNOWN",
                "realized_horizons": {},
            },
        ],
    }
    plan = {
        "orders": [
            {"symbol": "AAPL"},
            {"symbol": "PLTR"},
        ]
    }

    report = build_research_conversion_integrity_report(
        as_of_date="2026-03-08",
        batch_summary=batch_summary,
        portfolio_plan=plan,
    )

    assert report["group_counts"]["deep_success"] == 1
    assert report["group_counts"]["deep_cached"] == 1
    assert report["group_counts"]["quick_success"] == 1
    assert report["group_counts"]["quick_failed"] == 1
    assert report["coverage_summary"]["portfolio_included_count"] == 2
    assert report["coverage_summary"]["analysis_report_found_count"] == 3
    assert report["coverage_summary"]["realized_horizon_count"] == 2

    by_symbol = {row["symbol"]: row for row in report["candidate_records"]}
    assert by_symbol["AAPL"]["integrity_group"] == "deep_success"
    assert by_symbol["NVDA"]["integrity_group"] == "deep_cached"
    assert by_symbol["PLTR"]["portfolio_included"] is True
    assert by_symbol["AMD"]["integrity_group"] == "quick_failed"

    deep_vs_quick = report["comparisons"]["deep_vs_quick"]
    assert deep_vs_quick["deep_count"] == 2
    assert deep_vs_quick["quick_count"] == 2
    assert deep_vs_quick["deep_usable_report_rate"] == 1.0
    assert deep_vs_quick["quick_portfolio_conversion_rate"] == 0.5
