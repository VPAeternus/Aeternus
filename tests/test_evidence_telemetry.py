import json

from tradingagents.evidence.telemetry import (
    build_cost_alpha_telemetry,
    build_feature_family_dashboard,
    build_source_ablation_report,
)


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))


def test_cost_alpha_telemetry_aggregates_alpha_cost_and_family_views(tmp_path):
    dealflow_dir = tmp_path / "eval_results" / "deal_flow"
    _write_json(
        dealflow_dir / "2026-02-06" / "shortlist_top20.json",
        {
            "x_scope_summary": {
                "mode": "HYBRID",
                "handles": 4,
                "symbol_calls": 3,
                "expansions": 1,
            }
        },
    )
    _write_json(
        dealflow_dir / "2026-02-07" / "connector_health.json",
        [
            {
                "connector": "social_news",
                "x_scope": {
                    "mode": "DIRECT_ONLY",
                    "handles": 99,
                    "symbol_calls": 2,
                    "expansions": 0,
                },
            }
        ],
    )

    summaries = [
        {
            "date": "2026-02-06",
            "run_id": "run-1",
            "processed": 4,
            "success_count": 3,
            "failure_count": 1,
            "skipped_count": 0,
            "analysis_mode_counts": {"DEEP": 2, "QUICK": 2},
            "attribution": {
                "overall": {
                    "realized_horizons": {
                        "5d": {
                            "evaluated_count": 2,
                            "pending_count": 1,
                            "no_data_count": 0,
                            "avg_strategy_edge_vs_benchmark_pct": 1.5,
                            "strategy_edge_win_rate": 0.5,
                        },
                        "20d": {
                            "evaluated_count": 1,
                            "pending_count": 2,
                            "no_data_count": 0,
                            "avg_strategy_edge_vs_benchmark_pct": 2.0,
                            "strategy_edge_win_rate": 1.0,
                        },
                    }
                },
                "by_signal_family": {
                    "price_momentum": {
                        "count": 2,
                        "realized_horizons": {
                            "5d": {
                                "evaluated_count": 1,
                                "pending_count": 0,
                                "no_data_count": 0,
                                "avg_strategy_edge_vs_benchmark_pct": 2.0,
                                "strategy_edge_win_rate": 1.0,
                            },
                            "20d": {
                                "evaluated_count": 1,
                                "pending_count": 0,
                                "no_data_count": 0,
                                "avg_strategy_edge_vs_benchmark_pct": 2.5,
                                "strategy_edge_win_rate": 1.0,
                            },
                        },
                    },
                    "social_momentum": {
                        "count": 1,
                        "realized_horizons": {
                            "5d": {
                                "evaluated_count": 1,
                                "pending_count": 0,
                                "no_data_count": 0,
                                "avg_strategy_edge_vs_benchmark_pct": 1.0,
                                "strategy_edge_win_rate": 0.0,
                            },
                            "20d": {
                                "evaluated_count": 0,
                                "pending_count": 1,
                                "no_data_count": 0,
                                "avg_strategy_edge_vs_benchmark_pct": None,
                                "strategy_edge_win_rate": None,
                            },
                        },
                    },
                },
                "signal_family_counts": {
                    "price_momentum": 2,
                    "social_momentum": 1,
                },
            },
        },
        {
            "date": "2026-02-07",
            "run_id": "run-2",
            "processed": 3,
            "success_count": 2,
            "failure_count": 0,
            "skipped_count": 1,
            "analysis_mode_counts": {"DEEP": 1, "QUICK": 2},
            "attribution": {
                "overall": {
                    "realized_horizons": {
                        "5d": {
                            "evaluated_count": 3,
                            "pending_count": 0,
                            "no_data_count": 0,
                            "avg_strategy_edge_vs_benchmark_pct": -0.5,
                            "strategy_edge_win_rate": 0.33,
                        },
                        "20d": {
                            "evaluated_count": 2,
                            "pending_count": 1,
                            "no_data_count": 0,
                            "avg_strategy_edge_vs_benchmark_pct": 0.4,
                            "strategy_edge_win_rate": 0.5,
                        },
                    }
                },
                "by_signal_family": {
                    "price_momentum": {
                        "count": 2,
                        "realized_horizons": {
                            "5d": {
                                "evaluated_count": 2,
                                "pending_count": 0,
                                "no_data_count": 0,
                                "avg_strategy_edge_vs_benchmark_pct": -0.2,
                                "strategy_edge_win_rate": 0.5,
                            },
                            "20d": {
                                "evaluated_count": 1,
                                "pending_count": 0,
                                "no_data_count": 0,
                                "avg_strategy_edge_vs_benchmark_pct": 0.3,
                                "strategy_edge_win_rate": 0.0,
                            },
                        },
                    },
                    "smart_money": {
                        "count": 1,
                        "realized_horizons": {
                            "5d": {
                                "evaluated_count": 1,
                                "pending_count": 0,
                                "no_data_count": 0,
                                "avg_strategy_edge_vs_benchmark_pct": -1.0,
                                "strategy_edge_win_rate": 0.0,
                            },
                            "20d": {
                                "evaluated_count": 1,
                                "pending_count": 0,
                                "no_data_count": 0,
                                "avg_strategy_edge_vs_benchmark_pct": 0.6,
                                "strategy_edge_win_rate": 1.0,
                            },
                        },
                    },
                },
                "signal_family_counts": {
                    "price_momentum": 2,
                    "smart_money": 1,
                },
            },
        },
    ]

    report = build_cost_alpha_telemetry(
        summaries=summaries,
        from_date="2026-02-06",
        to_date="2026-02-07",
        x_cost_per_api_call_usd=0.5,
        dealflow_base_dir=dealflow_dir,
    )

    assert report["sample_days"] == 2
    # With cashtag_stream removed, x_scope is only read from shortlist_top20.json (day 1: HYBRID, 4+3=7 calls).
    # Day 2 connector_health no longer matches the cashtag_stream lookup, so contributes 0.
    assert report["totals"]["estimated_x_api_calls"] == 7
    assert round(report["totals"]["estimated_x_cost_usd"], 6) == 3.5

    hz5 = report["alpha"]["5d"]
    hz20 = report["alpha"]["20d"]
    assert hz5["evaluated_count"] == 5
    assert hz20["evaluated_count"] == 3
    assert hz5["avg_strategy_edge_vs_benchmark_pct"] == 0.3
    assert hz20["avg_strategy_edge_vs_benchmark_pct"] == 0.933333

    # efficiency = edge_pct * 100 / total_cost_usd (day1 cost = 3.5, day2 cost = 0)
    assert report["efficiency"]["5d_edge_bps_per_usd"] == round(0.3 * 100 / 3.5, 6)
    assert report["efficiency"]["20d_edge_bps_per_usd"] == round(0.933333 * 100 / 3.5, 6)

    by_family = report["by_signal_family"]
    assert by_family["price_momentum"]["signal_count"] == 4
    # Day 1: cost=3.5, price_momentum=2/3 share; day 2: cost=0
    assert by_family["price_momentum"]["allocated_cost_usd"] == round(3.5 * 2 / 3, 6)
    assert by_family["social_momentum"]["allocated_cost_usd"] == round(3.5 * 1 / 3, 6)
    # smart_money only in day 2 which has 0 cost
    assert by_family["smart_money"]["allocated_cost_usd"] == 0.0


