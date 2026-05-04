"""Aggregation tables for macro backtest outputs."""

from __future__ import annotations

from typing import Sequence

import pandas as pd


def build_performance_table(
    rows: pd.DataFrame,
    *,
    group_by: Sequence[str] = ("regime",),
    return_columns: Sequence[str] | None = None,
) -> pd.DataFrame:
    """Aggregate forward-return columns by regime/sector/bucket keys."""
    if rows.empty:
        return pd.DataFrame()
    groups = list(group_by)
    missing = [col for col in groups if col not in rows.columns]
    if missing:
        raise ValueError(f"rows missing group columns: {missing}")
    ret_cols = list(return_columns or [col for col in rows.columns if col.startswith("fwd_")])

    out = []
    for ret_col in ret_cols:
        if ret_col not in rows.columns:
            continue
        clean = rows[groups + [ret_col]].dropna(subset=[ret_col])
        if clean.empty:
            continue
        for keys, frame in clean.groupby(groups, dropna=False):
            if not isinstance(keys, tuple):
                keys = (keys,)
            values = frame[ret_col].astype(float)
            record = {group: value for group, value in zip(groups, keys)}
            record.update(
                {
                    "return_column": ret_col,
                    "count": int(values.count()),
                    "mean_return": float(values.mean()),
                    "median_return": float(values.median()),
                    "hit_rate": float((values > 0).mean()),
                    "best_return": float(values.max()),
                    "worst_return": float(values.min()),
                }
            )
            out.append(record)
    return pd.DataFrame(out)


def build_sector_performance_table(
    rows: pd.DataFrame,
    *,
    sector_col: str = "sector",
    return_columns: Sequence[str] | None = None,
) -> pd.DataFrame:
    """Convenience wrapper for sector-by-regime performance."""
    return build_performance_table(rows, group_by=("regime", sector_col), return_columns=return_columns)
