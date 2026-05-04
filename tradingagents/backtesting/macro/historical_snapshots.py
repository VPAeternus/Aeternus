"""Point-in-time-ish historical macro snapshots.

This module is intentionally pure: callers pass already-loaded price and
macro history. FRED values are treated as known only after an explicit lag;
for true PIT research, pass vintage/release-date aligned inputs.
"""

from __future__ import annotations

from typing import Iterable, Optional, Sequence

import pandas as pd

from tradingagents.agents.utils.macro_engine import (
    _20d_return,
    _classify_regime,
    _compute_commodity_cycle,
    _compute_correlation_regime,
    _compute_monetary_stress,
    _compute_rate_headwind,
    _compute_regime_fit,
    _rolling_mean,
)

DEFAULT_MARKET_SYMBOLS = ("SPY", "^VIX", "GLD", "SLV", "TLT", "UUP", "DBC", "BTC-USD", "HYG", "LQD", "EEM")


def build_historical_macro_snapshots(
    price_history: pd.DataFrame,
    *,
    fred_history: Optional[pd.DataFrame] = None,
    snapshot_dates: Optional[Iterable[pd.Timestamp | str]] = None,
    snapshot_frequency: str = "W-FRI",
    fred_release_lag_days: int = 0,
    sector: str = "",
    asset_class: str = "Equity",
) -> pd.DataFrame:
    """Compute macro snapshots on historical dates without using future rows.

    Args:
        price_history: Wide close-price frame indexed by date.
        fred_history: Optional frame indexed by effective/release date with columns
            `dgs10`, `dgs2`, `cpi_yoy`, `debt_to_gdp`, `deficit_pct_gdp`.
        snapshot_dates: Explicit dates. If absent, generated from SPY dates by frequency.
        snapshot_frequency: Pandas resample rule used when snapshot_dates is absent.
        fred_release_lag_days: Conservative lag applied before FRED rows are visible.
        sector: Sector adjustment context.
        asset_class: Asset-class adjustment context.
    """
    prices = _normalize_price_frame(price_history)
    fred = _normalize_fred_frame(fred_history)
    dates = list(snapshot_dates) if snapshot_dates is not None else _snapshot_dates(prices, snapshot_frequency)

    rows = []
    for raw_date in dates:
        as_of = pd.Timestamp(raw_date)
        price_slice = prices.loc[prices.index <= as_of]
        if price_slice.empty or "SPY" not in price_slice.columns:
            continue
        row = _build_one_snapshot(
            price_slice=price_slice,
            fred_history=fred,
            as_of=as_of,
            fred_release_lag_days=fred_release_lag_days,
            sector=sector,
            asset_class=asset_class,
        )
        rows.append(row)
    return pd.DataFrame(rows)


