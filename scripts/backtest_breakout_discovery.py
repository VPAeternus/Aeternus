"""
Breakout Discovery Forward Returns Backtest

Event-study: when the breakout scanner fires (score >= 50, near_high >= 0.95),
does buying at that close and holding for 10/20/30/60 days make money?

Universe: Top ~30 holdings from QQQ + SPY (hardcoded, deduped).
Data: 10 years daily OHLCV from yfinance.

Usage: python3 scripts/backtest_breakout_discovery.py
Output:
  eval_results/breakout_backtest.json       — all events
  eval_results/breakout_backtest_summary.csv — per-ticker stats
  Console summary tables
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import datetime as dt
import json
import warnings
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCORE_THRESHOLD = 50.0
NEAR_HIGH_THRESHOLD = 0.95
MIN_GAP_DAYS = 5          # min trading days between breakout events per ticker
HORIZONS = [10, 20, 30, 60]
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "eval_results")

# Top ~20 unique holdings from QQQ + SPY by weight, deduped (~30 after union)
UNIVERSE = [
    # QQQ top
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "AVGO", "GOOGL", "COST",
    "TSLA", "NFLX", "AMD", "ADBE", "PEP", "CSCO", "QCOM", "INTU",
    "TXN", "AMGN", "AMAT", "BKNG",
    # SPY top (not already in QQQ top)
    "BRK-B", "LLY", "UNH", "JPM", "V", "MA", "JNJ", "XOM",
    "PG", "HD",
]


# ---------------------------------------------------------------------------
# Scoring — mirrors breakout_scanner._score_ticker exactly
# ---------------------------------------------------------------------------

def score_day(
    close_252: np.ndarray,
    vol_60: np.ndarray,
    latest_close: float,
    latest_vol: float,
    sma50: float,
    sma200: float,
) -> tuple[float, dict]:
    """Compute breakout score for a single day. Returns (score, meta)."""
    high_52w = float(close_252.max())
    near_high = latest_close / high_52w if high_52w > 0 else 0.0

    vol_baseline = float(vol_60.mean()) if len(vol_60) > 0 else 0.0
    vol_ratio = latest_vol / vol_baseline if vol_baseline > 0 else 0.0

    above_sma200 = latest_close > sma200
    sma50_above_sma200 = sma50 > sma200

    near_high_component = min(1.0, max(0.0, (near_high - 0.90) / 0.10)) * 70.0
    trend_component = (25.0 if above_sma200 else 0.0) + (5.0 if sma50_above_sma200 else 0.0)

    score = min(100.0, near_high_component + trend_component)
    meta = {
        "near_high": round(near_high, 4),
        "vol_ratio": round(vol_ratio, 2),
        "above_sma200": bool(above_sma200),
        "sma50_above_sma200": bool(sma50_above_sma200),
    }
    return score, meta


# ---------------------------------------------------------------------------
# Walk-forward scan for a single ticker
# ---------------------------------------------------------------------------

def scan_ticker(ticker: str, closes: np.ndarray, volumes: np.ndarray, dates: np.ndarray) -> List[Dict[str, Any]]:
    """Walk forward through history, detect breakout events, record forward returns."""
    n = len(closes)
    events: List[Dict[str, Any]] = []
    last_event_idx = -MIN_GAP_DAYS - 1  # allow first event

    # Need at least 252 days of lookback + longest horizon of forward data
    start_idx = 252
    if n <= start_idx:
        return events

    for i in range(start_idx, n):
        # Minimum gap between events
        if i - last_event_idx < MIN_GAP_DAYS:
            continue

        close_252 = closes[i - 252 : i + 1]  # 252d window ending at i (inclusive)
        vol_60 = volumes[i - 60 : i]          # 60d window ending before i (yesterday's baseline)
        latest_close = closes[i]
        latest_vol = volumes[i]

        # SMA50 and SMA200
        sma50 = closes[i - 50 + 1 : i + 1].mean()
        sma200 = closes[i - 200 + 1 : i + 1].mean()

        score, meta = score_day(close_252, vol_60, latest_close, latest_vol, sma50, sma200)

        if score < SCORE_THRESHOLD or meta["near_high"] < NEAR_HIGH_THRESHOLD:
            continue

        # Record event
        last_event_idx = i
        entry_price = latest_close

        fwd_returns: Dict[str, Optional[float]] = {}
        for h in HORIZONS:
            if i + h < n:
                fwd_returns[f"fwd_{h}d"] = round(float((closes[i + h] - entry_price) / entry_price), 6)
            else:
                fwd_returns[f"fwd_{h}d"] = None

        events.append({
            "ticker": ticker,
            "date": str(dates[i])[:10],
            "entry_price": round(float(entry_price), 2),
            "score": round(score, 1),
            **meta,
            **fwd_returns,
        })

    return events


# ---------------------------------------------------------------------------
# Download helper
# ---------------------------------------------------------------------------

def download_ticker(ticker: str) -> Optional[pd.DataFrame]:
    """Download 10y daily OHLCV. Returns DataFrame with Close/Volume columns or None."""
    for attempt in range(2):
        try:
            df = yf.download(ticker, period="10y", interval="1d", progress=False, auto_adjust=True)
            if df is None or df.empty:
                continue
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            if hasattr(df.index, "tz") and df.index.tz is not None:
                df.index = df.index.tz_localize(None)
            if "Close" in df.columns and "Volume" in df.columns:
                return df[["Close", "Volume"]].dropna()
        except Exception:
            continue
    return None


# ---------------------------------------------------------------------------
# Stats helpers
# ---------------------------------------------------------------------------

def horizon_stats(returns: List[float]) -> Dict[str, Any]:
    """Compute summary stats for a list of returns."""
    if not returns:
        return {"n": 0}
    arr = np.array(returns)
    return {
        "n": len(arr),
        "win_rate": round(float((arr > 0).mean()), 4),
        "mean": round(float(arr.mean()), 6),
        "median": round(float(np.median(arr)), 6),
        "p10": round(float(np.percentile(arr, 10)), 6),
        "p90": round(float(np.percentile(arr, 90)), 6),
        "max_drawdown": round(float(arr.min()), 6),
        "best": round(float(arr.max()), 6),
    }


def print_stats_table(label: str, events: List[Dict], horizons: List[int] = HORIZONS) -> None:
    """Print a formatted stats table for a group of events."""
    print(f"\n{'=' * 80}")
    print(f"  {label}  (N events = {len(events)})")
    print(f"{'=' * 80}")
    print(f"  {'Horizon':<10} {'N':>6} {'WinRate':>8} {'Mean':>9} {'Median':>9} {'P10':>9} {'P90':>9} {'Worst':>9}")
    print(f"  {'-' * 70}")
    for h in horizons:
        key = f"fwd_{h}d"
        rets = [e[key] for e in events if e.get(key) is not None]
        s = horizon_stats(rets)
        if s["n"] == 0:
            print(f"  {h}d{'':<7} {'0':>6}")
            continue
        print(
            f"  {h}d{'':<7} {s['n']:>6} {s['win_rate']:>7.1%} {s['mean']:>8.2%} "
            f"{s['median']:>8.2%} {s['p10']:>8.2%} {s['p90']:>8.2%} {s['max_drawdown']:>8.2%}"
        )


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def write_outputs(all_events: List[Dict], per_ticker: Dict[str, List[Dict]]) -> None:
    """Write JSON and CSV to eval_results/."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # JSON — all events
    json_path = os.path.join(OUTPUT_DIR, "breakout_backtest.json")
    output = {
        "computed_date": dt.date.today().isoformat(),
        "universe_size": len(UNIVERSE),
        "total_events": len(all_events),
        "horizons": HORIZONS,
        "score_threshold": SCORE_THRESHOLD,
        "near_high_threshold": NEAR_HIGH_THRESHOLD,
        "min_gap_days": MIN_GAP_DAYS,
        "events": all_events,
    }
    with open(json_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nWrote {json_path}")

    # CSV — per-ticker summary
    rows = []
    for ticker, events in per_ticker.items():
        row: Dict[str, Any] = {"ticker": ticker, "event_count": len(events)}
        for h in HORIZONS:
            rets = [e[f"fwd_{h}d"] for e in events if e.get(f"fwd_{h}d") is not None]
            s = horizon_stats(rets)
            row[f"win_rate_{h}d"] = s.get("win_rate")
            row[f"mean_{h}d"] = s.get("mean")
            row[f"median_{h}d"] = s.get("median")
        rows.append(row)
    df = pd.DataFrame(rows).sort_values("event_count", ascending=False)
    csv_path = os.path.join(OUTPUT_DIR, "breakout_backtest_summary.csv")
    df.to_csv(csv_path, index=False)
    print(f"Wrote {csv_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print(f"\nBreakout Discovery Forward Returns Backtest — {dt.date.today().isoformat()}")
    print(f"Universe: {len(UNIVERSE)} tickers | Horizons: {HORIZONS}")
    print(f"Score threshold: {SCORE_THRESHOLD} | Near-high threshold: {NEAR_HIGH_THRESHOLD}")
    print(f"Min gap between events: {MIN_GAP_DAYS} trading days\n")

    all_events: List[Dict] = []
    per_ticker: Dict[str, List[Dict]] = {}

    for i, ticker in enumerate(UNIVERSE):
        print(f"  [{i + 1}/{len(UNIVERSE)}] {ticker}...", end=" ", flush=True)
        df = download_ticker(ticker)
        if df is None or len(df) < 300:
            print("skip (insufficient data)")
            continue

        closes = df["Close"].values.astype(float)
        volumes = df["Volume"].values.astype(float)
        dates = df.index.values

        events = scan_ticker(ticker, closes, volumes, dates)
        per_ticker[ticker] = events
        all_events.extend(events)
        print(f"{len(events)} events")

    if not all_events:
        print("\nNo breakout events found. Check universe/data.")
        return

    # --- Overall stats ---
    print_stats_table("OVERALL — All Breakout Events", all_events)

    # --- Score buckets ---
    bucket_50_70 = [e for e in all_events if 50 <= e["score"] < 70]
    bucket_70_90 = [e for e in all_events if 70 <= e["score"] < 90]
    bucket_90_100 = [e for e in all_events if e["score"] >= 90]

    if bucket_50_70:
        print_stats_table("SCORE BUCKET: 50-70", bucket_50_70)
    if bucket_70_90:
        print_stats_table("SCORE BUCKET: 70-90", bucket_70_90)
    if bucket_90_100:
        print_stats_table("SCORE BUCKET: 90-100", bucket_90_100)

    # --- Volume ratio buckets ---
    vol_1_2 = [e for e in all_events if 1.0 <= e["vol_ratio"] < 2.0]
    vol_2_3 = [e for e in all_events if 2.0 <= e["vol_ratio"] < 3.0]
    vol_3_plus = [e for e in all_events if e["vol_ratio"] >= 3.0]

    if vol_1_2:
        print_stats_table("VOLUME RATIO: 1-2x", vol_1_2)
    if vol_2_3:
        print_stats_table("VOLUME RATIO: 2-3x", vol_2_3)
    if vol_3_plus:
        print_stats_table("VOLUME RATIO: 3x+", vol_3_plus)

    # --- Per-ticker top-line ---
    print(f"\n{'=' * 80}")
    print("  PER-TICKER SUMMARY (20d forward return)")
    print(f"{'=' * 80}")
    print(f"  {'Ticker':<8} {'Events':>7} {'WinRate':>8} {'Mean':>9} {'Median':>9}")
    print(f"  {'-' * 45}")
    for ticker in sorted(per_ticker.keys()):
        events = per_ticker[ticker]
        rets = [e["fwd_20d"] for e in events if e.get("fwd_20d") is not None]
        if not rets:
            continue
        s = horizon_stats(rets)
        print(f"  {ticker:<8} {s['n']:>7} {s['win_rate']:>7.1%} {s['mean']:>8.2%} {s['median']:>8.2%}")

    # Write files
    write_outputs(all_events, per_ticker)
    print(f"\nDone. {len(all_events)} total breakout events across {len(per_ticker)} tickers.")


if __name__ == "__main__":
    main()
