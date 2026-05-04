"""Autoresearch eval harness — DO NOT MODIFY.

Downloads S&P 100 OHLCV data, computes price_momentum (F=MA v2) and breakout_discovery
signals across 100 weekly snapshots, caches everything, and provides evaluate(score_fn)
for measuring Spearman rank IC against forward returns.

Standalone: python autoresearch/prepare.py  (downloads, caches, runs sanity check)
"""

import contextlib
import datetime as dt
import hashlib
import io
import json
import math
import os
import warnings
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
import yfinance as yf
from scipy import stats as sp_stats

warnings.filterwarnings("ignore")

CACHE_DIR = Path.home() / ".cache" / "autoresearch_scoring"

SP100_FALLBACK = [
    "AAPL", "ABBV", "ABT", "ACN", "ADBE", "AIG", "AMD", "AMGN", "AMT", "AMZN",
    "AVGO", "AXP", "BA", "BAC", "BK", "BKNG", "BLK", "BMY", "BRK-B", "C",
    "CAT", "CHTR", "CL", "CMCSA", "COF", "COP", "COST", "CRM", "CSCO", "CVS",
    "CVX", "DE", "DHR", "DIS", "DOW", "DUK", "EMR", "EXC", "F", "FDX",
    "GD", "GE", "GILD", "GM", "GOOG", "GOOGL", "GS", "HD", "HON", "IBM",
    "INTC", "INTU", "ISRG", "JNJ", "JPM", "KHC", "KO", "LIN", "LLY", "LMT",
    "LOW", "MA", "MCD", "MDLZ", "MDT", "MET", "META", "MMM", "MO", "MRK",
    "MS", "MSFT", "NEE", "NFLX", "NKE", "NVDA", "ORCL", "PEP", "PFE", "PG",
    "PM", "PYPL", "QCOM", "RTX", "SBUX", "SCHW", "SO", "SPG", "T", "TGT",
    "TMO", "TMUS", "TXN", "UNH", "UNP", "UPS", "USB", "V", "VZ", "WFC",
    "WMT", "XOM",
]

SIGNAL_FAMILIES = [
    "price_momentum", "breakout_discovery",
    "social_momentum", "news_catalyst", "macro_regime_fit",
    "smart_money", "sector_rotation", "insider_cluster",
    "emergence", "liquidity_tradability",
]


# ---------------------------------------------------------------------------
# Data infrastructure (proven, from backtest_price_momentum_ic.py)
# ---------------------------------------------------------------------------

def load_sp100_tickers() -> List[str]:
    try:
        import ssl
        ssl._create_default_https_context = ssl._create_unverified_context
        tables = pd.read_html("https://en.wikipedia.org/wiki/S%26P_100", match="Symbol")
        return tables[0]["Symbol"].str.replace(".", "-", regex=False).tolist()
    except Exception:
        return list(SP100_FALLBACK)


def download_bulk(symbols: List[str], days: int = 540) -> Optional[pd.DataFrame]:
    print(f"Downloading {days}d of data for {len(symbols)} symbols...")
    target = list(dict.fromkeys(symbols))
    sink = io.StringIO()
    for _ in range(3):
        try:
            with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
                df = yf.download(
                    target, period=f"{days}d", interval="1d",
                    auto_adjust=False, progress=False,
                    group_by="ticker", threads=False,
                )
            if df is not None and not df.empty:
                print(f"  Got {len(df)} rows")
                return df
        except Exception:
            continue
    return None


def extract_series(frame: pd.DataFrame, symbol: str, field: str) -> Optional[pd.Series]:
    if frame is None or frame.empty:
        return None
    try:
        if isinstance(frame.columns, pd.MultiIndex):
            for pair in [(symbol, field), (field, symbol)]:
                if pair in frame.columns:
                    return pd.to_numeric(frame[pair], errors="coerce").dropna()
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


def _sl(s: Optional[pd.Series], ts: pd.Timestamp) -> Optional[pd.Series]:
    """Slice series to on-or-before timestamp (time-travel guard)."""
    if s is None or s.empty:
        return None
    sliced = s[s.index <= ts]
    return sliced if not sliced.empty else None


def build_friday_grid(end_date: dt.date, n_weeks: int = 100) -> List[dt.date]:
    d = end_date
    while d.weekday() != 4:
        d -= dt.timedelta(days=1)
    return [d - dt.timedelta(weeks=i) for i in range(n_weeks)]


