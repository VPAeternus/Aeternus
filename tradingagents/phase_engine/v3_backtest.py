"""
V3 Momentum Acceleration Strategy — Core Library
=================================================
Pure functions extracted from scripts/backtest_accel_rth.py.
Used by both the backtest script and the production IndexOverlayEngine.

Three RTH legs + filtered overnight. See backtest_accel_rth.py docstring
for full algorithm specification.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def compute_accel(close: pd.Series, sma: pd.Series, lookback: int) -> pd.Series:
    """Second derivative of SMA slope, normalized by price."""
    slope = (sma - sma.shift(lookback)) / (close * lookback)
    return slope - slope.shift(lookback)


def build_regime(df: pd.DataFrame) -> tuple:
    """
    Build persistent regime series from acceleration zero-crossings.
    Returns (regime_series, accel_series).
    """
    accel = compute_accel(df["close"], df["sma10"], 5)
    prev_accel = accel.shift(1)

    accel_dn_signal = (accel < 0) & (prev_accel >= 0)
    accel_up_signal = (accel > 0) & (prev_accel <= 0)

    n = len(df)
    regime = np.full(n, "", dtype=object)
    current = "none"
    for i in range(n):
        if accel_dn_signal.iloc[i]:
            current = "accel_dn"
        elif accel_up_signal.iloc[i]:
            current = "accel_up"
        regime[i] = current

    return pd.Series(regime, index=df.index, name="regime"), accel


def run_backtest(df: pd.DataFrame) -> pd.DataFrame:
    """
    Simulate v3 strategy: 3 RTH legs + filtered overnight.
    All conditions use previous day's values (shift(1)).
    Returns per-day results DataFrame with per-leg attribution.
    """
    regime_series, accel_series = build_regime(df)

    prev_close = df["close"].shift(1)
    prev_sma3 = df["sma3"].shift(1)
    prev_sma10 = df["sma10"].shift(1)
    prev_sma20 = df["sma20"].shift(1)
    prev_sma50 = df["sma50"].shift(1)
    prev_sma200 = df["sma200"].shift(1)
    prev_regime = regime_series.shift(1).fillna("none")
    prev_vix = df["vix"].shift(1)
    prev_vol = df["volume"].shift(1)
    vol_sma5 = df["volume"].rolling(5).mean().shift(1)

    # RTH Leg 1: Dip-Buy
    vix_ok_leg1 = (
        ((prev_vix >= 20) & (prev_vix < 25))
        | ((prev_vix >= 30) & (prev_vix < 40))
        | (prev_vix >= 40)
    )
    leg1 = (
        (prev_regime == "accel_dn")
        & (prev_close < prev_sma3)
        & (prev_close < prev_sma10)
        & (prev_close < prev_sma20)
        & vix_ok_leg1
    ).fillna(False)

    # RTH Leg 2: Stay-Long
    leg2 = (
        (prev_vix <= 15)
        & (prev_close > prev_sma10)
        & (prev_sma10 > prev_sma20)
    ).fillna(False)

    # RTH Leg 3: Uptrend Decel
    leg3 = (
        (prev_regime == "accel_dn")
        & (prev_close > prev_sma3)
        & (prev_close > prev_sma10)
        & (prev_close > prev_sma20)
        & (prev_close > prev_sma50)
        & (prev_close > prev_sma200)
        & (prev_vol > vol_sma5)
    ).fillna(False)

    rth_cond = leg1 | leg2 | leg3

    # Non-overlapping attribution (priority: leg1 > leg2 > leg3)
    leg2_net = leg2 & ~leg1
    leg3_net = leg3 & ~leg1 & ~leg2

    rth_daily = df["close"] - df["open"]
    rth_pnl = np.where(rth_cond, rth_daily, 0.0)
    leg1_pnl = np.where(leg1, rth_daily, 0.0)
    leg2_pnl = np.where(leg2_net, rth_daily, 0.0)
    leg3_pnl = np.where(leg3_net, rth_daily, 0.0)

    # Overnight (filtered)
    skip_on_1 = (
        (prev_vix >= 30) & (prev_vix < 40) & (prev_regime == "accel_up")
    ).fillna(False)
    skip_on_2 = ((prev_vix >= 40) & (prev_close < prev_sma20)).fillna(False)
    on_active = ~(skip_on_1 | skip_on_2)

    on_raw = (df["open"] - prev_close).fillna(0.0).values.copy()
    on_raw[0] = 0.0
    on_pnl = np.where(on_active, on_raw, 0.0)

    return pd.DataFrame(
        {
            "date": df["date"].values,
            "open": df["open"].values,
            "close": df["close"].values,
            "regime": regime_series.values,
            "rth_cond": rth_cond.values,
            "leg1": leg1.values,
            "leg2": leg2_net.values,
            "leg3": leg3_net.values,
            "rth_pnl": rth_pnl,
            "leg1_pnl": leg1_pnl,
            "leg2_pnl": leg2_pnl,
            "leg3_pnl": leg3_pnl,
            "on_active": on_active.values,
            "on_pnl": on_pnl,
            "total_pnl": rth_pnl + on_pnl,
            "accel": accel_series.values,
            "vix": df["vix"].values,
        }
    )
