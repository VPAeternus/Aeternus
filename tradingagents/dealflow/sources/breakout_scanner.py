"""Breakout Discovery Engine — scans AKG universe for 52w-high breakouts, writes to AKG emergence."""

from __future__ import annotations

import contextlib
import datetime as dt
import io
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import pandas as pd
import yfinance as yf


_CACHE_DIR = Path("eval_results") / "deal_flow"
_SCORE_THRESHOLD = 50.0
_NEAR_HIGH_THRESHOLD = 0.95

_OHLCV_CACHE_PATH = Path("eval_results") / "deal_flow" / "breakout_ohlcv.json"
_MAX_BARS = 252
_ADV_MIN_USD = 5_000_000.0
_AKG_MIN_CENTRALITY = 0.05


# ---------------------------------------------------------------------------
# Scan universe
# ---------------------------------------------------------------------------

def _get_scan_universe() -> List[str]:
    """AKG company nodes with centrality >= threshold OR emerging (ATMOSPHERE/HABITABLE)."""
    try:
        from tradingagents.graph.knowledge_graph import AeternusKnowledgeGraph
        akg = AeternusKnowledgeGraph.load()
        _EMERGING_TIERS = {"ATMOSPHERE", "HABITABLE"}
        tickers = set()
        for n in akg._nodes.values():
            if n.get("node_type") != "company":
                continue
            if float(n.get("centrality") or 0) >= _AKG_MIN_CENTRALITY:
                tickers.add(n["id"])
            elif n.get("emergence_tier") in _EMERGING_TIERS:
                tickers.add(n["id"])
        return sorted(tickers)
    except Exception:
        return []


# ---------------------------------------------------------------------------
# OHLCV cache helpers
# ---------------------------------------------------------------------------

def _load_ohlcv_cache() -> dict:
    if not _OHLCV_CACHE_PATH.exists():
        return {}
    try:
        return json.loads(_OHLCV_CACHE_PATH.read_text())
    except Exception:
        return {}


def _save_ohlcv_cache(cache: dict) -> None:
    try:
        _OHLCV_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _OHLCV_CACHE_PATH.write_text(json.dumps(cache))
    except Exception:
        pass


def _update_ohlcv_cache(cache: dict, symbols: List[str], trade_date: str) -> dict:
    """Incremental OHLCV cache update.
    - New symbols: batch download 380d.
    - Stale symbols (last_date < trade_date): download 30d, append new bars.
    - Fresh symbols: skip.
    """
    new_symbols = [s for s in symbols if s not in cache]
    stale_symbols = [s for s in symbols if s in cache and cache[s].get("last_date", "") < trade_date]

    if new_symbols:
        close_map, volume_map = _download_ohlcv(new_symbols, period="380d")
        for sym in new_symbols:
            c, v = close_map.get(sym), volume_map.get(sym)
            if c is None or v is None or len(c) < 10:
                continue
            cache[sym] = {
                "last_date": c.index[-1].date().isoformat(),
                "close": [float(x) for x in c.values[-_MAX_BARS:]],
                "volume": [float(x) for x in v.values[-_MAX_BARS:]],
            }

    if stale_symbols:
        close_map, volume_map = _download_ohlcv(stale_symbols, period="30d")
        for sym in stale_symbols:
            c, v = close_map.get(sym), volume_map.get(sym)
            if c is None or v is None or c.empty:
                continue
            existing = cache[sym]
            last_known = existing.get("last_date", "")
            new_close = [float(c.values[i]) for i, d in enumerate(c.index) if d.date().isoformat() > last_known]
            new_volume = [float(v.values[i]) for i, d in enumerate(v.index) if d.date().isoformat() > last_known]
            if not new_close:
                continue
            cache[sym] = {
                "last_date": c.index[-1].date().isoformat(),
                "close": (existing.get("close", []) + new_close)[-_MAX_BARS:],
                "volume": (existing.get("volume", []) + new_volume)[-_MAX_BARS:],
            }

    return cache


