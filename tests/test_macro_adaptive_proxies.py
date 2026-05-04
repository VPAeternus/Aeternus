import pandas as pd

from tradingagents.backtesting.macro.adaptive_proxies import add_adaptive_proxy_features


def test_adaptive_proxies_fallback_to_futures_and_indexes():
    idx = pd.bdate_range("2001-01-01", periods=25)
    prices = pd.DataFrame(
        {
            "SPY": [100.0] * 24 + [110.0],
            "GC=F": [100.0] * 24 + [120.0],
            "CL=F": [100.0] * 24 + [130.0],
            "HG=F": [100.0] * 24 + [110.0],
            "DX-Y.NYB": [100.0] * 24 + [105.0],
            "^TNX": [100.0] * 24 + [90.0],
        },
        index=idx,
    )

    out = add_adaptive_proxy_features(prices)
    row = out.iloc[-1]

    assert round(row["adaptive_gold_20d_return"], 6) == 0.20
    assert round(row["adaptive_gold_vs_spy"], 6) == 0.10
    assert round(row["adaptive_commodity_20d_return"], 6) == 0.20
    assert round(row["adaptive_dollar_20d_return"], 6) == 0.05
    assert round(row["adaptive_bond_support_20d"], 6) == 0.10
    assert row["adaptive_commodity_source"] == "CL=F_HG=F_BLEND"
    assert row["adaptive_bond_source"] == "INVERSE_TNX"


def test_adaptive_proxies_use_symbol_observations_not_union_calendar_rows():
    idx = pd.date_range("2020-01-01", periods=30, freq="D")
    spy_values = [None if day.weekday() >= 5 else 100.0 for day in idx]
    # Last weekday gets a 10% move after 20 valid SPY observations.
    weekday_positions = [i for i, day in enumerate(idx) if day.weekday() < 5]
    spy_values[weekday_positions[-1]] = 110.0
    btc_values = [100.0] * 29 + [130.0]
    prices = pd.DataFrame({"SPY": spy_values, "BTC-USD": btc_values}, index=idx)

    out = add_adaptive_proxy_features(prices)
    last_weekday = idx[weekday_positions[-1]]

    assert pd.notna(out.loc[last_weekday, "adaptive_btc_vs_spy"])


def test_adaptive_proxies_fallback_per_row_when_modern_etf_has_later_history():
    idx = pd.bdate_range("2001-01-01", periods=25)
    prices = pd.DataFrame(
        {
            "SPY": [100.0] * 24 + [110.0],
            "DBC": [None] * 25,
            "CL=F": [100.0] * 24 + [130.0],
            "HG=F": [100.0] * 24 + [110.0],
            "TLT": [None] * 25,
            "^TNX": [100.0] * 24 + [90.0],
        },
        index=idx,
    )

    out = add_adaptive_proxy_features(prices)
    row = out.iloc[-1]

    assert round(row["adaptive_commodity_20d_return"], 6) == 0.20
    assert round(row["adaptive_bond_support_20d"], 6) == 0.10
    assert row["adaptive_commodity_source"] == "CL=F_HG=F_BLEND"
    assert row["adaptive_bond_source"] == "INVERSE_TNX"


def test_adaptive_proxies_prefer_etfs_when_available():
    idx = pd.bdate_range("2020-01-01", periods=25)
    prices = pd.DataFrame(
        {
            "SPY": [100.0] * 24 + [110.0],
            "GC=F": [100.0] * 24 + [150.0],
            "GLD": [100.0] * 24 + [120.0],
            "DBC": [100.0] * 24 + [115.0],
            "CL=F": [100.0] * 24 + [130.0],
            "HG=F": [100.0] * 24 + [130.0],
            "TLT": [100.0] * 24 + [105.0],
            "^TNX": [100.0] * 24 + [90.0],
        },
        index=idx,
    )

    out = add_adaptive_proxy_features(prices)
    row = out.iloc[-1]

    assert round(row["adaptive_gold_20d_return"], 6) == 0.20
    assert round(row["adaptive_commodity_20d_return"], 6) == 0.15
    assert round(row["adaptive_bond_support_20d"], 6) == 0.05
    assert row["adaptive_commodity_source"] == "DBC"
    assert row["adaptive_bond_source"] == "TLT"
