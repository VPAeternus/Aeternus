"""Incremental daily OHLCV cache sync for the technical signal store."""

from __future__ import annotations

import datetime as dt
from typing import Any, Sequence

import pandas as pd
import yfinance as yf

from .technical_signal_store import SQLiteTechnicalSignalStore


def sync_market_history(
    store: SQLiteTechnicalSignalStore,
    tickers: Sequence[str],
    *,
    start_date: str,
    end_date: str | None = None,
    source: str = "yfinance",
    updated_at_utc: str | None = None,
) -> dict[str, Any]:
    effective_end = str(end_date or dt.date.today().isoformat())
    today_iso = dt.date.today().isoformat()
    updated_at = str(
        updated_at_utc
        or dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )
    summary: dict[str, Any] = {
        "tickers": [],
        "inserted_rows": 0,
        "updated_rows": 0,
        "invalid_tickers_removed": [],
        "skipped_invalid_tickers": [],
    }

    for ticker in tickers:
        symbol = str(ticker or "").upper().strip()
        if not symbol:
            continue
        status = store.get_yahoo_symbol_status(symbol) or {}
        if bool(status.get("is_invalid", False)):
            summary["skipped_invalid_tickers"].append(symbol)
            summary["tickers"].append(
                {
                    "ticker": symbol,
                    "fetched": False,
                    "rows": 0,
                    "windows": [],
                    "status": "SKIPPED_INVALID",
                }
            )
            continue

        earliest_date = store.earliest_market_history_date(symbol)
        last_date = store.latest_market_history_date(symbol)
        no_data_before_date = str(status.get("no_data_before_date", "") or "").strip() or None
        fetch_windows: list[tuple[str, str, str]] = []
        if earliest_date is None or pd.Timestamp(start_date) < pd.Timestamp(earliest_date):
            prepend_end = earliest_date or effective_end
            if pd.Timestamp(start_date) < pd.Timestamp(prepend_end):
                if not _window_known_empty(
                    start=str(start_date),
                    end=str(prepend_end),
                    no_data_before_date=no_data_before_date,
                ):
                    fetch_windows.append(
                        (
                            str(start_date),
                            str(prepend_end),
                            "prepend" if earliest_date is not None else "full",
                        )
                    )
        if last_date is None:
            if not fetch_windows:
                fetch_windows.append((str(start_date), str(effective_end), "full"))
        else:
            append_start = str((pd.Timestamp(last_date) + pd.Timedelta(days=1)).date())
            if pd.Timestamp(append_start) < pd.Timestamp(effective_end):
                fetch_windows.append((append_start, str(effective_end), "append"))

        all_rows: list[dict[str, Any]] = []
        empty_windows: list[dict[str, Any]] = []
        for fetch_start, fetch_end, kind in fetch_windows:
            frame = _download_history_frame(symbol, start=fetch_start, end=fetch_end)
            normalized = _normalize_download_frame(frame)
            if normalized.empty:
                empty_windows.append({"start": fetch_start, "end": fetch_end, "kind": kind})
                continue
            all_rows.extend(
                [
                    {
                        "ticker": symbol,
                        "date": pd.to_datetime(index).date().isoformat(),
                        "open": float(row["open"]),
                        "high": float(row["high"]),
                        "low": float(row["low"]),
                        "close": float(row["close"]),
                        "volume": float(row["volume"]),
                        "source": source,
                        "updated_at_utc": updated_at,
                    }
                    for index, row in normalized.iterrows()
                ]
            )
        rows = all_rows
        store.upsert_market_history(rows)
        learned_no_data_before = _resolve_no_data_before_date(
            start_date=str(start_date),
            earliest_cached_date=earliest_date,
            rows=rows,
            empty_windows=empty_windows,
            current_no_data_before_date=no_data_before_date,
        )
        if learned_no_data_before is not None or status:
            store.upsert_yahoo_symbol_status(
                [
                    {
                        "ticker": symbol,
                        "is_invalid": 0,
                        "invalid_reason": "",
                        "no_data_before_date": learned_no_data_before or no_data_before_date,
                        "checked_through_date": effective_end,
                        "updated_at_utc": updated_at,
                    }
                ]
            )

        if not rows and earliest_date is None and last_date is None and _recent_validation_is_empty(
            symbol,
            empty_windows=empty_windows,
            effective_end=effective_end,
            today_iso=today_iso,
        ):
            store.upsert_yahoo_symbol_status(
                [
                    {
                        "ticker": symbol,
                        "is_invalid": 1,
                        "invalid_reason": "No recent Yahoo data",
                        "no_data_before_date": learned_no_data_before or no_data_before_date,
                        "checked_through_date": effective_end,
                        "updated_at_utc": updated_at,
                    }
                ]
            )
            store.purge_tickers([symbol])
            summary["invalid_tickers_removed"].append(symbol)
        summary["tickers"].append(
            {
                "ticker": symbol,
                "fetched": bool(fetch_windows),
                "rows": len(rows),
                "windows": [{"start": start, "end": end, "kind": kind} for start, end, kind in fetch_windows],
                "empty_windows": empty_windows,
            }
        )
        summary["inserted_rows"] += len(rows)
    return summary