# ---------------------------------------------------------------------------
# ADV filter
# ---------------------------------------------------------------------------

def _filter_by_adv(cache: dict, symbols: List[str]) -> List[str]:
    """Return symbols where 20-day ADV >= _ADV_MIN_USD."""
    result = []
    for sym in symbols:
        entry = cache.get(sym)
        if not entry or len(entry.get("close", [])) < 20 or len(entry.get("volume", [])) < 20:
            continue
        avg_vol = sum(entry["volume"][-20:]) / 20.0
        last_close = entry["close"][-1]
        if last_close > 0 and avg_vol * last_close >= _ADV_MIN_USD:
            result.append(sym)
    return result


# ---------------------------------------------------------------------------
# Main discovery entry point
# ---------------------------------------------------------------------------

def scan_breakout_discovery(
    *,
    trade_date: Optional[str] = None,
    dry_run: bool = False,
    akg=None,
) -> Dict:
    """Scan AKG universe for 52w-high breakouts. Write to AKG unless dry_run.

    Returns result dict with alerts list for CLI display.
    Never raises — returns empty result on any failure.
    """
    date_str = trade_date or dt.date.today().isoformat()
    try:
        symbols = _get_scan_universe()
        cache = _load_ohlcv_cache()
        cache = _update_ohlcv_cache(cache, symbols, date_str)
        _save_ohlcv_cache(cache)
        liquid = _filter_by_adv(cache, symbols)

        alerts: List[Dict] = []
        for sym in liquid:
            entry = cache.get(sym)
            if not entry:
                continue
            closes = entry.get("close", [])
            volumes = entry.get("volume", [])
            if len(closes) < _MAX_BARS or len(volumes) < _MAX_BARS:
                continue
            score, meta = _score_ticker(pd.Series(closes), pd.Series(volumes))
            if score < _SCORE_THRESHOLD or meta["near_high"] < _NEAR_HIGH_THRESHOLD:
                continue
            alerts.append({"ticker": sym, "score": round(score, 1), **meta})

        if alerts and not dry_run:
            if akg is None:
                from tradingagents.graph.knowledge_graph import AeternusKnowledgeGraph
                akg = AeternusKnowledgeGraph.load()
            for a in alerts:
                akg.enrich_node_breakout(
                    ticker=a["ticker"], score=a["score"],
                    near_high=a["near_high"],
                    vol_ratio=a["vol_ratio"],
                    as_of_date=date_str,
                )
            akg.save()

        audit = {}
        if not dry_run:
            try:
                from tradingagents.dealflow.scout_audit import append_scout_audit
                audit = append_scout_audit(
                    scout="breakout_scan",
                    as_of_date=date_str,
                    symbols=[a.get("ticker", "") for a in alerts],
                    records=alerts,
                    metadata={"universe_scanned": len(liquid), "score_threshold": _SCORE_THRESHOLD},
                )
            except Exception:
                audit = {}

        return {
            "ran": True,
            "trade_date": date_str,
            "universe_scanned": len(liquid),
            "alerts": alerts,
            "count": len(alerts),
            "dry_run": dry_run,
            "audit_path": str(Path("eval_results") / "deal_flow" / date_str / "scout_audit.json") if not dry_run else "",
            "audit_count": int(audit.get("count", 0) or 0),
        }
    except Exception as exc:
        print(f"[breakout_scanner] scan failed: {exc}", file=sys.stderr)
        return {"ran": False, "alerts": [], "count": 0, "error": str(exc)}


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _score_ticker(
    close: pd.Series,
    volume: pd.Series,
) -> Tuple[float, Dict]:
    """Compute breakout score (0-100) and metadata dict."""
    c = close.values
    v = volume.values

    latest_close = float(c[-1])
    high_52w = float(close.iloc[-252:].max())
    near_high = latest_close / high_52w if high_52w > 0 else 0.0

    vol_last = float(v[-1]) if len(v) > 0 else 0.0
    vol_baseline = float(pd.to_numeric(pd.Series(v[-60:]), errors="coerce").dropna().mean()) if len(v) >= 60 else 0.0
    vol_ratio = vol_last / vol_baseline if vol_baseline > 0 else 0.0

    above_sma200 = bool(latest_close > float(close.iloc[-200:].mean())) if len(close) >= 200 else False
    sma50 = float(close.iloc[-50:].mean()) if len(close) >= 50 else latest_close
    sma200 = float(close.iloc[-200:].mean()) if len(close) >= 200 else latest_close
    sma50_above_sma200 = bool(sma50 > sma200)

    # Score components — volume weight zeroed after backtest showed inverse
    # correlation with forward returns (quiet breakouts outperform loud ones).
    near_high_component = min(1.0, max(0.0, (near_high - 0.90) / 0.10)) * 70.0
    trend_component = (25.0 if above_sma200 else 0.0) + (5.0 if sma50_above_sma200 else 0.0)

    score = min(100.0, near_high_component + trend_component)

    meta = {
        "near_high": near_high,
        "vol_ratio": vol_ratio,
        "above_sma200": above_sma200,
        "sma50_above_sma200": sma50_above_sma200,
        "close": latest_close,
        "high_52w": high_52w,
    }
    return score, meta


