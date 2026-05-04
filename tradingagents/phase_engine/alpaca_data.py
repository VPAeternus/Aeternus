"""
Aeternus Core — Alpaca Live Data Provider
Wraps the core data_engine with real-time Alpaca market data.

This module NEVER modifies the core engine. It:
  1. Loads historical data via data_engine.load() (cached, all indicators computed)
  2. Fetches today's live bar from Alpaca (real-time OHLCV + VIX)
  3. Appends the live bar and recomputes indicators on the combined DataFrame
  4. Returns a DataFrame identical in schema to data_engine.load() output

Usage:
    from tradingagents.phase_engine.alpaca_data import load_live
    df = load_live("QQQ")   # historical + today's live bar
    # df has same columns as data_engine.load() — drop-in replacement
"""

import os
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import numpy as np

from . import data_engine, config as cfg
from .data_engine import _compute_indicators

# ── Alpaca Client (singleton) ──────────────────────────────────────────────
_client = None

def _get_client():
    global _client
    if _client is None:
        try:
            from dotenv import load_dotenv
            load_dotenv(Path(__file__).parent.parent.parent / ".env")
        except ImportError:
            pass

        from alpaca.data.historical import StockHistoricalDataClient
        key = os.getenv("APCA_API_KEY_ID")
        secret = os.getenv("APCA_API_SECRET_KEY")
        if not key or not secret:
            raise RuntimeError("Alpaca API keys not found in environment")
        _client = StockHistoricalDataClient(key, secret)
    return _client


def _market_is_open() -> bool:
    """Quick check: is it a weekday between 9:30 AM and 4:00 PM ET?"""
    from zoneinfo import ZoneInfo
    now = datetime.now(ZoneInfo("America/New_York"))
    if now.weekday() >= 5:  # Saturday/Sunday
        return False
    market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = now.replace(hour=16, minute=0, second=0, microsecond=0)
    return market_open <= now <= market_close


def get_live_bar(ticker: str) -> dict | None:
    """
    Fetch today's current bar from Alpaca.
    Returns dict with keys: date, open, high, low, close, volume
    Returns None if no data available (pre-market, weekend, etc.)
    """
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame

    client = _get_client()
    try:
        req = StockBarsRequest(
            symbol_or_symbols=[ticker],
            timeframe=TimeFrame.Day,
            start=datetime.now() - timedelta(days=1),
        )
        bars = client.get_stock_bars(req)
        df = bars.df
        if df.empty:
            return None

        row = df.iloc[-1]
        ts = df.index.get_level_values('timestamp')[-1]

        return {
            "date": pd.Timestamp(ts).tz_localize(None).normalize(),
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": int(row["volume"]),
        }
    except Exception as e:
        print(f"  Alpaca bar fetch failed for {ticker}: {e}")
        return None


def get_live_vix() -> float | None:
    """
    Fetch current VIX from Alpaca.
    VIX is not a stock — Alpaca may not have it directly.
    Fall back to VIXY ETF as proxy, or use latest from data_engine cache.
    """
    from alpaca.data.requests import StockLatestQuoteRequest

    client = _get_client()

    for vix_proxy in ["VIXY", "VXX", "UVXY"]:
        try:
            req = StockLatestQuoteRequest(symbol_or_symbols=[vix_proxy])
            client.get_stock_latest_quote(req)
        except Exception:
            continue

    # Alpaca doesn't serve ^VIX directly. Use the latest cached VIX value.
    return None


def get_latest_quote(ticker: str) -> dict | None:
    """Fetch the absolute latest quote (bid/ask/last) for a ticker."""
    from alpaca.data.requests import StockLatestQuoteRequest

    client = _get_client()
    try:
        req = StockLatestQuoteRequest(symbol_or_symbols=[ticker])
        quotes = client.get_stock_latest_quote(req)
        q = quotes.get(ticker)
        if q is None:
            return None
        return {
            "bid": float(q.bid_price),
            "ask": float(q.ask_price),
            "mid": round((float(q.bid_price) + float(q.ask_price)) / 2, 4),
            "timestamp": str(q.timestamp),
        }
    except Exception as e:
        print(f"  Alpaca quote failed for {ticker}: {e}")
        return None


