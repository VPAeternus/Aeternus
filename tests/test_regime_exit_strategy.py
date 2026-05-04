import importlib.util
from pathlib import Path

import pandas as pd


def _load_module():
    path = Path("strategies/regime_exit/regime_exit_strategy.py")
    spec = importlib.util.spec_from_file_location("regime_exit_strategy", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_compute_metrics_reports_compounded_portfolio_returns():
    mod = _load_module()

    closes = [100.0, 110.0, 121.0]
    df = pd.DataFrame({"Close": closes})
    result_df = pd.DataFrame(
        {
            "Close": closes,
            "state": ["long", "long", "long"],
            "position": [1, 1, 1],
            "exit_type": ["", "", ""],
        }
    )

    metrics = mod.compute_metrics(df, result_df)

    assert round(metrics["strategy_return_pct"], 2) == 21.0
    assert round(metrics["buy_hold_return_pct"], 2) == 21.0


def test_compute_metrics_holds_cash_when_out_of_position():
    mod = _load_module()

    closes = [100.0, 110.0, 121.0]
    df = pd.DataFrame({"Close": closes})
    result_df = pd.DataFrame(
        {
            "Close": closes,
            "state": ["long", "holdout", "holdout"],
            "position": [1, 0, 0],
            "exit_type": ["", "overbought", ""],
        }
    )

    metrics = mod.compute_metrics(df, result_df)

    assert round(metrics["strategy_return_pct"], 2) == 10.0
    assert round(metrics["buy_hold_return_pct"], 2) == 21.0