def test_feature_family_dashboard_prioritizes_by_share_and_ablation_impact():
    telemetry = {
        "from_date": "2026-02-06",
        "to_date": "2026-02-07",
        "by_signal_family": {
            "price_momentum": {
                "signal_count": 4,
                "signal_share": 0.666667,
                "allocated_cost_usd": 3.0,
                "horizons": {
                    "5d": {
                        "avg_strategy_edge_vs_benchmark_pct": 0.6,
                        "strategy_edge_win_rate": 0.75,
                    },
                    "20d": {
                        "avg_strategy_edge_vs_benchmark_pct": 1.1,
                        "strategy_edge_win_rate": 0.66,
                    },
                },
                "efficiency": {
                    "5d_edge_bps_per_usd": 20.0,
                    "20d_edge_bps_per_usd": 36.666667,
                },
            },
            "smart_money": {
                "signal_count": 1,
                "signal_share": 0.166667,
                "allocated_cost_usd": 0.33,
                "horizons": {
                    "5d": {
                        "avg_strategy_edge_vs_benchmark_pct": -0.3,
                        "strategy_edge_win_rate": 0.2,
                    },
                    "20d": {
                        "avg_strategy_edge_vs_benchmark_pct": 0.4,
                        "strategy_edge_win_rate": 0.5,
                    },
                },
                "efficiency": {
                    "5d_edge_bps_per_usd": -90.0,
                    "20d_edge_bps_per_usd": 121.212121,
                },
            },
        },
    }
    ablation_report = {
        "families": [
            {
                "family": "price_momentum",
                "runs_evaluated": 2,
                "avg_selection_turnover": 0.4,
                "avg_edge_delta_5d_pct": -0.3,
                "avg_edge_delta_20d_pct": -0.8,
            },
            {
                "family": "smart_money",
                "runs_evaluated": 2,
                "avg_selection_turnover": 0.2,
                "avg_edge_delta_5d_pct": -0.4,
                "avg_edge_delta_20d_pct": -1.1,
            },
        ]
    }

    dashboard = build_feature_family_dashboard(
        telemetry=telemetry,
        ablation_report=ablation_report,
    )

    assert dashboard["family_count"] == 2
    assert dashboard["rows"][0]["family"] == "price_momentum"
    assert dashboard["rows"][0]["rank"] == 1
    assert dashboard["rows"][0]["ablation_delta_20d_pct"] == -0.8
    assert dashboard["rows"][0]["efficiency_20d_edge_bps_per_usd"] == 36.666667


