"""Point-in-time 13F delta backtest kernel.

This module intentionally starts with normalized inputs. Live SEC ingestion and
CUSIP mapping are separate concerns; this kernel enforces the backtest contract:
entry occurs after public filing date, horizons are 30/60/90 trading days, and
hold-until-exit exits only after a later public filing shows exit/reduction.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from statistics import mean
from typing import Any, Dict, Iterable, List, Optional, Sequence

import pandas as pd

HORIZONS = (30, 60, 90, 120, 150, 180)


def normalize_13f_events(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Normalize raw 13F rows and sort point-in-time by filing date.

    Expected fields include manager_id, manager_name, filing_date, report_date,
    ticker, shares, market_value. Optional previous_shares/previous_market_value
    are used for delta classification.
    """
    events: List[Dict[str, Any]] = []
    for raw in rows:
        ticker = str(raw.get("ticker", "")).upper().replace(".", "-").strip()
        manager_id = str(raw.get("manager_id") or raw.get("manager_cik") or "").strip()
        filing_date = _parse_date(raw.get("filing_date"))
        if not ticker or not manager_id or filing_date is None:
            continue
        shares = _to_float(raw.get("shares")) or 0.0
        prev_shares = _to_float(raw.get("previous_shares"))
        value = _to_float(raw.get("market_value"))
        prev_value = _to_float(raw.get("previous_market_value"))
        delta_shares = shares - (prev_shares or 0.0)
        if bool(raw.get("is_new_position")):
            action = "new"
        elif shares <= 0:
            action = "exit"
        elif delta_shares > 0:
            action = "add"
        elif delta_shares < 0:
            action = "reduce"
        else:
            action = "hold"
        events.append(
            {
                **raw,
                "manager_id": manager_id,
                "manager_name": str(raw.get("manager_name") or manager_id),
                "ticker": ticker,
                "filing_date": filing_date.isoformat(),
                "report_date": (_parse_date(raw.get("report_date")) or filing_date).isoformat(),
                "shares": shares,
                "previous_shares": prev_shares,
                "delta_shares": delta_shares,
                "market_value": value,
                "previous_market_value": prev_value,
                "action": action,
            }
        )
    return sorted(events, key=lambda row: (row["filing_date"], row["manager_id"], row["ticker"]))


