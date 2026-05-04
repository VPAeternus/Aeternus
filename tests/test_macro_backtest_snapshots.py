import pandas as pd

from tradingagents.backtesting.macro.historical_snapshots import build_historical_macro_snapshots


def _series(start, periods, first=100.0, step=1.0):
    idx = pd.bdate_range(start, periods=periods)
    return idx, [first + i * step for i in range(periods)]


def test_historical_snapshot_uses_only_values_available_at_or_before_snapshot_date():
    idx, spy = _series("2026-01-01", 230, 100, 1)
    prices = pd.DataFrame(
        {
            "SPY": spy,
            "^VIX": [18.0] * len(idx),
            "GLD": [100.0] * len(idx),
            "SLV": [100.0] * len(idx),
            "TLT": [100.0] * len(idx),
            "UUP": [100.0] * len(idx),
            "DBC": [100.0] * len(idx),
            "BTC-USD": [100.0] * len(idx),
            "HYG": [100.0] * len(idx),
            "LQD": [100.0] * len(idx),
            "EEM": [100.0] * len(idx),
        },
        index=idx,
    )
    snapshot_date = idx[210]
    fred = pd.DataFrame(
        {
            "dgs10": [4.0, 9.9],
            "dgs2": [3.5, 9.0],
            "cpi_yoy": [2.5, 9.9],
        },
        index=[snapshot_date, idx[-1]],
    )

    out = build_historical_macro_snapshots(
        prices,
        fred_history=fred,
        snapshot_dates=[snapshot_date],
    )

    assert len(out) == 1
    assert out.loc[0, "dgs10"] == 4.0
    assert out.loc[0, "cpi_yoy"] == 2.5
    assert out.loc[0, "regime"] != "INFLATION_SHOCK"


def test_historical_snapshot_persists_raw_cross_asset_features():
    idx = pd.bdate_range("2026-01-01", periods=230)
    prices = pd.DataFrame(
        {
            "SPY": [100.0] * 229 + [110.0],
            "^VIX": [18.0] * 230,
            "GLD": [100.0] * 229 + [120.0],
            "BTC-USD": [100.0] * 229 + [130.0],
            "UUP": [100.0] * 229 + [90.0],
            "DBC": [100.0] * 229 + [115.0],
            "SLV": [100.0] * 229 + [125.0],
            "TLT": [100.0] * 229 + [105.0],
            "HYG": [100.0] * 229 + [103.0],
            "LQD": [100.0] * 229 + [104.0],
            "EEM": [100.0] * 230,
        },
        index=idx,
    )

    out = build_historical_macro_snapshots(prices, snapshot_dates=[idx[-1]])

    row = out.iloc[0]
    assert round(row["gld_20d_return"], 6) == 0.20
    assert round(row["btc_20d_return"], 6) == 0.30
    assert round(row["uup_20d_return"], 6) == -0.10
    assert round(row["dbc_20d_return"], 6) == 0.15
    assert round(row["gold_vs_spy"], 6) == 0.10
    assert round(row["btc_vs_spy"], 6) == 0.20
    assert round(row["silver_vs_gold"], 6) == 0.05
    assert round(row["hyg_20d_return"], 6) == 0.03
    assert round(row["lqd_20d_return"], 6) == 0.04
    assert round(row["tlt_20d_return"], 6) == 0.05


def test_historical_snapshot_rejects_missing_spy_price_history():
    idx = pd.bdate_range("2026-01-01", periods=5)
    prices = pd.DataFrame({"QQQ": [100, 101, 102, 103, 104]}, index=idx)

    try:
        build_historical_macro_snapshots(prices, snapshot_dates=[idx[-1]])
    except ValueError as exc:
        assert "SPY" in str(exc)
    else:
        raise AssertionError("Expected ValueError for missing SPY")


def test_historical_snapshot_respects_fred_release_lag_days():
    idx, spy = _series("2026-01-01", 230, 100, 1)
    prices = pd.DataFrame({"SPY": spy, "^VIX": [18.0] * len(idx)}, index=idx)
    snapshot_date = idx[210]
    fred = pd.DataFrame({"dgs10": [3.0, 5.0], "cpi_yoy": [2.0, 5.0]}, index=[idx[100], snapshot_date])

    out = build_historical_macro_snapshots(
        prices,
        fred_history=fred,
        snapshot_dates=[snapshot_date],
        fred_release_lag_days=5,
    )

    assert out.loc[0, "dgs10"] == 3.0
    assert out.loc[0, "cpi_yoy"] == 2.0
