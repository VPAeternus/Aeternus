import pandas as pd

from tradingagents.backtesting.macro.dealflow_ablation import run_macro_ablation


def test_macro_ablation_changes_only_macro_channel_and_reports_topk_returns():
    candidates = pd.DataFrame(
        [
            {
                "date": "2026-01-02",
                "symbol": "A",
                "subscores": {"price_momentum": 70, "macro_regime_fit": 90, "news_catalyst": 50},
                "fwd_20d": 0.20,
            },
            {
                "date": "2026-01-02",
                "symbol": "B",
                "subscores": {"price_momentum": 70, "macro_regime_fit": 10, "news_catalyst": 50},
                "fwd_20d": -0.10,
            },
        ]
    )

    result = run_macro_ablation(candidates, forward_return_col="fwd_20d", top_k=1)

    ranked_on = result["ranked"][(result["ranked"]["scenario"] == "macro_on")]
    ranked_neutral = result["ranked"][(result["ranked"]["scenario"] == "macro_neutral")]
    assert ranked_on.sort_values("rank").iloc[0]["symbol"] == "A"
    assert ranked_neutral.sort_values(["rank", "symbol"]).iloc[0]["macro_regime_fit"] == 50.0
    assert set(result["summary"]["scenario"]) == {"macro_on", "macro_neutral"}


def test_macro_ablation_recomputes_asymmetry_after_macro_neutralization():
    candidates = pd.DataFrame(
        [
            {
                "date": "2026-01-02",
                "symbol": "A",
                "subscores": {"price_momentum": 90, "social_momentum": 90, "news_catalyst": 90, "macro_regime_fit": 90},
                "fwd_5d": 0.1,
            }
        ]
    )

    result = run_macro_ablation(candidates, forward_return_col="fwd_5d", top_k=1)
    asymmetry = result["ranked"].set_index("scenario")["asymmetry_score"].to_dict()

    assert asymmetry["macro_neutral"] < asymmetry["macro_on"]


def test_macro_ablation_uses_same_date_symbol_universe_in_both_scenarios():
    candidates = pd.DataFrame(
        [
            {"date": "2026-01-02", "symbol": "A", "subscores": {"macro_regime_fit": 90}, "fwd_5d": 0.1},
            {"date": "2026-01-02", "symbol": "B", "subscores": {"macro_regime_fit": 10}, "fwd_5d": 0.0},
        ]
    )

    result = run_macro_ablation(candidates, forward_return_col="fwd_5d", top_k=2)
    counts = result["ranked"].groupby("scenario")["symbol"].nunique().to_dict()

    assert counts == {"macro_neutral": 2, "macro_on": 2}
