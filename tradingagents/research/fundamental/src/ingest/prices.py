from __future__ import annotations

from typing import Any

import pandas as pd
import yfinance as yf


RAW_REQUIRED_COLUMNS = {"Open", "High", "Low", "Close", "Volume"}


def validate_price_columns(columns: list[str] | pd.Index) -> None:
    names = set(map(str, columns))
    if "Adj Close" in names:
        raise ValueError("Adj Close forbidden: store raw OHLCV plus audited corporate-action fields")
    missing = RAW_REQUIRED_COLUMNS - names
    if missing:
        raise ValueError(f"missing raw OHLCV columns: {sorted(missing)}")


def add_corporate_action_defaults(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "split_factor": row.get("split_factor", 1),
        "dividend_amount": row.get("dividend_amount", 0),
        "corporate_action_flag": row.get("corporate_action_flag", 0),
        "adjusted_close_for_return_calc": row.get("adjusted_close_for_return_calc", row.get("Close", row.get("close", ""))),
        "split_adjusted_entry_price": row.get("split_adjusted_entry_price", row.get("entry_open", "")),
        **row,
    }


def pct_return(exit_price: float, entry_price: float) -> float:
    if entry_price == 0:
        raise ValueError("entry_price cannot be zero")
    return ((exit_price / entry_price) - 1) * 100


def _normalise_price_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalised = []
    for row in rows:
        normalised.append({str(key).lower(): value for key, value in row.items()})
    return sorted(normalised, key=lambda row: str(row["date"]))


def compute_return_checkpoints(
    price_rows: list[dict[str, Any]],
    *,
    tradable_date: str,
    actual_entry_price: float | None = None,
    horizons: tuple[int, ...] = (10, 20, 30, 60),
) -> dict[str, Any]:
    rows = _normalise_price_rows(price_rows)
    eligible = [row for row in rows if str(row.get("date", "")) >= tradable_date]
    if not eligible:
        return {"entry_open": "", "current_return_pct": "", "return_since_signal_pct": "", "return_since_purchase_pct": ""}
    entry = eligible[0]
    entry_open = float(entry["open"])
    latest = eligible[-1]
    latest_close = float(latest.get("adjusted_close_for_return_calc") or latest["close"])
    output: dict[str, Any] = {
        "tradable_date": tradable_date,
        "entry_open": entry_open,
        "current_price": latest_close,
        "current_return_pct": round(pct_return(latest_close, entry_open), 4),
        "return_since_signal_pct": round(pct_return(latest_close, entry_open), 4),
        "return_since_purchase_pct": round(pct_return(latest_close, actual_entry_price), 4) if actual_entry_price else "",
    }
    for horizon in horizons:
        exit_rows = eligible[horizon:]
        output[f"return_{horizon}d_pct"] = round(pct_return(float(exit_rows[0].get("adjusted_close_for_return_calc") or exit_rows[0]["close"]), entry_open), 4) if exit_rows else ""
    return output


def fetch_yahoo_ohlcv(tickers: list[str], *, start: str, end: str | None = None) -> list[dict[str, Any]]:
    if not tickers:
        return []
    frame = yf.download(tickers, start=start, end=end, auto_adjust=False, progress=False, group_by="ticker")
    rows: list[dict[str, Any]] = []
    if not isinstance(frame.columns, pd.MultiIndex):
        frame = frame.drop(columns=["Adj Close"], errors="ignore")
        validate_price_columns(frame.columns)
        for date, values in frame.iterrows():
            rows.append(_price_row(tickers[0], date, values))
        return rows
    for ticker in tickers:
        if ticker not in frame.columns.get_level_values(0):
            continue
        panel = frame[ticker].drop(columns=["Adj Close"], errors="ignore").dropna(how="all")
        validate_price_columns(panel.columns)
        for date, values in panel.iterrows():
            rows.append(_price_row(ticker, date, values))
    return rows


def _price_row(ticker: str, date: Any, values: Any) -> dict[str, Any]:
    close = float(values["Close"])
    volume = float(values["Volume"])
    return add_corporate_action_defaults(
        {
            "ticker": ticker,
            "date": pd.Timestamp(date).strftime("%Y-%m-%d"),
            "open": float(values["Open"]),
            "high": float(values["High"]),
            "low": float(values["Low"]),
            "close": close,
            "volume": volume,
            "dollar_volume": close * volume,
        }
    )