def compute_breakout_score(
    near_high: float,
    vol_ratio: float,
    above_sma200: bool,
    sma50_above_sma200: bool,
) -> float:
    """Public scoring function — used directly in tests."""
    near_high_component = min(1.0, max(0.0, (near_high - 0.90) / 0.10)) * 70.0
    trend_component = (25.0 if above_sma200 else 0.0) + (5.0 if sma50_above_sma200 else 0.0)
    return min(100.0, near_high_component + trend_component)


# ---------------------------------------------------------------------------
# OHLCV download helpers
# ---------------------------------------------------------------------------

def _download_ohlcv(
    symbols: Sequence[str],
    period: str = "380d",
) -> Tuple[Dict[str, pd.Series], Dict[str, pd.Series]]:
    close_map: Dict[str, pd.Series] = {}
    volume_map: Dict[str, pd.Series] = {}
    deduped = list(dict.fromkeys(str(s).upper().strip() for s in symbols if s))

    frame = _download_batch(deduped, period=period)
    if frame is None or frame.empty:
        return close_map, volume_map

    for symbol in deduped:
        c = _extract_series(frame, symbol, "Close")
        v = _extract_series(frame, symbol, "Volume")
        if c is not None and not c.empty:
            close_map[symbol] = c
        if v is not None and not v.empty:
            volume_map[symbol] = v

    return close_map, volume_map


def _download_batch(symbols: Sequence[str], period: str = "380d"):
    target = symbols[0] if len(symbols) == 1 else list(symbols)
    for _ in range(2):
        try:
            with _suppress_yf_noise():
                return yf.download(
                    target,
                    period=period,
                    interval="1d",
                    auto_adjust=True,
                    progress=False,
                    group_by="ticker",
                    threads=False,
                )
        except Exception:
            continue
    return None


def _extract_series(frame: pd.DataFrame, symbol: str, field: str) -> Optional[pd.Series]:
    if frame is None or frame.empty:
        return None
    try:
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
        if field in frame.columns:
            return pd.to_numeric(frame[field], errors="coerce").dropna()
    except Exception:
        return None
    return None


def _compute_freshness_hours(close_map: Dict[str, pd.Series]) -> Dict[str, float]:
    result: Dict[str, float] = {}
    now = pd.Timestamp.now("UTC")
    for symbol, series in close_map.items():
        if series.empty:
            result[symbol] = 9999.0
            continue
        ts = series.index[-1]
        if hasattr(ts, "tzinfo") and ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        delta = (now - ts).total_seconds() / 3600.0
        result[symbol] = float(max(0.0, delta))
    return result


# ---------------------------------------------------------------------------
# I/O utilities
# ---------------------------------------------------------------------------

@contextlib.contextmanager
def _suppress_yf_noise():
    sink = io.StringIO()
    with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
        yield
