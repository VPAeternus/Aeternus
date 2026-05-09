"""
Local price cache for CSP/CC scanner.
Stores OHLCV data per ticker in research/cache/{ticker}.csv.
On each call: fetches only new bars since last cached date and appends.
"""

import warnings
warnings.filterwarnings('ignore')

import os
import pandas as pd
import yfinance as yf
from datetime import date, timedelta

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cache')


def _cache_path(ticker: str) -> str:
    return os.path.join(CACHE_DIR, f"{ticker.replace('-', '_')}.csv")


def get_prices(ticker: str) -> pd.DataFrame | None:
    """
    Returns OHLCV DataFrame for ticker, using local cache.
    Historical bars (up to yesterday) are cached. Today's bar is always
    fetched live so volume is never stale/partial.
    Columns: Open, High, Low, Close, Volume (index = Date).
    """
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = _cache_path(ticker)
    today     = date.today()
    yesterday = today - timedelta(days=1)

    cached = None
    if os.path.exists(path):
        try:
            cached = pd.read_csv(path, index_col='Date', parse_dates=True)
            # Drop today's bar from cache — always re-fetch it live
            cached = cached[cached.index.date < today]
        except Exception:
            cached = None

    if cached is not None and not cached.empty:
        last_cached = cached.index[-1].date()

        # Fetch everything from (last_cached + 1) onward, including today
        start = (last_cached + timedelta(days=1)).strftime('%Y-%m-%d')
        new = _download(ticker, start=start)

        if new is not None and not new.empty:
            # Cache only historical bars (not today) to avoid stale volume
            to_cache = new[new.index.date < today]
            if not to_cache.empty:
                combined = pd.concat([cached, to_cache])
                combined = combined[~combined.index.duplicated(keep='last')]
                combined.sort_index(inplace=True)
                combined.to_csv(path)
            else:
                combined = cached.copy()

            # Return full data including today's live bar
            full = pd.concat([combined, new[new.index.date >= today]])
            full = full[~full.index.duplicated(keep='last')]
            return full.sort_index()

        # No new data (weekend/holiday) — fetch today live anyway
        today_data = _download(ticker, start=today.strftime('%Y-%m-%d'))
        if today_data is not None and not today_data.empty:
            full = pd.concat([cached, today_data])
            return full[~full.index.duplicated(keep='last')].sort_index()

        return cached

    # No cache — full download, cache historical only
    full = _download(ticker, period='max')
    if full is not None and not full.empty:
        to_cache = full[full.index.date < today]
        if not to_cache.empty:
            to_cache.to_csv(path)
    return full


def _download(ticker: str, period: str = None, start: str = None) -> pd.DataFrame | None:
    try:
        kwargs = dict(auto_adjust=False, progress=False)
        if start:
            kwargs['start'] = start
        else:
            kwargs['period'] = period or 'max'

        raw = yf.download(ticker, **kwargs)
        if raw.empty:
            return None
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)

        raw.index.name = 'Date'
        return raw[['Open', 'High', 'Low', 'Close', 'Volume']].copy()
    except Exception:
        return None


def clear_cache(ticker: str = None):
    """Delete cache for one ticker or all tickers."""
    if ticker:
        path = _cache_path(ticker)
        if os.path.exists(path):
            os.remove(path)
    else:
        import shutil
        if os.path.exists(CACHE_DIR):
            shutil.rmtree(CACHE_DIR)