def forward_return(close: pd.Series, snapshot_date: pd.Timestamp, horizon: int) -> Optional[float]:
    future = close[close.index > snapshot_date]
    if future.empty or len(future) <= horizon:
        return None
    entry = float(future.iloc[0])
    if entry <= 0:
        return None
    return (float(future.iloc[horizon]) - entry) / entry


def spearman_ic(scores: List[float], returns: List[float]) -> Optional[float]:
    if len(scores) < 5:
        return None
    pairs = [(s, r) for s, r in zip(scores, returns) if math.isfinite(s) and math.isfinite(r)]
    if len(pairs) < 5:
        return None
    s_vals, r_vals = zip(*pairs)
    corr, _ = sp_stats.spearmanr(s_vals, r_vals)
    if math.isnan(corr):
        return None
    return round(corr, 4)


def _percentile_rank_map(values: Dict[str, float]) -> Dict[str, float]:
    if not values:
        return {}
    items = sorted(values.items(), key=lambda kv: kv[1])
    n = len(items)
    if n == 1:
        return {items[0][0]: 1.0}
    return {key: idx / float(n - 1) for idx, (key, _) in enumerate(items)}


# ---------------------------------------------------------------------------
# Signal computation
# ---------------------------------------------------------------------------

def _return_pct(series: Optional[pd.Series], bars: int) -> Optional[float]:
    if series is None or len(series) <= bars:
        return None
    prev = float(series.iloc[-bars - 1])
    cur = float(series.iloc[-1])
    if prev == 0.0:
        return None
    return ((cur - prev) / prev) * 100.0


def _mass_ratio(close: pd.Series, volume: pd.Series) -> Optional[float]:
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


def _accel_sma20_20d(close: pd.Series) -> Optional[float]:
    """SMA20 slope change over 20d windows (2nd derivative of price)."""
    need = 20 + 2 * 20 + 1
    if close is None or len(close) < need:
        return None
    sma = close.rolling(20).mean()
    sma_now = sma.iloc[-1]
    sma_mid = sma.iloc[-21]
    sma_far = sma.iloc[-41]
    if pd.isna(sma_now) or pd.isna(sma_mid) or pd.isna(sma_far):
        return None
    if float(sma_mid) == 0 or float(sma_far) == 0:
        return None
    slope_recent = (float(sma_now) - float(sma_mid)) / float(sma_mid)
    slope_prior = (float(sma_mid) - float(sma_far)) / float(sma_far)
    return slope_recent - slope_prior


def compute_price_momentum_signals(
    close_map: Dict[str, pd.Series],
    volume_map: Dict[str, pd.Series],
    symbols: List[str],
    ts: pd.Timestamp,
) -> Dict[str, float]:
    """F=MA v2: 20% vel + 30% accel + 20% mass + 20% force + 10% RS, percentile ranked."""
    spy_c = _sl(close_map.get("SPY"), ts)
    spy_r60 = _return_pct(spy_c, 60)

    raw: Dict[str, Dict[str, float]] = {}
    for sym in symbols:
        c = _sl(close_map.get(sym), ts)
        v = _sl(volume_map.get(sym), ts)
        if c is None or len(c) < 201:
            continue
        r60 = _return_pct(c, 60)
        if r60 is None or spy_r60 is None:
            continue
        mass = _mass_ratio(c, v)
        accel = _accel_sma20_20d(c)
        if mass is None or accel is None:
            continue
        raw[sym] = {
            "vel": r60,
            "accel": accel,
            "mass": mass,
            "force": mass * accel,
            "rs": r60 - spy_r60,
        }

    if len(raw) < 10:
        return {}

    vel_r = _percentile_rank_map({s: r["vel"] for s, r in raw.items()})
    accel_r = _percentile_rank_map({s: r["accel"] for s, r in raw.items()})
    mass_r = _percentile_rank_map({s: r["mass"] for s, r in raw.items()})
    force_r = _percentile_rank_map({s: r["force"] for s, r in raw.items()})
    rs_r = _percentile_rank_map({s: r["rs"] for s, r in raw.items()})

    scores: Dict[str, float] = {}
    for sym in raw:
        sc = (0.20 * 100 * vel_r.get(sym, 0.5)
              + 0.30 * 100 * accel_r.get(sym, 0.5)
              + 0.20 * 100 * mass_r.get(sym, 0.5)
              + 0.20 * 100 * force_r.get(sym, 0.5)
              + 0.10 * 100 * rs_r.get(sym, 0.5))
        scores[sym] = max(0.0, min(100.0, sc))
    return scores


