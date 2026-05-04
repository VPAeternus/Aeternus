import pandas as pd

from tradingagents.backtesting.macro.forward_returns import DEFAULT_HORIZONS, attach_forward_returns


def test_default_horizons_match_macro_backtest_contract():
    assert DEFAULT_HORIZONS == (5, 10, 20, 30, 60, 90)


def test_forward_returns_start_from_next_trading_bar_not_signal_close():
    dates = pd.bdate_range("2026-01-01", periods=8)
    prices = pd.DataFrame({"SPY": [100, 110, 121, 133.1, 146.41, 161.051, 177.1561, 194.87171]}, index=dates)
    snapshots = pd.DataFrame([{"snapshot_date": dates[0], "regime": "BULL"}])

    out = attach_forward_returns(snapshots, prices, horizons=(2,), symbols=("SPY",))

    # Entry is dates[1] close (110), exit is two trading bars later dates[3] close (133.1).
    assert round(float(out.loc[0, "fwd_SPY_2d"]), 6) == round(133.1 / 110 - 1, 6)
    assert out.loc[0, "entry_date"] == dates[1]


def test_forward_returns_skip_calendar_rows_where_symbol_has_no_price():
    dates = pd.date_range("2026-01-02", periods=6, freq="D")
    prices = pd.DataFrame(
        {"SPY": [100.0, None, None, 110.0, 121.0, 133.1]},
        index=dates,
    )
    snapshots = pd.DataFrame([{"snapshot_date": dates[0], "regime": "BULL"}])

    out = attach_forward_returns(snapshots, prices, horizons=(2,), symbols=("SPY",))

    assert out.loc[0, "entry_date"] == dates[3]
    assert round(float(out.loc[0, "fwd_SPY_2d"]), 6) == round(133.1 / 110.0 - 1.0, 6)


def test_forward_returns_emit_nan_when_horizon_exceeds_price_history():
    dates = pd.bdate_range("2026-01-01", periods=4)
    prices = pd.DataFrame({"SPY": [100, 101, 102, 103]}, index=dates)
    snapshots = pd.DataFrame([{"snapshot_date": dates[1], "regime": "BULL"}])

    out = attach_forward_returns(snapshots, prices, horizons=(5,), symbols=("SPY",))

    assert pd.isna(out.loc[0, "fwd_SPY_5d"])
