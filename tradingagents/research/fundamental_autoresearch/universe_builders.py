from __future__ import annotations

import csv
import json
from io import StringIO
from pathlib import Path
from typing import Any


_SP500_CONSTITUENTS_URL = (
    "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv"
)


def fetch_sp500_constituents(*, session=None, timeout: int = 30) -> list[dict[str, str]]:
    """Fetch S&P 500 constituents with GICS sector labels."""
    import requests

    client = session or requests.Session()
    response = client.get(_SP500_CONSTITUENTS_URL, timeout=timeout)
    response.raise_for_status()

    reader = csv.DictReader(StringIO(response.text))
    rows: list[dict[str, str]] = []
    for row in reader:
        raw_ticker = str(row.get("Symbol", "")).strip().upper().replace(".", "-")
        if not raw_ticker:
            continue
        rows.append(
            {
                "ticker": raw_ticker,
                "security": str(row.get("Security", "")).strip(),
                "sector": str(row.get("GICS Sector", "")).strip() or "Unknown",
            }
        )
    return rows


def fetch_liquidity_snapshot(
    tickers: list[str],
    *,
    period: str = "3mo",
    interval: str = "1d",
    batch_size: int = 50,
) -> list[dict[str, Any]]:
    """Fetch a batched yfinance liquidity snapshot for a ticker list."""
    import pandas as pd
    import yfinance as yf

    def _extract_series(data, symbol: str, field: str, multi: bool):
        try:
            if not multi:
                if field in data.columns:
                    return pd.to_numeric(data[field], errors="coerce")
                return None
            if isinstance(data.columns, pd.MultiIndex):
                if (symbol, field) in data.columns:
                    return pd.to_numeric(data[(symbol, field)], errors="coerce")
                if (field, symbol) in data.columns:
                    return pd.to_numeric(data[(field, symbol)], errors="coerce")
                if symbol in data.columns.get_level_values(0):
                    sub = data[symbol]
                    if field in sub.columns:
                        return pd.to_numeric(sub[field], errors="coerce")
            return None
        except Exception:
            return None

    snapshot: list[dict[str, Any]] = []
    for start in range(0, len(tickers), batch_size):
        batch = tickers[start : start + batch_size]
        multi = len(batch) > 1
        data = yf.download(
            batch if multi else batch[0],
            period=period,
            interval=interval,
            auto_adjust=False,
            progress=False,
            group_by="ticker",
            threads=False,
        )
        if data is None or data.empty:
            continue
        for ticker in batch:
            close_s = _extract_series(data, ticker, "Close", multi)
            volume_s = _extract_series(data, ticker, "Volume", multi)
            if close_s is None or volume_s is None:
                continue
            frame = pd.DataFrame({"close": close_s, "volume": volume_s}).dropna()
            if frame.empty:
                continue
            frame["dollar_volume"] = frame["close"] * frame["volume"]
            avg_dollar_volume = float(frame["dollar_volume"].tail(60).mean())
            last_close = float(frame["close"].iloc[-1])
            snapshot.append(
                {
                    "ticker": ticker,
                    "avg_dollar_volume_60d": avg_dollar_volume,
                    "last_close": last_close,
                }
            )
    return snapshot


def select_sector_balanced_universe(
    rows: list[dict[str, Any]],
    *,
    target_size: int = 250,
    per_sector_cap: int = 30,
    min_avg_dollar_volume: float = 20_000_000.0,
    min_last_close: float = 5.0,
) -> list[dict[str, Any]]:
    """Select a liquid, sector-balanced equity universe."""
    eligible = [
        row
        for row in rows
        if float(row.get("avg_dollar_volume_60d", 0.0) or 0.0) >= min_avg_dollar_volume
        and float(row.get("last_close", 0.0) or 0.0) >= min_last_close
    ]
    eligible.sort(key=lambda row: float(row["avg_dollar_volume_60d"]), reverse=True)

    selected: list[dict[str, Any]] = []
    sector_counts: dict[str, int] = {}
    used: set[str] = set()

    for row in eligible:
        sector = str(row.get("sector", "Unknown") or "Unknown")
        ticker = str(row["ticker"]).upper()
        if ticker in used:
            continue
        if sector_counts.get(sector, 0) >= per_sector_cap:
            continue
        selected.append(row)
        used.add(ticker)
        sector_counts[sector] = sector_counts.get(sector, 0) + 1
        if len(selected) >= target_size:
            return selected

    for row in eligible:
        ticker = str(row["ticker"]).upper()
        if ticker in used:
            continue
        selected.append(row)
        used.add(ticker)
        if len(selected) >= target_size:
            break

    return selected


def write_research_universe(
    entries: list[dict[str, Any]],
    *,
    universe_root: str,
    name: str,
    metadata: dict[str, Any] | None = None,
) -> Path:
    root = Path(universe_root)
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{name}.json"
    payload = {
        "name": name,
        "count": len(entries),
        "metadata": metadata or {},
        "entries": entries,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))
    return path


def load_research_universe(name: str, *, universe_root: str) -> dict[str, Any]:
    path = Path(universe_root) / f"{name}.json"
    if not path.exists():
        raise ValueError(f"Unknown research universe: {name}")
    return json.loads(path.read_text())


def build_liquid_core_v1(
    *,
    universe_root: str,
    target_size: int = 250,
    per_sector_cap: int = 30,
    min_avg_dollar_volume: float = 20_000_000.0,
    min_last_close: float = 5.0,
    session=None,
) -> Path:
    constituents = fetch_sp500_constituents(session=session)
    snapshot = fetch_liquidity_snapshot([row["ticker"] for row in constituents])
    liquidity_by_ticker = {row["ticker"]: row for row in snapshot}

    merged_rows: list[dict[str, Any]] = []
    for row in constituents:
        ticker = row["ticker"]
        liquidity = liquidity_by_ticker.get(ticker)
        if not liquidity:
            continue
        merged_rows.append(
            {
                "ticker": ticker,
                "security": row["security"],
                "sector": row["sector"],
                "avg_dollar_volume_60d": liquidity["avg_dollar_volume_60d"],
                "last_close": liquidity["last_close"],
            }
        )

    selected = select_sector_balanced_universe(
        merged_rows,
        target_size=target_size,
        per_sector_cap=per_sector_cap,
        min_avg_dollar_volume=min_avg_dollar_volume,
        min_last_close=min_last_close,
    )
    selected.sort(key=lambda row: row["ticker"])
    metadata = {
        "source": "sp500_constituents_plus_liquidity_snapshot",
        "target_size": target_size,
        "per_sector_cap": per_sector_cap,
        "min_avg_dollar_volume": min_avg_dollar_volume,
        "min_last_close": min_last_close,
    }
    return write_research_universe(
        selected,
        universe_root=universe_root,
        name="liquid_core_v1",
        metadata=metadata,
    )
