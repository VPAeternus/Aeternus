"""Shared daily OHLCV cache for dealflow collectors.

This keeps yfinance out of hot-path collectors as much as possible by:
- loading existing per-symbol history from disk
- refreshing only a recent window for cached symbols
- fetching a longer window only for missing/undersized symbols
"""

from __future__ import annotations

import contextlib
import io
from pathlib import Path
from typing import Callable, Dict, Iterable, Optional, Sequence

import pandas as pd
import yfinance as yf


DEFAULT_MARKET_CACHE_ROOT = Path("eval_results") / "deal_flow" / "market_cache"
_OHLCV_COLUMNS = ["Open", "High", "Low", "Close", "Adj Close", "Volume"]


def market_cache_path(symbol: str, cache_root: Path | str = DEFAULT_MARKET_CACHE_ROOT) -> Path:
    normalized = str(symbol).upper().strip()
    safe = normalized.replace("^", "_IDX_").replace("/", "_").replace(":", "_")
    return Path(cache_root) / f"{safe}.csv"


def load_symbol_history(symbol: str, cache_root: Path | str = DEFAULT_MARKET_CACHE_ROOT) -> Optional[pd.DataFrame]:
    path = market_cache_path(symbol, cache_root=cache_root)
    if not path.exists():
        return None
    try:
        frame = pd.read_csv(path, index_col=0, parse_dates=True)
    except Exception:
        return None
    if frame.empty:
        return None
    frame = frame.loc[:, [col for col in _OHLCV_COLUMNS if col in frame.columns]]
    if frame.empty:
        return None
    frame = frame.sort_index()
    frame.index = pd.to_datetime(frame.index)
    return frame


def save_symbol_history(
    symbol: str,
    frame: pd.DataFrame,
    cache_root: Path | str = DEFAULT_MARKET_CACHE_ROOT,
) -> Path:
    path = market_cache_path(symbol, cache_root=cache_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    trimmed = frame.loc[:, [col for col in _OHLCV_COLUMNS if col in frame.columns]].sort_index()
    trimmed.to_csv(path)
    return path


def ensure_ohlcv_history(
    symbols: Sequence[str],
    *,
    min_bars: int,
    cache_root: Path | str = DEFAULT_MARKET_CACHE_ROOT,
    refresh_period: str = "30d",
    full_period: Optional[str] = None,
    batch_size: int = 10,
    fetch_batch: Optional[Callable[[Sequence[str], str], Dict[str, pd.DataFrame]]] = None,
) -> Dict[str, pd.DataFrame]:
    deduped = [symbol for symbol in dict.fromkeys(str(sym).upper().strip() for sym in symbols) if symbol]
    ready: Dict[str, pd.DataFrame] = {}
    refresh: list[str] = []
    full_fetch: list[str] = []

    for symbol in deduped:
        existing = load_symbol_history(symbol, cache_root=cache_root)
        if existing is None or len(existing) < int(min_bars):
            full_fetch.append(symbol)
            continue
        if _cache_is_stale(existing):
            refresh.append(symbol)
        ready[symbol] = existing

    fetcher = fetch_batch or _default_fetch_batch
    if refresh:
        for batch in _chunked(refresh, batch_size):
            fresh_frames = _normalize_fetch_result(fetcher(batch, refresh_period), batch)
            for symbol in batch:
                existing = ready.get(symbol)
                fresh = fresh_frames.get(symbol)
                if existing is None:
                    continue
                if fresh is None or fresh.empty:
                    continue
                merged = _merge_frames(existing, fresh)
                save_symbol_history(symbol, merged, cache_root=cache_root)
                ready[symbol] = merged

    if full_fetch:
        period = full_period or f"{max(int(min_bars) + 30, 430)}d"
        for batch in _chunked(full_fetch, batch_size):
            fresh_frames = _normalize_fetch_result(fetcher(batch, period), batch)
            for symbol in batch:
                fresh = fresh_frames.get(symbol)
                if fresh is None or fresh.empty:
                    continue
                merged = _merge_frames(load_symbol_history(symbol, cache_root=cache_root), fresh)
                save_symbol_history(symbol, merged, cache_root=cache_root)
                ready[symbol] = merged

    return ready


def _default_fetch_batch(symbols: Sequence[str], period: str) -> Dict[str, pd.DataFrame]:
    target: object = symbols[0] if len(symbols) == 1 else list(symbols)
    with _suppress_yf_noise():
        frame = yf.download(
            target,
            period=period,
            interval="1d",
            auto_adjust=False,
            progress=False,
            group_by="ticker",
            threads=False,
        )
    return _split_download_frame(frame, symbols)


def _normalize_fetch_result(
    result: Optional[object],
    symbols: Sequence[str],
) -> Dict[str, pd.DataFrame]:
    if result is None:
        return {}
    if isinstance(result, dict):
        return {
            str(symbol).upper().strip(): frame
            for symbol, frame in result.items()
            if isinstance(frame, pd.DataFrame) and not frame.empty
        }
    if isinstance(result, pd.DataFrame):
        return _split_download_frame(result, symbols)
    return {}


def _split_download_frame(frame: Optional[pd.DataFrame], symbols: Sequence[str]) -> Dict[str, pd.DataFrame]:
    if frame is None or frame.empty:
        return {}

    symbol_list = [str(symbol).upper().strip() for symbol in symbols if str(symbol).strip()]
    frames: Dict[str, pd.DataFrame] = {}
    for symbol in symbol_list:
        subframe = _extract_symbol_frame(frame, symbol)
        if subframe is not None and not subframe.empty:
            frames[symbol] = subframe
    return frames


def _extract_symbol_frame(frame: pd.DataFrame, symbol: str) -> Optional[pd.DataFrame]:
    try:
        if isinstance(frame.columns, pd.MultiIndex):
            cols = []
            for field in _OHLCV_COLUMNS:
                if (symbol, field) in frame.columns:
                    cols.append((field, pd.to_numeric(frame[(symbol, field)], errors="coerce")))
                elif (field, symbol) in frame.columns:
                    cols.append((field, pd.to_numeric(frame[(field, symbol)], errors="coerce")))
            if not cols:
                return None
            out = pd.DataFrame({field: series for field, series in cols}).dropna(how="all")
            return out

        out = frame.loc[:, [col for col in _OHLCV_COLUMNS if col in frame.columns]].apply(
            pd.to_numeric, errors="coerce"
        )
        return out.dropna(how="all")
    except Exception:
        return None


def _cache_is_stale(frame: pd.DataFrame) -> bool:
    if frame.empty:
        return True
    last = pd.Timestamp(frame.index.max())
    if last.tzinfo is not None:
        last = last.tz_convert(None)
    cutoff = pd.Timestamp.now("UTC").tz_localize(None).normalize() - pd.Timedelta(days=3)
    return last < cutoff


def _merge_frames(existing: Optional[pd.DataFrame], fresh: pd.DataFrame) -> pd.DataFrame:
    if existing is None or existing.empty:
        merged = fresh.copy()
    else:
        merged = pd.concat([existing, fresh]).sort_index()
        merged = merged[~merged.index.duplicated(keep="last")]
    return merged.loc[:, [col for col in _OHLCV_COLUMNS if col in merged.columns]]


def _chunked(values: Sequence[str], size: int) -> Iterable[list[str]]:
    step = max(1, int(size))
    for idx in range(0, len(values), step):
        yield list(values[idx : idx + step])


@contextlib.contextmanager
def _suppress_yf_noise():
    sink = io.StringIO()
    with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
        yield