def compute_breakout_signals(
    close_map: Dict[str, pd.Series],
    symbols: List[str],
    ts: pd.Timestamp,
) -> Dict[str, float]:
    """Breakout discovery: near_high(70) + trend(30), volume zeroed."""
    scores: Dict[str, float] = {}
    for sym in symbols:
        c = _sl(close_map.get(sym), ts)
        if c is None or len(c) < 252:
            continue
        latest = float(c.iloc[-1])
        high_252 = float(c.tail(252).max())
        near_high = latest / high_252 if high_252 > 0 else 0.0

        above_sma200 = latest > float(c.tail(200).mean()) if len(c) >= 200 else False
        sma50 = float(c.tail(50).mean()) if len(c) >= 50 else latest
        sma200 = float(c.tail(200).mean()) if len(c) >= 200 else latest

        near_high_comp = min(1.0, max(0.0, (near_high - 0.90) / 0.10)) * 70.0
        trend_comp = (25.0 if above_sma200 else 0.0) + (5.0 if sma50 > sma200 else 0.0)
        scores[sym] = min(100.0, near_high_comp + trend_comp)
    return scores


# ---------------------------------------------------------------------------
# Snapshot building + caching
# ---------------------------------------------------------------------------

def _build_close_volume_maps(
    raw_df: pd.DataFrame, symbols: List[str],
) -> Tuple[Dict[str, pd.Series], Dict[str, pd.Series]]:
    close_map: Dict[str, pd.Series] = {}
    volume_map: Dict[str, pd.Series] = {}
    for sym in symbols:
        c = extract_series(raw_df, sym, "Close")
        if c is not None and not c.empty:
            if hasattr(c.index, "tz") and c.index.tz is not None:
                c.index = c.index.tz_localize(None)
            close_map[sym] = c
        v = extract_series(raw_df, sym, "Volume")
        if v is not None and not v.empty:
            if hasattr(v.index, "tz") and v.index.tz is not None:
                v.index = v.index.tz_localize(None)
            volume_map[sym] = v
    return close_map, volume_map


def build_snapshots(
    close_map: Dict[str, pd.Series],
    volume_map: Dict[str, pd.Series],
    symbols: List[str],
    fridays: List[dt.date],
) -> List[dict]:
    snapshots = []
    for i, friday in enumerate(fridays):
        ts = pd.Timestamp(friday)
        pm = compute_price_momentum_signals(close_map, volume_map, symbols, ts)
        bd = compute_breakout_signals(close_map, symbols, ts)

        all_tickers = set(pm.keys())
        if not all_tickers:
            continue

        signals: Dict[str, Dict[str, float]] = {}
        fwd5: Dict[str, float] = {}
        fwd20: Dict[str, float] = {}

        for sym in all_tickers:
            sig: Dict[str, float] = {}
            sig["price_momentum"] = pm.get(sym, 50.0)
            sig["breakout_discovery"] = bd.get(sym, 50.0)
            for fam in SIGNAL_FAMILIES:
                if fam not in sig:
                    sig[fam] = 50.0
            signals[sym] = sig

            c = close_map.get(sym)
            if c is not None:
                r5 = forward_return(c, ts, 5)
                r20 = forward_return(c, ts, 20)
                if r5 is not None:
                    fwd5[sym] = r5
                if r20 is not None:
                    fwd20[sym] = r20

        snapshots.append({
            "date": str(friday),
            "signals": signals,
            "forward_5d": fwd5,
            "forward_20d": fwd20,
        })

        if (i + 1) % 25 == 0 or i == 0:
            print(f"  [{i+1:>3}/{len(fridays)}] {friday}  ({len(all_tickers)} tickers)")

    return snapshots


def _cache_hash(symbols: List[str], n_weeks: int, end_date: str) -> str:
    key = f"{sorted(symbols)}|{n_weeks}|{end_date}"
    return hashlib.md5(key.encode()).hexdigest()[:12]


