"""
Aeternus Core — Data Engine
Downloads OHLCV + VIX, caches to parquet, computes all indicators.

Every other module depends on this. Indicators computed here:
  SMAs:       sma3, sma10, sma20, sma50, sma200
  VIX:        vix, vix_sma10, vix_sma20
  ADR:        adr_14 (absolute $), adr_pct (% of close)
  FVG:        is_bull_fvg, is_bear_fvg, fvg_bull, fvg_bear, fvg_ratio
  Volume:     vol_sma20
  SMA slope:  slope_10, slope_20 (5-bar change, normalized by price)
"""

import os
import time
import pandas as pd
import numpy as np
import yfinance as yf
from . import config as cfg


def _download_raw(ticker: str, start: str) -> pd.DataFrame:
    """Download raw OHLCV from yfinance. No indicators, just clean columns."""
    buf_start = (pd.to_datetime(start) - pd.DateOffset(days=cfg.WARMUP_DAYS)).strftime("%Y-%m-%d")

    raw = yf.download(ticker, start=buf_start, progress=False, auto_adjust=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    raw.reset_index(inplace=True)
    raw.columns = [c.lower() for c in raw.columns]
    if 'datetime' in raw.columns:
        raw.rename(columns={'datetime': 'date'}, inplace=True)
    raw['date'] = pd.to_datetime(raw['date'])

    # Drop adjusted close — use raw prices only
    if 'adj close' in raw.columns:
        raw.drop(columns=['adj close'], inplace=True)

    return raw[['date', 'open', 'high', 'low', 'close', 'volume']].copy()


def _download_vix(start: str) -> pd.DataFrame:
    """Download VIX close for fear regime detection."""
    buf_start = (pd.to_datetime(start) - pd.DateOffset(days=cfg.WARMUP_DAYS)).strftime("%Y-%m-%d")

    vix = yf.download("^VIX", start=buf_start, progress=False, auto_adjust=False)
    if isinstance(vix.columns, pd.MultiIndex):
        vix.columns = vix.columns.get_level_values(0)
    vix.reset_index(inplace=True)
    vix.columns = [c.lower() for c in vix.columns]
    if 'datetime' in vix.columns:
        vix.rename(columns={'datetime': 'date'}, inplace=True)
    vix['date'] = pd.to_datetime(vix['date'])

    return vix[['date', 'close']].rename(columns={'close': 'vix'})


def _compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Compute all indicators on a merged OHLCV+VIX dataframe."""

    # ── SMAs ──────────────────────────────────────────────────────────────────
    df['sma3']   = df['close'].rolling(3).mean()
    df['sma10']  = df['close'].rolling(10).mean()
    df['sma20']  = df['close'].rolling(20).mean()
    df['sma50']  = df['close'].rolling(50).mean()
    df['sma200'] = df['close'].rolling(200).mean()

    # ── VIX SMAs ──────────────────────────────────────────────────────────────
    if 'vix' in df.columns:
        df['vix_sma10'] = df['vix'].rolling(10).mean()
        df['vix_sma20'] = df['vix'].rolling(20).mean()
    else:
        df['vix'] = np.nan
        df['vix_sma10'] = np.nan
        df['vix_sma20'] = np.nan

    # ── ADR (Average Daily Range) ─────────────────────────────────────────────
    df['adr_14'] = (df['high'] - df['low']).rolling(cfg.ADR_WINDOW).mean()
    df['adr_pct'] = df['adr_14'] / df['close']

    # ── Volume average ────────────────────────────────────────────────────────
    df['vol_sma20'] = df['volume'].rolling(cfg.VOLUME_AVG_WINDOW).mean()

    # ── SMA Slope (normalized by price) ───────────────────────────────────────
    lb = cfg.SMA_SLOPE_LOOKBACK
    df['slope_10'] = (df['sma10'] - df['sma10'].shift(lb)) / (df['close'] * lb)
    df['slope_20'] = (df['sma20'] - df['sma20'].shift(lb)) / (df['close'] * lb)

    # ── FVG Detection ─────────────────────────────────────────────────────────
    hi = df['high'].values
    lo = df['low'].values
    n  = len(df)

    bull_fvg = np.zeros(n)
    bear_fvg = np.zeros(n)
    for i in range(2, n):
        if hi[i - 2] < lo[i]:    # 3-bar gap up (bullish)
            bull_fvg[i] = 1
        if lo[i - 2] > hi[i]:    # 3-bar gap down (bearish)
            bear_fvg[i] = 1

    df['is_bull_fvg'] = bull_fvg
    df['is_bear_fvg'] = bear_fvg

    # Rolling FVG counts and ratio
    w = cfg.FVG_RATIO_WINDOW
    df['fvg_bull'] = pd.Series(bull_fvg).rolling(w).sum().values
    df['fvg_bear'] = pd.Series(bear_fvg).rolling(w).sum().values
    denom = df['fvg_bull'] + df['fvg_bear']
    df['fvg_ratio'] = np.where(denom == 0, np.nan, df['fvg_bull'] / denom)

    return df


def _cache_path(ticker: str) -> str:
    os.makedirs(cfg.CACHE_DIR, exist_ok=True)
    return os.path.join(cfg.CACHE_DIR, f"{ticker}.csv")


def _is_cache_fresh(path: str) -> bool:
    if not os.path.exists(path):
        return False
    age_hours = (time.time() - os.path.getmtime(path)) / 3600
    return age_hours < (cfg.CACHE_STALE_DAYS * 24)


def load(ticker: str, start: str = None) -> pd.DataFrame:
    """
    Load a fully-computed indicator DataFrame for a ticker.
    Uses parquet cache. Re-downloads if stale.

    Returns DataFrame with date index trimmed to >= start,
    but with indicators warm (computed from warmup window).
    """
    if start is None:
        start = cfg.START_DATE

    cache = _cache_path(ticker)

    if _is_cache_fresh(cache):
        df = pd.read_csv(cache, parse_dates=['date'])
    else:
        raw = _download_raw(ticker, start)
        vix = _download_vix(start)
        df  = pd.merge(raw, vix, on='date', how='left')
        df  = _compute_indicators(df)
        df.to_csv(cache, index=False)

    # Trim to start date (indicators already warm from buffer)
    df = df[df['date'] >= pd.to_datetime(start)].reset_index(drop=True)
    return df


def load_universe(tickers: list = None, start: str = None) -> dict:
    """
    Load data for multiple tickers. Returns {ticker: DataFrame}.
    """
    if tickers is None:
        tickers = cfg.UNIVERSE
    if start is None:
        start = cfg.START_DATE

    data = {}
    for t in tickers:
        try:
            data[t] = load(t, start)
        except Exception as e:
            print(f"  WARNING: Failed to load {t}: {e}")
    return data
