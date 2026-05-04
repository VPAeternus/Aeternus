import pandas as pd

from tradingagents.backtesting.macro.regime_tables import build_performance_table


def test_regime_performance_table_aggregates_forward_returns():
    rows = pd.DataFrame(
        [
            {"regime": "BULL", "fwd_SPY_5d": 0.10},
            {"regime": "BULL", "fwd_SPY_5d": -0.05},
            {"regime": "BEAR", "fwd_SPY_5d": -0.20},
        ]
    )

    table = build_performance_table(rows, group_by=("regime",), return_columns=("fwd_SPY_5d",))
    bull = table[(table["regime"] == "BULL") & (table["return_column"] == "fwd_SPY_5d")].iloc[0]

    assert bull["count"] == 2
    assert round(float(bull["mean_return"]), 6) == 0.025
    assert round(float(bull["hit_rate"]), 6) == 0.5
    assert round(float(bull["best_return"]), 6) == 0.10
    assert round(float(bull["worst_return"]), 6) == -0.05
