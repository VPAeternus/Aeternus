"""Current-constituent builders for broad technical screening universes."""

from __future__ import annotations

import datetime as dt
import json
from io import StringIO
from pathlib import Path
from typing import Iterable

import pandas as pd
import requests
import urllib3


_SOURCE_URLS = {
    "SPY": "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
    "QQQ": "https://en.wikipedia.org/wiki/Nasdaq-100",
    "DOW": "https://en.wikipedia.org/wiki/Dow_Jones_Industrial_Average",
}


def fetch_current_universe(
    sources: Iterable[str],
    *,
    as_of_date: str | None = None,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    fetched_at = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    effective_date = str(as_of_date or dt.date.today().isoformat())
    for source in sources:
        normalized_source = str(source or "").upper().strip()
        if normalized_source not in _SOURCE_URLS:
            raise ValueError(f"Unsupported source index: {source}")
        frame = _select_source_table(normalized_source, _read_source_tables(_SOURCE_URLS[normalized_source]))
        for _, row in frame.iterrows():
            ticker = normalize_current_universe_ticker(
                _first_present(row, ("Symbol", "Ticker", "Company", "Security"))
            )
            if not ticker:
                continue
            rows.append(
                {
                    "source_index": normalized_source,
                    "ticker": ticker,
                    "company_name": _first_present(row, ("Security", "Company", "Name")) or ticker,
                    "sector": _first_present(row, ("GICS Sector", "Sector", "Industry")) or "",
                    "as_of_date": effective_date,
                    "fetched_at_utc": fetched_at,
                }
            )
    return rows


def dedupe_current_universe_tickers(rows: Iterable[dict[str, str]]) -> list[str]:
    return sorted(
        {
            normalize_current_universe_ticker(row.get("ticker", ""))
            for row in rows
            if normalize_current_universe_ticker(row.get("ticker", ""))
        }
    )


def persist_current_universe_snapshot(rows: list[dict[str, str]], path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {"count": len(rows), "rows": rows}
    target.write_text(json.dumps(payload, indent=2))
    return target


def normalize_current_universe_ticker(value: str) -> str:
    symbol = str(value or "").strip().upper()
    if not symbol:
        return ""
    return symbol.replace(".", "-")


def _first_present(row: pd.Series, candidates: tuple[str, ...]) -> str:
    for candidate in candidates:
        if candidate in row.index:
            value = str(row.get(candidate, "") or "").strip()
            if value:
                return value
    return ""


def _select_source_table(source: str, tables: list[pd.DataFrame]) -> pd.DataFrame:
    if not tables:
        return pd.DataFrame()
    preferred_columns = {
        "SPY": {"Symbol", "Security"},
        "QQQ": {"Ticker", "Company"},
        "DOW": {"Symbol", "Company"},
    }.get(source, set())
    for frame in tables:
        if preferred_columns.issubset(set(frame.columns)):
            return frame
    return tables[0]


def _read_source_tables(url: str) -> list[pd.DataFrame]:
    try:
        return pd.read_html(url)
    except Exception:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        response = requests.get(
            url,
            timeout=30,
            verify=False,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        response.raise_for_status()
        return pd.read_html(StringIO(response.text))
