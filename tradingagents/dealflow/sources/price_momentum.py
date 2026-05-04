"""Deterministic price-momentum signal family for Deal Flow.

v2 — F=MA scoring (Force = Mass × Acceleration).

Components (percentile-ranked cross-sectionally):
  Velocity  (20%)  60d return
  Accel     (30%)  SMA20 slope change over 20d windows (2nd derivative)
  Mass      (20%)  relative dollar volume (5d avg / 60d avg)
  Force     (20%)  raw mass × raw acceleration interaction
  RelStr    (10%)  60d return minus SPY 60d return

Validated via IC backtest (52 weekly snapshots, S&P 100):
  20d IC = 0.075, t-stat = 2.93, hit rate = 65%
"""

from __future__ import annotations

import contextlib
import io
from typing import Dict, Iterable, List, Sequence

import pandas as pd
import yfinance as yf

from ..contracts import DealFlowSignal, UniverseRow
from ..market_cache import ensure_ohlcv_history


def collect_price_momentum_signals(universe: Iterable[UniverseRow]) -> List[DealFlowSignal]:
    rows = list(universe)
    symbols = []
    seen = set()
    for row in rows:
        symbol = str(row.get("symbol", "")).upper().strip()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        symbols.append(symbol)
    if not symbols:
        return []

    close_map, volume_map = _download_symbol_series(symbols + ["SPY"])
    if not close_map:
        return [_no_data_signal(symbol) for symbol in symbols]

    spy_close = close_map.get("SPY")
    spy_r60 = _return_pct(spy_close, 60)

    vel_map: Dict[str, float] = {}
    rs_map: Dict[str, float] = {}
    accel_map: Dict[str, float] = {}
    mass_map: Dict[str, float] = {}
    force_map: Dict[str, float] = {}
    meta: Dict[str, Dict[str, float]] = {}

    for symbol in symbols:
        close = close_map.get(symbol)
        volume = volume_map.get(symbol)
        if close is None or close.empty:
            continue

        r60 = _return_pct(close, 60)
        if r60 is None or spy_r60 is None:
            continue

        accel = _sma20_acceleration(close)
        mass = _mass_ratio(close, volume)
        if accel is None or mass is None:
            continue

        vel_map[symbol] = float(r60)
        rs_map[symbol] = float(r60 - spy_r60)
        accel_map[symbol] = accel
        mass_map[symbol] = mass
        force_map[symbol] = mass * accel
        meta[symbol] = {
            "freshness_hours": _freshness_hours(close),
            "evidence_count": float(min(len(close), 252)),
        }

    vel_rank = _percentile_rank_map(vel_map)
    rs_rank = _percentile_rank_map(rs_map)
    accel_rank = _percentile_rank_map(accel_map)
    mass_rank = _percentile_rank_map(mass_map)
    force_rank = _percentile_rank_map(force_map)

    signals: List[DealFlowSignal] = []
    for symbol in symbols:
        m = meta.get(symbol)
        if not m:
            signals.append(_no_data_signal(symbol))
            continue

        score = (
            0.20 * (100.0 * vel_rank.get(symbol, 0.5))
            + 0.30 * (100.0 * accel_rank.get(symbol, 0.5))
            + 0.20 * (100.0 * mass_rank.get(symbol, 0.5))
            + 0.20 * (100.0 * force_rank.get(symbol, 0.5))
            + 0.10 * (100.0 * rs_rank.get(symbol, 0.5))
        )
        score = _clamp(score, 0.0, 100.0)
        signals.append(
            {
                "symbol": symbol,
                "signal_family": "price_momentum",
                "raw_score": float(round(score, 4)),
                "z_score": 0.0,
                "direction": _direction_from_score(score),
                "evidence_count": int(m["evidence_count"]),
                "freshness_hours": float(round(m["freshness_hours"], 4)),
                "source_status": "OK",
                "source_name": "price_momentum_fma_v2",
            }
        )

    return signals


def _download_symbol_series(
    symbols: Sequence[str],
) -> tuple[Dict[str, pd.Series], Dict[str, pd.Series]]:
    close_map: Dict[str, pd.Series] = {}
    volume_map: Dict[str, pd.Series] = {}
    deduped = [s for s in dict.fromkeys(str(sym).upper().strip() for sym in symbols) if s]

    frames = ensure_ohlcv_history(
        deduped,
        min_bars=90,
        full_period="180d",
        batch_size=10,
        fetch_batch=lambda batch, period: _download_prices_batch(batch, period=period),
    )
    for symbol in deduped:
        frame = frames.get(symbol)
        if frame is None or frame.empty:
            continue
        close = _extract_series(frame, symbol, "Close")
        if close is not None and not close.empty:
            close_map[symbol] = close
        volume = _extract_series(frame, symbol, "Volume")
        if volume is not None and not volume.empty:
            volume_map[symbol] = volume
    return close_map, volume_map


