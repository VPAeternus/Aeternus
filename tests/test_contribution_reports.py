from tradingagents.dealflow.contribution_reports import build_family_contribution_report


def test_build_family_contribution_report_shape_rounding_and_lanes():
    shortlist = {
        "run_id": "r1",
        "date": "2026-05-05",
        "candidates": [
            {
                "symbol": "AAPL",
                "rank": 1,
                "lane": "CORE",
                "core_score": 90.0,
                "momentum_score": 80.0,
                "asymmetry_score": 70.0,
                "subscores": {
                    "fundamental_quality": 90.0,
                    "price_momentum": 70.0,
                    "social_momentum": 60.0,
                    "news_catalyst": 50.0,
                    "macro_regime_fit": 40.0,
                    "smart_money": 30.0,
                    "liquidity_tradability": 20.0,
                },
            },
            {
                "symbol": "NVDA",
                "rank": 2,
                "lane": "MOMENTUM",
                "deal_flow_score": 82.0,
                "momentum_score": 60.0,
                "asymmetry_score": 50.0,
                "subscores": {
                    "fundamental_quality": 70.0,
                    "price_momentum": 80.0,
                    "social_momentum": 50.0,
                    "news_catalyst": 40.0,
                    "macro_regime_fit": 30.0,
                    "smart_money": 20.0,
                    "liquidity_tradability": 10.0,
                },
            },
        ],
    }

    report = build_family_contribution_report(shortlist)

    assert report["run_id"] == "r1"
    assert report["date"] == "2026-05-05"
    assert report["momentum_weight_model"] == {"price_momentum": 0.60, "social_momentum": 0.30, "news_catalyst": 0.10}
    assert report["candidates"][1]["core_score"] == 82.0
    assert report["candidates"][0]["momentum_contributions"] == {
        "price_momentum": 42.0,
        "social_momentum": 18.0,
        "news_catalyst": 5.0,
    }
    assert report["candidates"][0]["asymmetry_contributions"] == {
        "momentum_score": 56.0,
        "macro_regime_fit": 4.0,
        "smart_money": 3.0,
        "liquidity_tradability": 2.0,
    }
    assert report["aggregate"]["ALL"]["count"] == 2
    assert report["aggregate"]["CORE"]["count"] == 1
    assert report["aggregate"]["MOMENTUM"]["count"] == 1
    assert report["aggregate"]["ALL"]["avg_momentum_contributions"] == {
        "price_momentum": 45.0,
        "social_momentum": 16.5,
        "news_catalyst": 4.5,
    }


def test_build_family_contribution_report_preserves_wrapper_hooks():
    report = build_family_contribution_report(
        {"candidates": [{"symbol": "AAPL", "lane": "CORE", "subscores": {}}]},
        core_contributions_fn=lambda subs: {"custom": 1.0},
        aggregate_contributions_fn=lambda rows, lane: {"lane": lane, "count": len(rows)},
    )

    assert report["candidates"][0]["core_contributions"] == {"custom": 1.0}
    assert report["aggregate"]["CORE"] == {"lane": "CORE", "count": 1}
