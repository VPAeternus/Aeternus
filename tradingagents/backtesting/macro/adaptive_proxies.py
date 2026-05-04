"""Adaptive historical macro proxies for long-horizon backtests.

Uses modern ETFs when available and older futures/index/rate proxies when ETFs
were not yet trading. Input is a wide price DataFrame; no network I/O here.
"""

from __future__ import annotations

import pandas as pd


def add_adaptive_proxy_features(prices: pd.DataFrame, *, window: int = 20) -> pd.DataFrame:
    """Return daily adaptive proxy feature frame indexed like `prices`.

    Required for relative features: SPY. Missing proxies remain NaN.
    """
    if "SPY" not in prices.columns:
        raise ValueError("prices must include SPY")
    px = prices.copy().sort_index()
    rets = _pct_change_by_observation(px, window)
    out = pd.DataFrame(index=px.index)
    spy = rets["SPY"]

    gold = _first_available(rets, ["GLD", "GC=F"])
    silver = _first_available(rets, ["SLV", "SI=F"])
    dollar = _first_available(rets, ["UUP", "DX-Y.NYB"])
    # Commodity pressure: DBC when it has data, else blended oil/copper futures.
    commodity_fallback_parts = [rets[c] for c in ("CL=F", "HG=F") if c in rets.columns]
    commodity_fallback = (
        pd.concat(commodity_fallback_parts, axis=1).mean(axis=1)
        if commodity_fallback_parts
        else pd.Series(float("nan"), index=px.index)
    )
    dbc = rets["DBC"] if "DBC" in rets.columns else pd.Series(float("nan"), index=px.index)
    commodity = dbc.combine_first(commodity_fallback)
    commodity_source = pd.Series(pd.NA, index=px.index, dtype="object")
    commodity_source.loc[dbc.notna()] = "DBC"
    commodity_source.loc[dbc.isna() & commodity_fallback.notna()] = "CL=F_HG=F_BLEND"

    # Bond support: TLT when it has data, else inverse 10Y yield percent change.
    tlt = rets["TLT"] if "TLT" in rets.columns else pd.Series(float("nan"), index=px.index)
    inverse_tnx = -rets["^TNX"] if "^TNX" in rets.columns else pd.Series(float("nan"), index=px.index)
    bond = tlt.combine_first(inverse_tnx)
    bond_source = pd.Series(pd.NA, index=px.index, dtype="object")
    bond_source.loc[tlt.notna()] = "TLT"
    bond_source.loc[tlt.isna() & inverse_tnx.notna()] = "INVERSE_TNX"

    btc = rets["BTC-USD"] if "BTC-USD" in rets.columns else pd.Series(float("nan"), index=px.index)
    hyg = rets["HYG"] if "HYG" in rets.columns else pd.Series(float("nan"), index=px.index)
    lqd = rets["LQD"] if "LQD" in rets.columns else pd.Series(float("nan"), index=px.index)

    out["adaptive_gold_20d_return"] = gold
    out["adaptive_silver_20d_return"] = silver
    out["adaptive_dollar_20d_return"] = dollar
    out["adaptive_commodity_20d_return"] = commodity
    out["adaptive_bond_support_20d"] = bond
    out["adaptive_btc_20d_return"] = btc
    out["adaptive_hyg_20d_return"] = hyg
    out["adaptive_lqd_20d_return"] = lqd
    out["adaptive_gold_vs_spy"] = gold - spy
    out["adaptive_btc_vs_spy"] = btc - spy
    out["adaptive_silver_vs_gold"] = silver - gold
    out["adaptive_hyg_vs_bond"] = hyg - bond
    out["adaptive_lqd_vs_bond"] = lqd - bond
    out["adaptive_commodity_source"] = commodity_source
    out["adaptive_bond_source"] = bond_source
    out["adaptive_proxy_inputs_available"] = out[
        [
            "adaptive_gold_vs_spy",
            "adaptive_btc_vs_spy",
            "adaptive_bond_support_20d",
            "adaptive_dollar_20d_return",
            "adaptive_commodity_20d_return",
        ]
    ].notna().sum(axis=1)
    return out


def _pct_change_by_observation(prices: pd.DataFrame, window: int) -> pd.DataFrame:
    """Compute pct_change over each column's own non-null observations.

    This avoids calendar-union artifacts when mixing weekday ETFs with 7-day
    assets like BTC-USD. A 20-day return means 20 valid observations for that
    symbol, not 20 rows in the unioned calendar.
    """
    out = pd.DataFrame(index=prices.index)
    for col in prices.columns:
        series = prices[col].dropna()
        changed = series.pct_change(window)
        out[col] = changed.reindex(prices.index)
    return out


def _first_available(rets: pd.DataFrame, columns: list[str]) -> pd.Series:
    result = pd.Series(float("nan"), index=rets.index)
    for col in columns:
        if col in rets.columns:
            result = result.combine_first(rets[col])
    return result
