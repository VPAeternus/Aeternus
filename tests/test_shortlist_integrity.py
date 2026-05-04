def test_build_shortlist_integrity_report_groups_and_false_negatives():
    from tradingagents.dealflow.shortlist_integrity import build_shortlist_integrity_report

    candidates = [
        {
            "symbol": "AAPL",
            "status": "ACTIVE",
            "lane": "CORE",
            "core_score": 90.0,
            "deal_flow_score": 88.0,
            "freshness_hours": 4.0,
            "rank": 1,
        },
        {
            "symbol": "NVDA",
            "status": "ACTIVE",
            "lane": "MOMENTUM",
            "asymmetry_score": 95.0,
            "deal_flow_score": 85.0,
            "freshness_hours": 3.0,
            "rank": 2,
        },
        {
            "symbol": "PLTR",
            "status": "ACTIVE",
            "lane": "MOMENTUM",
            "asymmetry_score": 89.0,
            "deal_flow_score": 82.0,
            "freshness_hours": 5.0,
        },
        {
            "symbol": "AMD",
            "status": "ACTIVE",
            "lane": "CORE",
            "core_score": 84.0,
            "deal_flow_score": 80.0,
            "freshness_hours": 6.0,
        },
        {
            "symbol": "VZ",
            "status": "LOW_DATA",
            "lane": "CORE",
            "core_score": 99.0,
            "deal_flow_score": 70.0,
            "freshness_hours": 1.0,
        },
    ]
    shortlist = {
        "date": "2026-03-08",
        "top_k": 2,
        "candidates": [
            {"symbol": "AAPL", "lane": "CORE", "rank": 1, "core_score": 90.0},
            {"symbol": "NVDA", "lane": "MOMENTUM", "rank": 2, "asymmetry_score": 95.0},
        ],
    }
    research_queue = {
        "deep_k": 1,
        "items": [
            {"symbol": "AAPL", "lane": "CORE", "triage_score": 83.0, "deal_flow_score": 88.0, "selected_for_deep": True},
            {"symbol": "NVDA", "lane": "MOMENTUM", "triage_score": 79.0, "deal_flow_score": 85.0, "selected_for_deep": False},
        ],
    }

    report = build_shortlist_integrity_report(
        as_of_date="2026-03-08",
        all_scored_candidates=candidates,
        shortlist=shortlist,
        research_queue=research_queue,
    )

    assert report["coverage_summary"]["candidate_count"] == 5
    assert len(report["groups"]["selected_shortlist"]) == 2
    assert len(report["groups"]["near_miss_eligible"]) == 2
    assert report["groups"]["near_miss_eligible"][0]["symbol"] == "PLTR"
    assert len(report["groups"]["selected_for_deep"]) == 1
    assert report["groups"]["selected_for_deep"][0]["symbol"] == "AAPL"
    assert report["top_false_negatives"][0]["symbol"] == "PLTR"
    assert report["comparisons"]["selected_vs_near_miss"]["near_miss_count"] == 2