def build_13f_backtest_events(
    rows: Iterable[Dict[str, Any]],
    prices: pd.DataFrame,
    *,
    benchmark: str = "SPY",
    reduction_exit_threshold: float = 0.5,
    actions: set[str] | None = None,
    exclude_initial_observations: bool = True,
) -> List[Dict[str, Any]]:
    """Create PIT 13F signal events with horizon and hold-until-exit returns."""
    events = normalize_13f_events(rows)
    allowed_actions = actions or {"new"}
    signal_events = [
        row for row in events
        if row.get("action") in allowed_actions
        and not (exclude_initial_observations and bool(row.get("is_initial_observation")))
    ]
    future_by_key: Dict[tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for row in events:
        future_by_key[(row["manager_id"], row["ticker"])].append(row)

    out: List[Dict[str, Any]] = []
    for row in signal_events:
        entry_date = next_trading_day(prices, row["ticker"], row["filing_date"])
        if entry_date is None:
            continue
        result = {**row, "tradable_date": entry_date.isoformat()}
        for horizon in HORIZONS:
            result[f"forward_return_{horizon}d"] = forward_return(prices, row["ticker"], entry_date, horizon)
            bench = forward_return(prices, benchmark, entry_date, horizon)
            raw_ret = result[f"forward_return_{horizon}d"]
            result[f"excess_return_{horizon}d"] = None if raw_ret is None or bench is None else raw_ret - bench
        exit_date = find_hold_exit_date(
            future_by_key[(row["manager_id"], row["ticker"])],
            after_filing_date=row["filing_date"],
            original_shares=float(row.get("shares") or 0.0),
            reduction_exit_threshold=reduction_exit_threshold,
            prices=prices,
        )
        result["hold_exit_date"] = exit_date.isoformat() if exit_date else ""
        result["hold_duration_days"] = (exit_date - entry_date).days if exit_date else None
        result["hold_until_exit_return"] = holding_return(prices, row["ticker"], entry_date, exit_date) if exit_date else None
        result["hold_until_exit_benchmark_return"] = holding_return(prices, benchmark, entry_date, exit_date) if exit_date else None
        if result["hold_until_exit_return"] is not None and result["hold_until_exit_benchmark_return"] is not None:
            result["hold_until_exit_excess_return"] = round(result["hold_until_exit_return"] - result["hold_until_exit_benchmark_return"], 6)
        else:
            result["hold_until_exit_excess_return"] = None
        result["hold_until_exit_cagr"] = cagr(result["hold_until_exit_return"], result["hold_duration_days"])
        result["hold_until_exit_max_drawdown"] = max_drawdown(prices, row["ticker"], entry_date, exit_date) if exit_date else None
        out.append(result)
    return out


def score_manager_quality(events: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Rank managers by historical 13F delta edge using completed event rows."""
    by_manager: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in events:
        by_manager[str(row.get("manager_id", ""))].append(row)
    scores: List[Dict[str, Any]] = []
    for manager_id, rows in by_manager.items():
        ex90 = [_to_float(row.get("excess_return_90d")) for row in rows]
        ex90 = [x for x in ex90 if x is not None]
        ex60 = [_to_float(row.get("excess_return_60d")) for row in rows]
        ex60 = [x for x in ex60 if x is not None]
        ex30 = [_to_float(row.get("excess_return_30d")) for row in rows]
        ex30 = [x for x in ex30 if x is not None]
        hold_excess = [_to_float(row.get("hold_until_exit_excess_return")) for row in rows]
        hold_excess = [x for x in hold_excess if x is not None]
        sample = len(ex90)
        hit_rate = (sum(1 for x in ex90 if x > 0) / sample) if sample else 0.0
        avg90 = mean(ex90) if ex90 else 0.0
        avg60 = mean(ex60) if ex60 else 0.0
        avg30 = mean(ex30) if ex30 else 0.0
        sample_penalty = min(1.0, sample / 20.0)
        quality = (50.0 + 250.0 * avg90 + 100.0 * avg60 + 50.0 * avg30 + 25.0 * (hit_rate - 0.5)) * sample_penalty
        scores.append(
            {
                "manager_id": manager_id,
                "manager_name": rows[-1].get("manager_name", manager_id),
                "event_count": len(rows),
                "completed_90d_count": sample,
                "hit_rate_90d": round(hit_rate, 4),
                "avg_excess_return_30d": round(avg30, 6),
                "avg_excess_return_60d": round(avg60, 6),
                "avg_excess_return_90d": round(avg90, 6),
                "avg_hold_until_exit_excess_return": round(mean(hold_excess), 6) if hold_excess else 0.0,
                "hold_until_exit_count": len(hold_excess),
                "manager_quality_score": round(max(0.0, min(100.0, quality)), 4),
            }
        )
    return sorted(scores, key=lambda row: (-row["manager_quality_score"], -row["completed_90d_count"], row["manager_id"]))


def next_trading_day(prices: pd.DataFrame, ticker: str, filing_date: str | dt.date) -> Optional[dt.date]:
    series = _price_series(prices, ticker)
    if series is None or series.empty:
        return None
    filing = _parse_date(filing_date)
    if filing is None:
        return None
    for idx in series.index:
        day = _index_date(idx)
        if day and day > filing:
            return day
    return None


def forward_return(prices: pd.DataFrame, ticker: str, entry_date: dt.date, horizon_bars: int) -> Optional[float]:
    series = _price_series(prices, ticker)
    if series is None or series.empty:
        return None
    dates = [_index_date(idx) for idx in series.index]
    try:
        start_idx = next(i for i, day in enumerate(dates) if day == entry_date)
    except StopIteration:
        return None
    end_idx = start_idx + int(horizon_bars)
    if end_idx >= len(series):
        return None
    start = float(series.iloc[start_idx])
    end = float(series.iloc[end_idx])
    if start <= 0:
        return None
    return round(end / start - 1.0, 6)


def holding_return(prices: pd.DataFrame, ticker: str, entry_date: dt.date, exit_date: Optional[dt.date]) -> Optional[float]:
    if exit_date is None:
        return None
    series = _price_series(prices, ticker)
    if series is None or series.empty:
        return None
    by_date = {_index_date(idx): float(value) for idx, value in series.items() if _index_date(idx)}
    start = by_date.get(entry_date)
    end = by_date.get(exit_date)
    if start is None or end is None or start <= 0:
        return None
    return round(end / start - 1.0, 6)


def cagr(total_return: Optional[float], duration_days: Optional[int]) -> Optional[float]:
    if total_return is None or not duration_days or duration_days <= 0:
        return None
    try:
        return round((1.0 + float(total_return)) ** (365.25 / float(duration_days)) - 1.0, 6)
    except Exception:
        return None


def max_drawdown(prices: pd.DataFrame, ticker: str, entry_date: dt.date, exit_date: Optional[dt.date]) -> Optional[float]:
    if exit_date is None:
        return None
    series = _price_series(prices, ticker)
    if series is None or series.empty:
        return None
    values = []
    for idx, value in series.items():
        day = _index_date(idx)
        if day and entry_date <= day <= exit_date:
            values.append(float(value))
    if len(values) < 2:
        return None
    peak = values[0]
    worst = 0.0
    for value in values:
        peak = max(peak, value)
        if peak > 0:
            worst = min(worst, value / peak - 1.0)
    return round(worst, 6)


def find_hold_exit_date(
    manager_ticker_events: Sequence[Dict[str, Any]],
    *,
    after_filing_date: str,
    original_shares: float,
    reduction_exit_threshold: float,
    prices: pd.DataFrame,
) -> Optional[dt.date]:
    after = _parse_date(after_filing_date)
    if after is None or original_shares <= 0:
        return None
    later = [row for row in manager_ticker_events if (_parse_date(row.get("filing_date")) or dt.date.min) > after]
    later.sort(key=lambda row: row["filing_date"])
    for row in later:
        shares = float(row.get("shares") or 0.0)
        if shares <= 0 or shares < original_shares * float(reduction_exit_threshold):
            return next_trading_day(prices, str(row.get("ticker", "")), str(row.get("filing_date")))
    return None


def _price_series(prices: pd.DataFrame, ticker: str) -> Optional[pd.Series]:
    if ticker in prices.columns:
        return pd.to_numeric(prices[ticker], errors="coerce").dropna()
    if isinstance(prices.columns, pd.MultiIndex) and ticker in prices.columns.get_level_values(-1):
        try:
            return pd.to_numeric(prices.xs(ticker, axis=1, level=-1)["Close"], errors="coerce").dropna()
        except Exception:
            return None
    return None


def _parse_date(raw: Any) -> Optional[dt.date]:
    if isinstance(raw, dt.date):
        return raw
    try:
        return dt.date.fromisoformat(str(raw)[:10])
    except Exception:
        return None


def _index_date(raw: Any) -> Optional[dt.date]:
    if isinstance(raw, dt.datetime):
        return raw.date()
    if isinstance(raw, dt.date):
        return raw
    try:
        return pd.Timestamp(raw).date()
    except Exception:
        return None


def _to_float(raw: Any) -> Optional[float]:
    try:
        if raw in {None, ""}:
            return None
        return float(raw)
    except (TypeError, ValueError):
        return None
