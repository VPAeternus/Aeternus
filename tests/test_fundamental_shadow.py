from tradingagents.dealflow.fundamental_shadow import build_fundamental_shadow_report


def test_build_fundamental_shadow_report_tracks_shortlist_and_deep_overlap():
    report = build_fundamental_shadow_report(
        as_of_date="2026-03-09",
        signals=[
            {
                "symbol": "AAPL",
                "signal_family": "fundamental_factor_shadow",
                "raw_score": 71.5,
                "source_status": "OK",
                "freshness_hours": 3.0,
                "source_name": "sec_autoresearch_shadow:health_0p4__inv_growth_0p1__inv_quality_0p5",
            },
            {
                "symbol": "MSFT",
                "signal_family": "fundamental_factor_shadow",
                "raw_score": 66.2,
                "source_status": "OK",
                "freshness_hours": 4.0,
                "source_name": "sec_autoresearch_shadow:health_0p4__inv_growth_0p1__inv_quality_0p5",
            },
            {
                "symbol": "TSLA",
                "signal_family": "fundamental_factor_shadow",
                "raw_score": 0.0,
                "source_status": "NO_DATA",
                "freshness_hours": 9999.0,
                "source_name": "sec_autoresearch_shadow:health_0p4__inv_growth_0p1__inv_quality_0p5",
            },
        ],
        shortlist={
            "candidates": [
                {"symbol": "AAPL", "lane": "CORE", "rank": 1},
                {"symbol": "TSLA", "lane": "MOMENTUM", "rank": 2},
            ]
        },
        research_queue={
            "items": [
                {"symbol": "AAPL", "selected_for_deep": True},
                {"symbol": "TSLA", "selected_for_deep": False},
            ]
        },
    )

    assert report["strategy_name"] == "health_0p4__inv_growth_0p1__inv_quality_0p5"
    assert report["coverage_summary"]["signal_count"] == 3
    assert report["coverage_summary"]["ok_count"] == 2
    assert report["coverage_summary"]["shortlist_overlap_count"] == 2
    assert report["coverage_summary"]["selected_for_deep_overlap_count"] == 1
    assert report["source_status_counts"] == {"NO_DATA": 1, "OK": 2}
    assert report["top_signals"][0]["symbol"] == "AAPL"
    assert report["top_signals"][0]["in_shortlist"] is True
    assert report["top_signals"][0]["selected_for_deep"] is True
