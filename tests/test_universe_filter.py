import json

from tradingagents.dealflow.universe_filter import (
    build_universe_filter_report,
    summarize_universe_filter,
)


def test_build_universe_filter_report_counts_tiers_sources_and_overlaps():
    report = build_universe_filter_report(
        as_of_date="2026-03-09",
        universe=[
            {"symbol": "AAPL"},
            {"symbol": "NVDA"},
            {"symbol": "PLTR"},
            {"symbol": "TSLA"},
        ],
        tier_map={
            "AAPL": "T1_ANCHOR",
            "NVDA": "T3B_FVG_RECALL",
            "PLTR": "T3C_FMA_RECALL",
            "TSLA": "MANUAL",
        },
        universe_ledger={"rule_snapshot": {"kept_count": 4}},
        manual_symbols=["TSLA", "NVDA"],
        x_feed_merged_symbols=["TSLA", "NVDA", "AMD"],
        scout_audit={
            "breakout": {"alerts": [{"ticker": "AMD"}]},
            "iv": {"force_queue": ["PLTR"]},
            "insider": {
                "buy_clusters": [{"ticker": "AAPL"}],
                "sell_clusters": [{"ticker": "TSLA"}],
            },
            "signals": [{"symbol": "AMD"}],
        },
        fvg_recall={"selected_symbols": ["NVDA", "TSLA"]},
        fma_recall={"selected_symbols": ["PLTR", "NVDA"]},
    )

    assert report["universe_size"] == 4
    assert report["tier_counts"]["T3B_FVG_RECALL"] == 1
    assert report["source_counts"]["x_feed_merged_symbols"] == 3
    assert report["source_counts"]["breakout_alerts"] == 1
    assert report["source_counts"]["iv_force_queue"] == 1
    assert report["overlap_counts"]["fvg_fma_overlap"] == 1
    assert report["overlap_counts"]["manual_technical_overlap"] == 2
    assert report["overlap_counts"]["scout_technical_overlap"] == 2
    assert report["health_checks"]["universe_nonzero"]["pass"] is True
    assert report["health_checks"]["manual_xfeed_present"]["pass"] is True

    summary = summarize_universe_filter(report)
    assert summary["overall_ready"] is True
    assert summary["tier_counts"]["MANUAL"] == 1
