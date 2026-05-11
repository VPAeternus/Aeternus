def test_build_discovery_delta_aggregates_scout_and_technical_sources():
    from tradingagents.dealflow.discovery_delta import build_discovery_delta

    result = build_discovery_delta(
        as_of_date="2026-03-07",
        scout_audit={
            "signals": [
                {
                    "symbol": "AMD",
                    "source": "breakout_scanner",
                    "delta_kind": "breakout",
                    "direction": "BULLISH",
                    "raw_strength": 0.8,
                    "confidence_score": 0.7,
                    "tags": ["breakout"],
                }
            ]
        },
        fvg_recall={
            "rows": [
                {
                    "symbol": "NVDA",
                    "score": 88.0,
                    "bucket": "fvg_confirmed",
                }
            ]
        },
        fma_recall={
            "rows": [
                {
                    "symbol": "PLTR",
                    "score": 75.0,
                    "bucket": "fma_live",
                }
            ]
        },
    )

    assert result["coverage_summary"]["record_count"] == 3
    assert result["cohorts"]["scout_only"] == ["AMD"]
    assert result["cohorts"]["technical_only"] == ["NVDA", "PLTR"]
    assert result["cohorts"]["multi_channel"] == []
    assert result["top_delta_symbols"][0]["symbol"] in {"AMD", "NVDA", "PLTR"}


def test_build_discovery_delta_marks_multi_channel_overlap():
    from tradingagents.dealflow.discovery_delta import build_discovery_delta

    result = build_discovery_delta(
        as_of_date="2026-03-07",
        scout_audit={
            "signals": [
                {
                    "symbol": "NVDA",
                    "source": "breakout_scanner",
                    "delta_kind": "breakout",
                    "direction": "BULLISH",
                    "raw_strength": 0.9,
                    "confidence_score": 0.6,
                    "tags": ["breakout"],
                }
            ]
        },
        fvg_recall={
            "rows": [
                {
                    "symbol": "NVDA",
                    "score": 86.0,
                    "bucket": "fvg_confirmed",
                }
            ]
        },
        fma_recall={"rows": []},
    )

    assert result["cohorts"]["multi_channel"] == ["NVDA"]
    record = result["symbol_records"][0]
    assert record["symbol"] == "NVDA"
    assert record["multi_channel"] is True
    assert record["independent_channel_count"] == 2


def test_discovery_delta_cohorts_scorecards_compare_peers_and_step1_baseline():
    from tradingagents.dealflow.discovery_delta import build_discovery_delta_cohort_scorecards

    result = build_discovery_delta_cohort_scorecards(
        discovery_delta={
            "cohorts": {
                "scout_only": ["AMD"],
                "technical_only": ["PLTR"],
                "multi_channel": ["NVDA"],
            }
        },
        step1_symbols=["AMD", "PLTR", "NVDA", "AAPL"],
        forward_returns_by_horizon={
            "5d": {"AMD": 0.01, "PLTR": 0.03, "NVDA": 0.08, "AAPL": 0.02},
            "20d": {"AMD": 0.04, "PLTR": 0.06, "NVDA": 0.14, "AAPL": 0.05},
            "3m": {"AMD": 0.08, "PLTR": 0.11, "NVDA": 0.22, "AAPL": 0.09},
        },
        benchmark_returns_by_horizon={"5d": 0.015, "20d": 0.04, "3m": 0.08},
    )

    multi = result["cohorts"]["multi_channel"]
    assert multi["count"] == 1
    assert multi["mean_return_5d"] == 0.08
    assert multi["edge_vs_benchmark_20d"] == 0.1

    baseline = result["step1_baseline"]
    assert baseline["count"] == 4
    assert baseline["mean_return_5d"] == 0.035

    vs_baseline = result["comparisons"]["vs_step1_baseline"]["multi_channel"]
    assert vs_baseline["mean_return_5d_delta"] == 0.045

    vs_peers = result["comparisons"]["vs_other_cohorts"]["multi_channel"]
    assert vs_peers["mean_return_20d_delta"] == 0.09
