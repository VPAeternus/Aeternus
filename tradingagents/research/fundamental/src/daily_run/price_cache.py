from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping
from collections import defaultdict

from .review_list_filter import fetch_review_price_rows, load_cached_review_price_rows, store_review_price_rows


def _ticker(value: Any) -> str:
    return str(value or "").upper().replace(".", "-").replace("/", "-").strip()


@dataclass(frozen=True)
class PriceCacheResult:
    rows: list[dict[str, Any]]
    summary: dict[str, Any]
    artifacts: dict[str, str]


def load_or_fetch_price_rows(
    tickers: list[str],
    *,
    start: str,
    end: str,
    cache_paths: list[Path],
    price_provider: Callable[..., list[dict[str, Any]]],
    output_root: Path,
    quarter: str,
    as_of: str,
    batch_size: int = 200,
    allow_live_fetch: bool = True,
    shared_cache_root: Path | None = None,
    required_start_by_ticker: Mapping[str, Any] | None = None,
) -> PriceCacheResult:
    wanted = sorted({_ticker(ticker) for ticker in tickers if _ticker(ticker)})
    cached_rows = load_cached_review_price_rows(cache_paths, tickers=wanted, start=start, end=end)
    required_starts = {
        _ticker(ticker): str(value)[:10]
        for ticker, value in (required_start_by_ticker or {}).items()
        if _ticker(ticker) and str(value or "").strip()
    }
    cached_tickers = {_ticker(row.get("ticker")) for row in cached_rows}
    usable_cached_tickers = _usable_price_tickers(cached_rows, wanted=wanted, required_starts=required_starts, default_start=start)
    missing_tickers = [ticker for ticker in wanted if ticker not in usable_cached_tickers]
    partial_cache_tickers = sorted(ticker for ticker in cached_tickers if ticker not in usable_cached_tickers)
    live_rows: list[dict[str, Any]] = []
    artifacts: dict[str, str] = {}

    if missing_tickers and allow_live_fetch:
        tickers_by_start: dict[str, list[str]] = defaultdict(list)
        for ticker in missing_tickers:
            tickers_by_start[required_starts.get(ticker, start)].append(ticker)
        for fetch_start, group in sorted(tickers_by_start.items()):
            live_rows.extend(
                fetch_review_price_rows(
                    group,
                    start=fetch_start,
                    end=end,
                    price_provider=price_provider,
                    batch_size=batch_size,
                )
            )
        live_tickers = {_ticker(row.get("ticker")) for row in live_rows}
        if live_rows:
            for label, root in {"daily_live_price_run_cache": output_root, "daily_live_price_shared_cache": shared_cache_root}.items():
                if root is None:
                    continue
                try:
                    artifacts[label] = str(store_review_price_rows(live_rows, output_root=root, quarter=quarter, as_of=as_of))
                except Exception as exc:  # noqa: BLE001 - cache write should not discard usable live prices.
                    artifacts[f"{label}_error"] = str(exc)
    else:
        live_tickers = set()

    rows = [*cached_rows, *live_rows]
    served_tickers = _usable_price_tickers(rows, wanted=wanted, required_starts=required_starts, default_start=start)
    still_missing = [ticker for ticker in wanted if ticker not in served_tickers]
    summary = {
        "daily_price_requested_ticker_count": len(wanted),
        "daily_price_cached_ticker_count": len(cached_tickers),
        "daily_price_cached_usable_ticker_count": len(usable_cached_tickers),
        "daily_price_partial_cache_ticker_count": len(partial_cache_tickers),
        "daily_price_partial_cache_tickers": partial_cache_tickers[:50],
        "daily_price_missing_cache_ticker_count": len(missing_tickers),
        "daily_price_live_fetch_allowed": bool(allow_live_fetch),
        "daily_price_live_fetch_ticker_count": len(live_tickers),
        "daily_price_live_fetch_row_count": len(live_rows),
        "daily_price_still_missing_ticker_count": len(still_missing),
        "daily_price_still_missing_tickers": still_missing[:50],
        "daily_price_start": start,
        "daily_price_end_exclusive": end,
        "daily_price_cache_paths": [str(path) for path in cache_paths],
    }
    return PriceCacheResult(rows=rows, summary=summary, artifacts=artifacts)


def _usable_price_tickers(
    rows: list[dict[str, Any]],
    *,
    wanted: list[str],
    required_starts: Mapping[str, str],
    default_start: str,
) -> set[str]:
    wanted_set = set(wanted)
    usable: set[str] = set()
    for row in rows:
        ticker = _ticker(row.get("ticker"))
        if ticker not in wanted_set:
            continue
        date_text = str(row.get("date") or "")[:10]
        required_start = required_starts.get(ticker, default_start)
        if required_start <= date_text and row.get("open") not in {None, ""}:
            usable.add(ticker)
    return usable