def _build_one_snapshot(
    *,
    price_slice: pd.DataFrame,
    fred_history: Optional[pd.DataFrame],
    as_of: pd.Timestamp,
    fred_release_lag_days: int,
    sector: str,
    asset_class: str,
) -> dict:
    series_map = {col: price_slice[col].dropna() for col in price_slice.columns}
    spy = series_map.get("SPY")
    vix = series_map.get("^VIX")
    if spy is None or spy.empty:
        raise ValueError("SPY history is required")

    spy_close = float(spy.iloc[-1])
    vix_close = float(vix.iloc[-1]) if vix is not None and not vix.empty else 20.0
    spy_sma20 = _rolling_mean(spy, 20) or spy_close
    spy_sma200 = _rolling_mean(spy, 200) or spy_close
    spy_return_1d_pct = 0.0
    if len(spy.dropna()) >= 2:
        spy_return_1d_pct = (float(spy.iloc[-1]) / float(spy.iloc[-2]) - 1.0) * 100.0

    fred = _latest_fred_row(fred_history, as_of, fred_release_lag_days)
    dgs10 = fred.get("dgs10")
    dgs2 = fred.get("dgs2")
    cpi_yoy = fred.get("cpi_yoy")
    yield_curve = (dgs10 - dgs2) if dgs10 is not None and dgs2 is not None else fred.get("yield_curve_2s10s")

    returns = {symbol: _20d_return(series_map.get(symbol)) for symbol in DEFAULT_MARKET_SYMBOLS if symbol in series_map}
    spy_ret_raw = returns.get("SPY")
    gld_ret_raw = returns.get("GLD")
    btc_ret_raw = returns.get("BTC-USD")
    uup_ret_raw = returns.get("UUP")
    dbc_ret_raw = returns.get("DBC")
    slv_ret_raw = returns.get("SLV")
    tlt_ret_raw = returns.get("TLT")
    hyg_ret_raw = returns.get("HYG")
    lqd_ret_raw = returns.get("LQD")
    eem_ret_raw = returns.get("EEM")
    spy_ret = spy_ret_raw or 0.0
    tlt_ret = tlt_ret_raw or 0.0
    hyg_ret = hyg_ret_raw or 0.0
    lqd_ret = lqd_ret_raw or 0.0
    gold_vs_spy = (gld_ret_raw - spy_ret_raw) if (gld_ret_raw is not None and spy_ret_raw is not None) else None
    btc_vs_spy = (btc_ret_raw - spy_ret_raw) if (btc_ret_raw is not None and spy_ret_raw is not None) else None
    silver_vs_gold = (slv_ret_raw - gld_ret_raw) if (slv_ret_raw is not None and gld_ret_raw is not None) else None
    hyg_vs_tlt = hyg_ret - tlt_ret
    lqd_vs_tlt = lqd_ret - tlt_ret

    stress_inputs = {
        "gold_vs_spy": (returns.get("GLD") or 0.0) - spy_ret,
        "btc_vs_spy": (returns.get("BTC-USD") or 0.0) - spy_ret,
        "usd_trend": returns.get("UUP") or 0.0,
        "silver_vs_gold": (returns.get("SLV") or 0.0) - (returns.get("GLD") or 0.0),
        "tlt_20d_return": returns.get("TLT"),
        "gld_20d_return": returns.get("GLD"),
        "dbc_20d_return": returns.get("DBC"),
        "dgs10": dgs10,
        "dgs2": dgs2,
        "cpi_yoy": cpi_yoy,
        "yield_curve_2s10s": yield_curve,
        "hyg_vs_tlt": hyg_vs_tlt,
        "lqd_vs_tlt": lqd_vs_tlt,
    }

    regime, triggers = _classify_regime(
        spy_close=spy_close,
        spy_sma20=spy_sma20,
        spy_sma200=spy_sma200,
        vix_close=vix_close,
        spy_return_1d_pct=spy_return_1d_pct,
        dgs10=dgs10,
        cpi_yoy=cpi_yoy,
        yield_curve_2s10s=yield_curve,
        hyg_vs_tlt=hyg_vs_tlt,
    )
    regime_fit = _compute_regime_fit(regime, sector, asset_class)
    monetary_stress = _compute_monetary_stress(stress_inputs, asset_class)
    rate_headwind = _compute_rate_headwind(stress_inputs, sector, asset_class)
    commodity_cycle = _compute_commodity_cycle(stress_inputs, sector, asset_class)
    composite_score = int(max(0, min(100, round((regime_fit + monetary_stress + rate_headwind + commodity_cycle) / 4.0))))

    populated = 0
    total = 0
    for val in list(returns.values()) + [dgs10, dgs2, cpi_yoy, yield_curve]:
        total += 1
        if val is not None and not pd.isna(val):
            populated += 1

    return {
        "snapshot_date": as_of,
        "regime": regime,
        "regime_triggers": triggers,
        "composite_score": composite_score,
        "direction": "BULLISH" if composite_score >= 60 else "BEARISH" if composite_score <= 40 else "NEUTRAL",
        "regime_fit": regime_fit,
        "monetary_stress": monetary_stress,
        "rate_headwind": rate_headwind,
        "commodity_cycle": commodity_cycle,
        "spy_close": round(spy_close, 4),
        "vix_close": round(vix_close, 4),
        "spy_20d_return": round(spy_ret_raw, 6) if spy_ret_raw is not None else None,
        "gld_20d_return": round(gld_ret_raw, 6) if gld_ret_raw is not None else None,
        "btc_20d_return": round(btc_ret_raw, 6) if btc_ret_raw is not None else None,
        "uup_20d_return": round(uup_ret_raw, 6) if uup_ret_raw is not None else None,
        "dbc_20d_return": round(dbc_ret_raw, 6) if dbc_ret_raw is not None else None,
        "slv_20d_return": round(slv_ret_raw, 6) if slv_ret_raw is not None else None,
        "tlt_20d_return": round(tlt_ret_raw, 6) if tlt_ret_raw is not None else None,
        "hyg_20d_return": round(hyg_ret_raw, 6) if hyg_ret_raw is not None else None,
        "lqd_20d_return": round(lqd_ret_raw, 6) if lqd_ret_raw is not None else None,
        "eem_20d_return": round(eem_ret_raw, 6) if eem_ret_raw is not None else None,
        "gold_vs_spy": round(gold_vs_spy, 6) if gold_vs_spy is not None else None,
        "btc_vs_spy": round(btc_vs_spy, 6) if btc_vs_spy is not None else None,
        "silver_vs_gold": round(silver_vs_gold, 6) if silver_vs_gold is not None else None,
        "dgs10": dgs10,
        "dgs2": dgs2,
        "yield_curve_2s10s": yield_curve,
        "cpi_yoy": cpi_yoy,
        "hyg_vs_tlt": round(hyg_vs_tlt, 6),
        "lqd_vs_tlt": round(lqd_vs_tlt, 6),
        "correlation_broken_count": _compute_correlation_regime(series_map).get("broken_count", 0),
        "data_coverage": round(populated / total, 2) if total else 0.0,
        "pit_disclaimer": "research_only_not_true_pit_unless_inputs_are_vintage_or_release_aligned",
    }