def test_source_ablation_report_computes_source_deltas_costs_and_roi(tmp_path):
    dealflow_dir = tmp_path / "eval_results" / "deal_flow"
    _write_json(
        dealflow_dir / "2026-02-06" / "shortlist_top20.json",
        {
            "x_scope_summary": {
                "mode": "DIRECT_ONLY",
                "handles": 0,
                "symbol_calls": 4,
                "expansions": 0,
            }
        },
    )
    _write_json(
        dealflow_dir / "2026-02-06" / "connector_health.json",
        [
            {
                "connector": "social_news",
                "status": "OK",
                "source_names": ["news+social_proxy"],
            },
            {
                "connector": "macro",
                "status": "OK",
                "source_names": ["macro_proxy_model"],
            },
        ],
    )

    items_by_date = {
        "2026-02-06": [
            {
                "symbol": "XWIN",
                "lane": "MOMENTUM",
                "subscores": {
                    "social_momentum": 30.0,
                    "price_momentum": 4.0,
                    "macro_regime_fit": 4.0,
                    "news_catalyst": 4.0,
                    "smart_money": 4.0,
                    "liquidity_tradability": 4.0,
                },
                "realized_horizons": {
                    "5d": {"status": "READY", "strategy_edge_vs_benchmark_pct": 2.0},
                    "20d": {"status": "READY", "strategy_edge_vs_benchmark_pct": 3.0},
                },
            },
            {
                "symbol": "NWIN",
                "lane": "CORE",
                "subscores": {
                    "social_momentum": 1.0,
                    "price_momentum": 4.0,
                    "macro_regime_fit": 4.0,
                    "news_catalyst": 9.0,
                    "smart_money": 4.0,
                    "liquidity_tradability": 4.0,
                },
                "realized_horizons": {
                    "5d": {"status": "READY", "strategy_edge_vs_benchmark_pct": 0.8},
                    "20d": {"status": "READY", "strategy_edge_vs_benchmark_pct": 1.5},
                },
            },
            {
                "symbol": "MWIN",
                "lane": "CORE",
                "subscores": {
                    "social_momentum": 1.0,
                    "price_momentum": 4.0,
                    "macro_regime_fit": 9.0,
                    "news_catalyst": 4.0,
                    "smart_money": 4.0,
                    "liquidity_tradability": 4.0,
                },
                "realized_horizons": {
                    "5d": {"status": "READY", "strategy_edge_vs_benchmark_pct": 0.6},
                    "20d": {"status": "READY", "strategy_edge_vs_benchmark_pct": 1.0},
                },
            },
        ]
    }

    report = build_source_ablation_report(
        items_by_date=items_by_date,
        from_date="2026-02-06",
        to_date="2026-02-06",
        dealflow_base_dir=dealflow_dir,
        deep_k=1,
        x_cost_per_api_call_usd=0.5,
        news_cost_per_run_usd=0.3,
        macro_cost_per_run_usd=0.1,
    )

    assert report["source_count"] == 3
    rows = {row["source"]: row for row in report["sources"]}
    assert rows["x"]["estimated_cost_usd"] == 2.0
    assert rows["news_vendors"]["estimated_cost_usd"] == 0.3
    assert rows["macro_feed"]["estimated_cost_usd"] == 0.1
    assert rows["x"]["alpha_contribution_20d_pct"] == 2.0
    assert rows["x"]["alpha_per_dollar_20d_bps"] == 100.0
    assert rows["x"]["runs_evaluated"] == 1
