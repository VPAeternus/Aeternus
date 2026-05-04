"""Forward-return labels for macro backtests.

Signal timing is explicit: a snapshot dated T enters on the next available
trading bar after T. A horizon of N exits N trading bars after entry.
"""

from __future__ import annotations

from typing import Iterable, Sequence

import pandas as pd

DEFAULT_HORIZONS = (5, 10, 20, 30, 60, 90)


def attach_forward_returns(
    snapshots: pd.DataFrame,
    price_history: pd.DataFrame,
    *,
    horizons: Sequence[int] = DEFAULT_HORIZONS,
    symbols: Iterable[str] = ("SPY",),
    snapshot_date_col: str = "snapshot_date",
) -> pd.DataFrame:
    """Attach forward close-to-close returns to snapshot rows.

    Args:
        snapshots: Rows with a snapshot date column.
        price_history: Wide close-price frame indexed by trading date.
        horizons: Trading-day horizons. N means exit N bars after entry.
        symbols: Price columns to label.
        snapshot_date_col: Column containing signal/snapshot date.

    Returns:
        Copy of snapshots with `entry_date` and `fwd_{symbol}_{horizon}d` columns.
    """
    if snapshot_date_col not in snapshots.columns:
        raise ValueError(f"snapshots missing {snapshot_date_col!r}")

    prices = _normalize_price_frame(price_history)
    out = snapshots.copy().reset_index(drop=True)
    out["entry_date"] = pd.NaT

    for symbol in symbols:
        if symbol not in prices.columns:
            continue
        for horizon in horizons:
            out[f"fwd_{symbol}_{int(horizon)}d"] = float("nan")

    primary_symbol = next((symbol for symbol in symbols if symbol in prices.columns), None)
    for row_idx, raw_date in out[snapshot_date_col].items():
        snapshot_date = pd.Timestamp(raw_date)

        for symbol in symbols:
            if symbol not in prices.columns:
                continue
            series = prices[symbol].dropna()
            symbol_dates = series.index
            entry_pos = symbol_dates.searchsorted(snapshot_date, side="right")
            if entry_pos >= len(symbol_dates):
                continue
            entry_date = symbol_dates[entry_pos]
            if symbol == primary_symbol:
                out.at[row_idx, "entry_date"] = entry_date
            entry_price = series.iloc[entry_pos]
            if pd.isna(entry_price) or float(entry_price) == 0.0:
                continue
            for horizon in horizons:
                exit_pos = entry_pos + int(horizon)
                col = f"fwd_{symbol}_{int(horizon)}d"
                if exit_pos >= len(symbol_dates):
                    out.at[row_idx, col] = float("nan")
                    continue
                exit_price = series.iloc[exit_pos]
                if pd.isna(exit_price):
                    out.at[row_idx, col] = float("nan")
                else:
                    out.at[row_idx, col] = float(exit_price) / float(entry_price) - 1.0
    return out


def _normalize_price_frame(price_history: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(price_history, pd.DataFrame):
        raise TypeError("price_history must be a pandas DataFrame")
    if price_history.empty:
        raise ValueError("price_history is empty")
    prices = price_history.copy()
    prices.index = pd.to_datetime(prices.index)
    prices = prices.sort_index()
    return prices