def _snapshot_dates(prices: pd.DataFrame, frequency: str) -> list[pd.Timestamp]:
    base = prices[["SPY"]].dropna() if "SPY" in prices.columns else prices.iloc[:, [0]].dropna()
    return list(base.resample(frequency).last().dropna().index)


def _latest_fred_row(fred_history: Optional[pd.DataFrame], as_of: pd.Timestamp, lag_days: int) -> dict:
    if fred_history is None or fred_history.empty:
        return {}
    visible_cutoff = as_of - pd.Timedelta(days=max(0, int(lag_days)))
    visible = fred_history.loc[fred_history.index <= visible_cutoff]
    if visible.empty:
        return {}
    row = visible.iloc[-1]
    out = {}
    for key in ("dgs10", "dgs2", "cpi_yoy", "debt_to_gdp", "deficit_pct_gdp", "yield_curve_2s10s"):
        if key in row and not pd.isna(row[key]):
            out[key] = float(row[key])
    return out


def _normalize_price_frame(price_history: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(price_history, pd.DataFrame):
        raise TypeError("price_history must be a pandas DataFrame")
    if price_history.empty:
        raise ValueError("price_history is empty")
    if "SPY" not in price_history.columns:
        raise ValueError("price_history must include SPY")
    prices = price_history.copy()
    prices.index = pd.to_datetime(prices.index)
    prices = prices.sort_index()
    if prices["SPY"].dropna().empty:
        raise ValueError("price_history SPY column has no data")
    return prices


def _normalize_fred_frame(fred_history: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
    if fred_history is None:
        return None
    fred = fred_history.copy()
    fred.index = pd.to_datetime(fred.index)
    return fred.sort_index()