def _download_prices_batch(symbols: Sequence[str], period: str = "380d"):
    target: object = symbols[0] if len(symbols) == 1 else list(symbols)
    for _ in range(2):
        try:
            with _suppress_yf_noise():
                return yf.download(
                    target,
                    period=period,
                    interval="1d",
                    auto_adjust=False,
                    progress=False,
                    group_by="ticker",
                    threads=False,
                )
        except Exception:
            continue
    return None


def _extract_series(frame: pd.DataFrame, symbol: str, field: str):
    if frame is None or frame.empty:
        return None

    try:
        if field in frame.columns:
            return pd.to_numeric(frame[field], errors="coerce").dropna()
        if isinstance(frame.columns, pd.MultiIndex):
            if (symbol, field) in frame.columns:
                return pd.to_numeric(frame[(symbol, field)], errors="coerce").dropna()
            if (field, symbol) in frame.columns:
                return pd.to_numeric(frame[(field, symbol)], errors="coerce").dropna()
            if symbol in frame.columns.get_level_values(0):
                sub = frame[symbol]
                if field in sub.columns:
                    return pd.to_numeric(sub[field], errors="coerce").dropna()
            if field in frame.columns.get_level_values(0):
                sub = frame.xs(field, axis=1, level=0)
                if symbol in sub.columns:
                    return pd.to_numeric(sub[symbol], errors="coerce").dropna()
            return None

    except Exception:
        return None

    return None


def _return_pct(series, bars: int):
    if series is None or len(series) <= bars:
        return None
    prev = float(series.iloc[-bars - 1])
    cur = float(series.iloc[-1])
    if prev == 0.0:
        return None
    return ((cur - prev) / prev) * 100.0


def _sma20_acceleration(close) -> float | None:
    """Second derivative of SMA20 over 20-day windows.

    slope_recent = (SMA20_now - SMA20_20d_ago) / SMA20_20d_ago
    slope_prior  = (SMA20_20d_ago - SMA20_40d_ago) / SMA20_40d_ago
    acceleration = slope_recent - slope_prior

    Returns None if insufficient data. Values are price-normalized (%).
    """
    if close is None or len(close) < 61:  # 20 SMA + 2×20 lookback + 1
        return None
    sma20 = close.rolling(20).mean()
    sma_now = sma20.iloc[-1]
    sma_mid = sma20.iloc[-21]
    sma_far = sma20.iloc[-41]
    if pd.isna(sma_now) or pd.isna(sma_mid) or pd.isna(sma_far):
        return None
    if float(sma_mid) == 0 or float(sma_far) == 0:
        return None
    slope_recent = (float(sma_now) - float(sma_mid)) / float(sma_mid)
    slope_prior = (float(sma_mid) - float(sma_far)) / float(sma_far)
    return slope_recent - slope_prior


def _mass_ratio(close, volume) -> float | None:
    """Relative dollar volume: 5d avg / 60d avg.

    > 1 means more capital flowing in than usual.
    """
    if close is None or volume is None or len(close) < 60 or len(volume) < 60:
        return None
    common = close.index.intersection(volume.index)
    if len(common) < 60:
        return None
    c = close.reindex(common)
    v = volume.reindex(common)
    dv = c * v
    dv_5d = float(dv.tail(5).mean())
    dv_60d = float(dv.tail(60).mean())
    if dv_60d <= 0:
        return None
    return dv_5d / dv_60d


def _percentile_rank_map(values: Dict[str, float]) -> Dict[str, float]:
    if not values:
        return {}
    items = sorted(values.items(), key=lambda kv: kv[1])
    n = len(items)
    if n == 1:
        return {items[0][0]: 1.0}
    return {key: idx / float(n - 1) for idx, (key, _) in enumerate(items)}


def _freshness_hours(series) -> float:
    if series is None or series.empty:
        return 9999.0
    ts = series.index[-1]
    if hasattr(ts, "tz_localize") and ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    now = pd.Timestamp.now("UTC")
    return max(0.0, (now - ts).total_seconds() / 3600.0)


def _no_data_signal(symbol: str) -> DealFlowSignal:
    return {
        "symbol": symbol,
        "signal_family": "price_momentum",
        "raw_score": 0.0,
        "z_score": 0.0,
        "direction": "NEUTRAL",
        "evidence_count": 0,
        "freshness_hours": 9999.0,
        "source_status": "NO_DATA",
        "source_name": "price_momentum_fma_v2",
    }


def _direction_from_score(score: float) -> str:
    if score >= 60.0:
        return "BULLISH"
    if score <= 40.0:
        return "BEARISH"
    return "NEUTRAL"


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


@contextlib.contextmanager
def _suppress_yf_noise():
    sink = io.StringIO()
    with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
        yield


def _chunked(values: Sequence[str], size: int):
    step = max(1, int(size))
    for idx in range(0, len(values), step):
        yield list(values[idx : idx + step])