def save_snapshots(snapshots: list, cache_hash: str) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"snapshots_{cache_hash}.json"
    path.write_text(json.dumps(snapshots))
    print(f"  Cached to {path}")


def load_snapshots(cache_hash: str) -> Optional[list]:
    path = CACHE_DIR / f"snapshots_{cache_hash}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Evaluation API
# ---------------------------------------------------------------------------

def evaluate(score_fn) -> dict:
    """Run score_fn against 100 weekly snapshots, return IC stats.

    Args:
        score_fn: callable(signals: dict[ticker, dict[family, score]]) -> dict[ticker, float]
    Returns:
        dict with mean_ic_5d, mean_ic_20d, t_stat_5d, t_stat_20d,
        hit_rate_5d, hit_rate_20d, n_snapshots, n_tickers_avg
    """
    symbols = load_sp100_tickers()
    all_symbols = list(dict.fromkeys(symbols + ["SPY"]))
    today = dt.date.today()
    last_snapshot = today - dt.timedelta(days=25)
    fridays = build_friday_grid(last_snapshot, n_weeks=100)

    ch = _cache_hash(all_symbols, 100, str(last_snapshot))
    snapshots = load_snapshots(ch)

    if snapshots is None:
        print("Building snapshots (first run, ~60s)...")
        raw_df = download_bulk(all_symbols, days=540)
        if raw_df is None:
            return {"error": "no data"}
        close_map, volume_map = _build_close_volume_maps(raw_df, all_symbols)
        print(f"  {len(close_map)} symbols with data")
        snapshots = build_snapshots(close_map, volume_map, symbols, fridays)
        save_snapshots(snapshots, ch)
    else:
        print(f"Loaded {len(snapshots)} cached snapshots.")

    ic_5d: List[float] = []
    ic_20d: List[float] = []
    ticker_counts: List[int] = []

    for snap in snapshots:
        scores = score_fn(snap["signals"])
        fwd5 = snap["forward_5d"]
        fwd20 = snap["forward_20d"]

        common5 = set(scores.keys()) & set(fwd5.keys())
        if len(common5) >= 5:
            s_list = [scores[t] for t in common5]
            r_list = [fwd5[t] for t in common5]
            ic = spearman_ic(s_list, r_list)
            if ic is not None:
                ic_5d.append(ic)

        common20 = set(scores.keys()) & set(fwd20.keys())
        if len(common20) >= 5:
            s_list = [scores[t] for t in common20]
            r_list = [fwd20[t] for t in common20]
            ic = spearman_ic(s_list, r_list)
            if ic is not None:
                ic_20d.append(ic)

        ticker_counts.append(len(scores))

    def _stats(vals):
        if not vals:
            return 0.0, 0.0, 0.0
        n = len(vals)
        m = sum(vals) / n
        std = (sum((v - m) ** 2 for v in vals) / max(n - 1, 1)) ** 0.5
        t = (m / (std / math.sqrt(n))) if std > 0 else 0.0
        hr = sum(1 for v in vals if v > 0) / n
        return round(m, 4), round(t, 2), round(hr, 4)

    m5, t5, hr5 = _stats(ic_5d)
    m20, t20, hr20 = _stats(ic_20d)
    avg_tickers = round(sum(ticker_counts) / max(len(ticker_counts), 1), 0)

    return {
        "mean_ic_5d": m5,
        "mean_ic_20d": m20,
        "t_stat_5d": t5,
        "t_stat_20d": t20,
        "hit_rate_5d": hr5,
        "hit_rate_20d": hr20,
        "n_snapshots": len(snapshots),
        "n_tickers_avg": int(avg_tickers),
    }


# ---------------------------------------------------------------------------
# Standalone sanity check
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    def uniform_scorer(signals):
        return {ticker: 50.0 for ticker in signals}

    print("Autoresearch scoring harness — sanity check")
    print("Running uniform scorer (IC should be ~0.0)...\n")
    results = evaluate(uniform_scorer)
    print("\n---")
    for k, v in results.items():
        fmt = f"{v:.4f}" if isinstance(v, float) else str(v)
        print(f"{k + ':':20s} {fmt}")
    print("\nExpected: mean_ic ≈ 0.0 (uniform scores carry no information)")