def _download_history_frame(symbol: str, *, start: str, end: str) -> pd.DataFrame:
    return yf.download(
        symbol,
        start=start,
        end=end,
        progress=False,
        auto_adjust=False,
        threads=False,
    )


def _normalize_download_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    if isinstance(frame.columns, pd.MultiIndex):
        level0 = {str(value) for value in frame.columns.get_level_values(0)}
        price_fields = {"Open", "High", "Low", "Close", "Volume", "Adj Close"}
        if level0 & price_fields:
            frame = frame.droplevel(1, axis=1)
        else:
            frame = frame.droplevel(0, axis=1)
    normalized = frame.rename(
        columns={
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
        }
    ).copy()
    return normalized[["open", "high", "low", "close", "volume"]].dropna(how="any")


def _window_known_empty(*, start: str, end: str, no_data_before_date: str | None) -> bool:
    if not no_data_before_date:
        return False
    return pd.Timestamp(start) < pd.Timestamp(no_data_before_date) and pd.Timestamp(end) <= pd.Timestamp(no_data_before_date)


def _resolve_no_data_before_date(
    *,
    start_date: str,
    earliest_cached_date: str | None,
    rows: Sequence[dict[str, Any]],
    empty_windows: Sequence[dict[str, Any]],
    current_no_data_before_date: str | None,
) -> str | None:
    candidate = str(current_no_data_before_date or "").strip() or None
    first_available = min((str(row.get("date", "")).strip() for row in rows if str(row.get("date", "")).strip()), default=None)
    if first_available and pd.Timestamp(start_date) < pd.Timestamp(first_available):
        candidate = _earlier_date(candidate, first_available)
    if earliest_cached_date and any(str(window.get("kind", "")).strip() == "prepend" for window in empty_windows):
        candidate = _earlier_date(candidate, str(earliest_cached_date))
    return candidate


def _earlier_date(left: str | None, right: str | None) -> str | None:
    if not left:
        return right
    if not right:
        return left
    return left if pd.Timestamp(left) <= pd.Timestamp(right) else right


def _recent_validation_is_empty(
    symbol: str,
    *,
    empty_windows: Sequence[dict[str, Any]],
    effective_end: str,
    today_iso: str,
) -> bool:
    validation_end = min(pd.Timestamp(effective_end), pd.Timestamp(today_iso))
    validation_start = str((validation_end - pd.Timedelta(days=90)).date())
    validation_end_str = str(validation_end.date())

    for window in empty_windows:
        if str(window.get("end", "")).strip() != validation_end_str:
            continue
        if pd.Timestamp(str(window.get("start", "")).strip()) <= pd.Timestamp(validation_start):
            return True

    frame = _download_history_frame(symbol, start=validation_start, end=validation_end_str)
    return _normalize_download_frame(frame).empty
