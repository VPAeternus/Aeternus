from __future__ import annotations

from pathlib import Path

import pandas as pd


def _yf_ticker(ticker: str) -> str:
    return ticker.replace(".", "-")


def _forward_return(series: pd.Series, start_index: int, horizon: int) -> float | None:
    target_index = start_index + horizon
    if target_index >= len(series):
        return None
    base = float(series.iloc[start_index])
    target = float(series.iloc[target_index])
    if base == 0:
        return None
    return (target / base) - 1.0


def attach_forward_returns(rows: list[dict], *, close_map: dict[str, pd.Series]) -> list[dict]:
    enriched_rows: list[dict] = []
    for row in rows:
        ticker = row.get("ticker")
        series = close_map.get(str(ticker))
        enriched = dict(row)
        for horizon in (20, 60, 120, 252):
            enriched[f"return_{horizon}d"] = None

        if series is None or series.empty:
            enriched_rows.append(enriched)
            continue

        effective_date = pd.Timestamp(str(row["effective_market_date"]))
        valid_index = series.index[series.index >= effective_date]
        if len(valid_index) == 0:
            enriched_rows.append(enriched)
            continue
        start_label = valid_index[0]
        start_pos = series.index.get_loc(start_label)
        if isinstance(start_pos, slice):
            start_pos = start_pos.start
        if isinstance(start_pos, (list, tuple)):
            start_pos = start_pos[0]

        for horizon in (20, 60, 120, 252):
            enriched[f"return_{horizon}d"] = _forward_return(series, int(start_pos), horizon)

        enriched_rows.append(enriched)
    return enriched_rows


def enrich_prepared_rows_with_market_data(rows: list[dict], *, close_map: dict[str, pd.Series] | None = None) -> list[dict]:
    if close_map is None:
        close_map = download_adjusted_close_history(rows)
    return attach_forward_returns(rows, close_map=close_map)


def download_adjusted_close_history(rows: list[dict]) -> dict[str, pd.Series]:
    import yfinance as yf

    tickers = sorted({str(row["ticker"]) for row in rows if row.get("ticker")})
    if not tickers:
        return {}
    yf_tickers = {_yf_ticker(ticker): ticker for ticker in tickers}

    start = min(pd.Timestamp(str(row["effective_market_date"])) for row in rows).date().isoformat()
    frame = yf.download(
        tickers=sorted(yf_tickers.keys()),
        start=start,
        auto_adjust=True,
        progress=False,
        group_by="column",
        threads=False,
    )
    if frame is None or frame.empty:
        return {}

    close_map: dict[str, pd.Series] = {}
    if isinstance(frame.columns, pd.MultiIndex):
        if "Close" in frame.columns.get_level_values(0):
            close_frame = frame["Close"]
        else:
            close_frame = frame.xs("Close", axis=1, level=0, drop_level=False)
        for yf_ticker, original_ticker in yf_tickers.items():
            if yf_ticker in close_frame:
                close_map[original_ticker] = close_frame[yf_ticker].dropna()
    else:
        first_original_ticker = yf_tickers[next(iter(yf_tickers.keys()))]
        close_map[first_original_ticker] = frame["Close"].dropna()
    return close_map
