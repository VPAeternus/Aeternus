from tradingagents.evidence.ablation import FAMILY_ORDER, build_ablation_report


def _item(symbol, lane, subscores, edge_5d, edge_20d):
    return {
        "symbol": symbol,
        "lane": lane,
        "status": "SUCCESS",
        "subscores": subscores,
        "realized_horizons": {
            "5d": {
                "status": "READY",
                "strategy_edge_vs_benchmark_pct": edge_5d,
            },
            "20d": {
                "status": "READY",
                "strategy_edge_vs_benchmark_pct": edge_20d,
            },
        },
    }


def test_ablation_outputs_all_families_and_deltas_are_bounded():
    base_subscores = {
        "social_momentum": 70.0,
        "price_momentum": 80.0,
        "macro_regime_fit": 60.0,
        "news_catalyst": 65.0,
        "smart_money": 55.0,
        "liquidity_tradability": 90.0,
    }

    items_by_date = {
        "2026-02-06": [
            _item("AAPL", "CORE", dict(base_subscores), 2.0, 3.0),
            _item("TE", "MOMENTUM", {**base_subscores, "price_momentum": 92.0}, 4.0, 5.0),
            _item("GLD", "CORE", {**base_subscores, "macro_regime_fit": 78.0}, 1.0, 2.0),
        ],
        "2026-02-07": [
            _item("MSFT", "CORE", {**base_subscores, "smart_money": 68.0}, 1.5, 2.2),
            _item("TSLA", "MOMENTUM", {**base_subscores, "social_momentum": 88.0}, 3.4, 4.8),
        ],
    }

    report = build_ablation_report(items_by_date=items_by_date, deep_k=2)

    assert report["family_count"] == len(FAMILY_ORDER)
    assert len(report["families"]) == len(FAMILY_ORDER)

    for row in report["families"]:
        assert row["runs_evaluated"] == 2
        assert 0.0 <= float(row["avg_selection_turnover"]) <= 1.0
        lane_mix = row.get("lane_mix_delta", {})
        assert "CORE" in lane_mix
        assert "MOMENTUM" in lane_mix


def test_ablation_renormalization_handles_missing_subscores():
    items_by_date = {
        "2026-02-08": [
            {
                "symbol": "AAPL",
                "lane": "CORE",
                "status": "SUCCESS",
                "subscores": {
                    "price_momentum": 81.0,
                    "news_catalyst": 74.0,
                    "liquidity_tradability": 92.0,
                },
                "realized_horizons": {
                    "5d": {"status": "READY", "strategy_edge_vs_benchmark_pct": 1.0},
                    "20d": {"status": "READY", "strategy_edge_vs_benchmark_pct": 1.8},
                },
            }
        ]
    }

    report = build_ablation_report(items_by_date=items_by_date, deep_k=1)
    assert report["families"]
    assert report["families"][0]["runs_evaluated"] == 1
