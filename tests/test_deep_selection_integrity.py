def test_build_deep_selection_integrity_report_tracks_injections_and_near_misses():
    from tradingagents.dealflow.deep_selection_integrity import build_deep_selection_integrity_report

    shortlist = {
        "date": "2026-03-08",
        "candidates": [
            {"symbol": "AAPL", "lane": "CORE", "rank": 1},
            {"symbol": "NVDA", "lane": "MOMENTUM", "rank": 2},
            {"symbol": "PLTR", "lane": "CORE", "rank": 3},
        ],
    }
    research_queue = {
        "deep_k": 2,
        "items": [
            {
                "symbol": "AAPL",
                "lane": "CORE",
                "triage_score": 90.0,
                "deal_flow_score": 88.0,
                "source": "AUTO",
                "source_detail": "AUTO_MODEL",
                "evidence": {"freshness_hours": 4.0},
                "selected_for_deep": True,
            },
            {
                "symbol": "NVDA",
                "lane": "MOMENTUM",
                "triage_score": 87.0,
                "deal_flow_score": 86.0,
                "source": "PORTFOLIO",
                "source_detail": "positions.json",
                "evidence": {"freshness_hours": 1.0},
                "selected_for_deep": True,
            },
            {
                "symbol": "PLTR",
                "lane": "CORE",
                "triage_score": 84.0,
                "deal_flow_score": 82.0,
                "source": "AUTO",
                "source_detail": "AUTO_MODEL",
                "evidence": {"freshness_hours": 3.0},
                "selected_for_deep": False,
            },
        ],
    }

    report = build_deep_selection_integrity_report(
        as_of_date="2026-03-08",
        shortlist=shortlist,
        research_queue=research_queue,
    )

    assert report["coverage_summary"]["selected_for_deep_count"] == 2
    assert report["coverage_summary"]["near_miss_count"] == 1
    assert report["coverage_summary"]["injected_selected_count"] == 1
    assert report["rule_snapshot"]["auto_selected_count"] == 1
    assert report["rule_snapshot"]["portfolio_selected_count"] == 1
    assert len(report["groups"]["selected_for_deep"]) == 2
    assert report["groups"]["selected_for_deep"][1]["selection_kind"] == "PORTFOLIO"
    assert report["groups"]["near_miss_eligible"][0]["symbol"] == "PLTR"
    assert report["groups"]["injected_selected"][0]["symbol"] == "NVDA"
    assert report["top_false_negatives"][0]["symbol"] == "PLTR"
