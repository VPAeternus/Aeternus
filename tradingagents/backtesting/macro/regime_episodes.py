"""Non-overlapping regime episode construction for macro backtests."""

from __future__ import annotations

from typing import Any

import pandas as pd


def build_regime_episodes(
    snapshots: pd.DataFrame,
    price_history: pd.DataFrame,
    *,
    state_col: str,
    symbol: str = "SPY",
    date_col: str = "snapshot_date",
) -> pd.DataFrame:
    """Collapse weekly state snapshots into non-overlapping regime episodes.

    A new episode starts when `state_col` changes. The prior episode exits on
    the new state's snapshot date, so regimes never overlap.
    """
    if date_col not in snapshots.columns:
        raise ValueError(f"snapshots missing {date_col!r}")
    if state_col not in snapshots.columns:
        raise ValueError(f"snapshots missing {state_col!r}")
    if symbol not in price_history.columns:
        raise ValueError(f"price_history missing {symbol!r}")

    states = snapshots[[date_col, state_col]].copy()
    states[date_col] = pd.to_datetime(states[date_col])
    states = states.dropna(subset=[date_col, state_col]).sort_values(date_col).reset_index(drop=True)
    if states.empty:
        return pd.DataFrame(columns=_episode_columns())

    prices = price_history[[symbol]].copy()
    prices.index = pd.to_datetime(prices.index)
    prices = prices.sort_index()[symbol].dropna()
    if prices.empty:
        raise ValueError(f"price_history {symbol!r} has no prices")

    starts: list[dict[str, Any]] = []
    prev_state = object()
    for _, row in states.iterrows():
        state = row[state_col]
        if state != prev_state:
            starts.append({"start_date": row[date_col], "state": state})
            prev_state = state

    episodes = []
    for i, start in enumerate(starts):
        start_date = pd.Timestamp(start["start_date"])
        state = start["state"]
        next_state = starts[i + 1]["state"] if i + 1 < len(starts) else pd.NA
        end_date = pd.Timestamp(starts[i + 1]["start_date"]) if i + 1 < len(starts) else prices.index[-1]

        entry_date, entry_price = _price_at_or_after(prices, start_date)
        exit_date, exit_price = _price_at_or_before(prices, end_date)
        window = prices.loc[(prices.index >= entry_date) & (prices.index <= exit_date)]
        if window.empty:
            max_drawdown = float("nan")
        else:
            running_peak = window.cummax()
            max_drawdown = float((window / running_peak - 1.0).min())
        episode_return = float(exit_price / entry_price - 1.0) if entry_price else float("nan")
        duration_weeks = max(0, int(round((exit_date - entry_date).days / 7)))

        episodes.append(
            {
                "start_date": entry_date,
                "end_date": exit_date,
                "state": state,
                "duration_weeks": duration_weeks,
                "entry_price": float(entry_price),
                "exit_price": float(exit_price),
                "episode_return": episode_return,
                "max_drawdown_during_episode": max_drawdown,
                "next_state": next_state,
            }
        )
    return pd.DataFrame(episodes, columns=_episode_columns())


def build_episode_performance(episodes: pd.DataFrame) -> pd.DataFrame:
    """Aggregate episode returns by state."""
    if episodes.empty:
        return pd.DataFrame()
    rows = []
    for state, frame in episodes.dropna(subset=["episode_return"]).groupby("state", dropna=False):
        returns = frame["episode_return"].astype(float)
        dds = frame["max_drawdown_during_episode"].astype(float)
        rows.append(
            {
                "state": state,
                "episode_count": int(len(frame)),
                "avg_duration_weeks": float(frame["duration_weeks"].mean()),
                "mean_return": float(returns.mean()),
                "median_return": float(returns.median()),
                "hit_rate": float((returns > 0).mean()),
                "worst_return": float(returns.min()),
                "best_return": float(returns.max()),
                "mean_max_drawdown": float(dds.mean()),
                "worst_max_drawdown": float(dds.min()),
            }
        )
    return pd.DataFrame(rows).sort_values("mean_return", ascending=False)


def build_transition_matrix(episodes: pd.DataFrame) -> pd.DataFrame:
    """Count state -> next_state transitions."""
    if episodes.empty or "next_state" not in episodes.columns:
        return pd.DataFrame()
    transitions = episodes.dropna(subset=["next_state"])
    if transitions.empty:
        return pd.DataFrame()
    return pd.crosstab(transitions["state"], transitions["next_state"])


def _price_at_or_after(prices: pd.Series, date: pd.Timestamp) -> tuple[pd.Timestamp, float]:
    pos = prices.index.searchsorted(date, side="left")
    if pos >= len(prices):
        pos = len(prices) - 1
    return prices.index[pos], float(prices.iloc[pos])


def _price_at_or_before(prices: pd.Series, date: pd.Timestamp) -> tuple[pd.Timestamp, float]:
    pos = prices.index.searchsorted(date, side="right") - 1
    if pos < 0:
        pos = 0
    return prices.index[pos], float(prices.iloc[pos])


def _episode_columns() -> list[str]:
    return [
        "start_date",
        "end_date",
        "state",
        "duration_weeks",
        "entry_price",
        "exit_price",
        "episode_return",
        "max_drawdown_during_episode",
        "next_state",
    ]