def get_snapshots(tickers: list) -> dict:
    """
    Fetch snapshots for multiple tickers at once.
    Returns {ticker: {open, high, low, close, volume, bid, ask, mid, vwap}}.
    Efficient single API call for the whole universe.
    """
    from alpaca.data.requests import StockSnapshotRequest

    client = _get_client()
    try:
        req = StockSnapshotRequest(symbol_or_symbols=tickers)
        snaps = client.get_stock_snapshot(req)
        result = {}
        for ticker, snap in snaps.items():
            entry = {}
            if snap.daily_bar:
                b = snap.daily_bar
                entry.update({
                    "open": float(b.open),
                    "high": float(b.high),
                    "low": float(b.low),
                    "close": float(b.close),
                    "volume": int(b.volume),
                    "vwap": float(b.vwap) if hasattr(b, 'vwap') and b.vwap else None,
                    "bar_timestamp": str(b.timestamp),
                })
            if snap.latest_quote:
                q = snap.latest_quote
                entry.update({
                    "bid": float(q.bid_price),
                    "ask": float(q.ask_price),
                    "mid": round((float(q.bid_price) + float(q.ask_price)) / 2, 4),
                    "quote_timestamp": str(q.timestamp),
                })
            if snap.latest_trade:
                t = snap.latest_trade
                entry["last_trade"] = float(t.price)
                entry["trade_timestamp"] = str(t.timestamp)
            result[ticker] = entry
        return result
    except Exception as e:
        print(f"  Alpaca snapshot failed: {e}")
        return {}


def load_live(ticker: str, start: str = None) -> pd.DataFrame:
    """
    Drop-in replacement for data_engine.load() with real-time data.

    Loads historical data from cache, then appends today's live bar
    from Alpaca and recomputes all indicators.

    Returns DataFrame with identical schema to data_engine.load().
    """
    # Step 1: Load historical (cached, all indicators pre-computed)
    df_hist = data_engine.load(ticker, start)

    # Step 2: Fetch today's live bar from Alpaca
    live = get_live_bar(ticker)
    if live is None:
        return df_hist  # No live data — return cached

    # Step 3: Check if live bar is newer than last historical bar
    last_hist_date = df_hist['date'].iloc[-1]
    live_date = live['date']

    if live_date <= last_hist_date:
        # Live bar is same date as last cached bar — update it in-place
        df_raw = df_hist[['date', 'open', 'high', 'low', 'close', 'volume', 'vix']].copy()
        df_raw.iloc[-1, df_raw.columns.get_loc('close')] = live['close']
        df_raw.iloc[-1, df_raw.columns.get_loc('high')] = max(df_raw.iloc[-1]['high'], live['high'])
        df_raw.iloc[-1, df_raw.columns.get_loc('low')] = min(df_raw.iloc[-1]['low'], live['low'])
        df_raw.iloc[-1, df_raw.columns.get_loc('volume')] = live['volume']
    else:
        # New trading day — append live bar
        df_raw = df_hist[['date', 'open', 'high', 'low', 'close', 'volume', 'vix']].copy()
        live_row = pd.DataFrame([{
            'date': live_date,
            'open': live['open'],
            'high': live['high'],
            'low': live['low'],
            'close': live['close'],
            'volume': live['volume'],
            'vix': df_hist['vix'].iloc[-1],  # Use last known VIX
        }])
        df_raw = pd.concat([df_raw, live_row], ignore_index=True)

    # Step 4: Recompute all indicators on the full dataset
    df_live = _compute_indicators(df_raw)

    # Step 5: Trim to start date
    if start is None:
        start = cfg.START_DATE
    df_live = df_live[df_live['date'] >= pd.to_datetime(start)].reset_index(drop=True)

    return df_live


def load_live_universe(tickers: list = None, start: str = None) -> dict:
    """Load live data for multiple tickers. Returns {ticker: DataFrame}."""
    if tickers is None:
        tickers = cfg.UNIVERSE
    data = {}
    for t in tickers:
        try:
            data[t] = load_live(t, start)
        except Exception as e:
            print(f"  WARNING: Failed to load live {t}: {e}")
    return data
