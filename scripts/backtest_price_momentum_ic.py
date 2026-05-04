"""
Price Momentum IC Backtest — Grid Search
Tests v1 (current) vs multiple v2 (F=MA) variants across:
  - 4 acceleration formulas (SMA20/10d, SMA20/20d, SMA50/20d, return-based)
  - 5 weight configurations (original, mass-heavy, mass-dominant, balanced, force-heavy)
= 20 v2 variants + 1 v1 baseline, all from the same data.

Universe: S&P 100. Data: yfinance bulk (~18 months). No paid APIs.

Usage: python3 scripts/backtest_price_momentum_ic.py
Output: eval_results/backtest_price_momentum_ic.json + console grid
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import contextlib
import datetime as dt
import io
import json
import math
import warnings
from typing import Dict, List, Optional, Tuple

import pandas as pd
import yfinance as yf
from scipy import stats as sp_stats

warnings.filterwarnings("ignore")

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "eval_results")

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

# ---------------------------------------------------------------------------
# Acceleration formulas (4 variants)
# ---------------------------------------------------------------------------
# Each takes a sliced close series, returns Optional[float]

ACCEL_CONFIGS = {
    "sma20_10d": "SMA20 slope Δ over 10d windows",
    "sma20_20d": "SMA20 slope Δ over 20d windows",
    "sma50_20d": "SMA50 slope Δ over 20d windows",
    "ret_accel":  "20d return acceleration",
}


def _accel_sma_slope(close: pd.Series, sma_window: int, slope_span: int) -> Optional[float]:
    """Generic: (SMA slope over recent span) - (SMA slope over prior span)."""
    need = sma_window + 2 * slope_span + 1
    if close is None or len(close) < need:
        return None
    sma = close.rolling(sma_window).mean()
    sma_now = sma.iloc[-1]
    sma_mid = sma.iloc[-slope_span - 1]
    sma_far = sma.iloc[-2 * slope_span - 1]
    if pd.isna(sma_now) or pd.isna(sma_mid) or pd.isna(sma_far):
        return None
    if float(sma_mid) == 0 or float(sma_far) == 0:
        return None
    slope_recent = (float(sma_now) - float(sma_mid)) / float(sma_mid)
    slope_prior = (float(sma_mid) - float(sma_far)) / float(sma_far)
    return slope_recent - slope_prior


def _accel_ret(close: pd.Series) -> Optional[float]:
    """Return acceleration: recent 20d return minus prior 20d return."""
    if close is None or len(close) < 41:
        return None
    p_now = float(close.iloc[-1])
    p_20 = float(close.iloc[-21])
    p_40 = float(close.iloc[-41])
    if p_20 == 0 or p_40 == 0:
        return None
    r_recent = (p_now - p_20) / p_20
    r_prior = (p_20 - p_40) / p_40
    return r_recent - r_prior


def compute_accel(close: pd.Series, accel_type: str) -> Optional[float]:
    if accel_type == "sma20_10d":
        return _accel_sma_slope(close, 20, 10)
    elif accel_type == "sma20_20d":
        return _accel_sma_slope(close, 20, 20)
    elif accel_type == "sma50_20d":
        return _accel_sma_slope(close, 50, 20)
    elif accel_type == "ret_accel":
        return _accel_ret(close)
    return None


# ---------------------------------------------------------------------------
# Weight configurations (5 variants)
# ---------------------------------------------------------------------------
# Keys: vel, accel, mass, force, rs

WEIGHT_CONFIGS = {
    "W1_orig":     {"vel": 0.20, "accel": 0.30, "mass": 0.20, "force": 0.20, "rs": 0.10},
    "W2_mass_hi":  {"vel": 0.25, "accel": 0.15, "mass": 0.30, "force": 0.20, "rs": 0.10},
    "W3_mass_dom": {"vel": 0.20, "accel": 0.10, "mass": 0.35, "force": 0.25, "rs": 0.10},
    "W4_balanced":  {"vel": 0.30, "accel": 0.20, "mass": 0.30, "force": 0.10, "rs": 0.10},
    "W5_force_hi": {"vel": 0.15, "accel": 0.25, "mass": 0.25, "force": 0.25, "rs": 0.10},
}


# ---------------------------------------------------------------------------
# Shared infrastructure
# ---------------------------------------------------------------------------

def load_sp100_tickers() -> List[str]:
    print("Loading S&P 100 tickers...")
    try:
        import ssl
        ssl._create_default_https_context = ssl._create_unverified_context
        tables = pd.read_html("https://en.wikipedia.org/wiki/S%26P_100", match="Symbol")
        tickers = tables[0]["Symbol"].str.replace(".", "-", regex=False).tolist()
        print(f"  Loaded {len(tickers)} from Wikipedia")
        return tickers
    except Exception:
        print(f"  Using hardcoded S&P 100 ({len(SP100_FALLBACK)})")
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
                print(f"  Got {len(df)} rows, {len(df.columns)} columns")
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


def _percentile_rank_map(values: Dict[str, float]) -> Dict[str, float]:
    if not values:
        return {}
    items = sorted(values.items(), key=lambda kv: kv[1])
    n = len(items)
    if n == 1:
        return {items[0][0]: 1.0}
    return {key: idx / float(n - 1) for idx, (key, _) in enumerate(items)}


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


def forward_return(close: pd.Series, snapshot_date: pd.Timestamp, horizon: int) -> Optional[float]:
    future = close[close.index > snapshot_date]
    if future.empty or len(future) <= horizon:
        return None
    entry = float(future.iloc[0])
    if entry <= 0:
        return None
    return (float(future.iloc[horizon]) - entry) / entry


def build_friday_grid(end_date: dt.date, n_weeks: int = 52) -> List[dt.date]:
    d = end_date
    while d.weekday() != 4:
        d -= dt.timedelta(days=1)
    return [d - dt.timedelta(weeks=i) for i in range(n_weeks)]


def _sl(s: Optional[pd.Series], ts: pd.Timestamp) -> Optional[pd.Series]:
    """Slice series to on-or-before timestamp."""
    if s is None or s.empty:
        return None
    sliced = s[s.index <= ts]
    return sliced if not sliced.empty else None


# ---------------------------------------------------------------------------
# v1 scorer (current formula, unchanged)
# ---------------------------------------------------------------------------

def _return_pct(series: pd.Series, bars: int) -> Optional[float]:
    if series is None or len(series) <= bars:
        return None
    prev = float(series.iloc[-bars - 1])
    cur = float(series.iloc[-1])
    if prev == 0.0:
        return None
    return ((cur - prev) / prev) * 100.0


def _rolling_last(series: pd.Series, window: int) -> Optional[float]:
    if series is None or len(series) < window:
        return None
    val = series.rolling(window).mean().iloc[-1]
    return None if pd.isna(val) else float(val)


def _volume_component_v1(vol: pd.Series) -> float:
    if vol is None or len(vol) < 60:
        return 50.0
    latest = float(vol.iloc[-1])
    bl = pd.to_numeric(vol.tail(60), errors="coerce").dropna()
    if bl.empty:
        return 50.0
    m, s = float(bl.mean()), float(bl.std(ddof=0))
    if s <= 0:
        return 50.0
    return max(0.0, min(100.0, 50.0 + 15.0 * ((latest - m) / s)))


def score_v1(
    close_map: Dict[str, pd.Series],
    volume_map: Dict[str, pd.Series],
    symbols: List[str],
    ts: pd.Timestamp,
) -> Dict[str, float]:
    spy_c = _sl(close_map.get("SPY"), ts)
    spy_r60 = _return_pct(spy_c, 60)

    r60_m: Dict[str, float] = {}
    rs60_m: Dict[str, float] = {}
    st: Dict[str, Dict[str, float]] = {}

    for sym in symbols:
        c = _sl(close_map.get(sym), ts)
        v = _sl(volume_map.get(sym), ts)
        if c is None or len(c) < 201:
            continue
        r60 = _return_pct(c, 60)
        if r60 is None or spy_r60 is None:
            continue
        sma20 = _rolling_last(c, 20)
        sma50 = _rolling_last(c, 50)
        sma200 = _rolling_last(c, 200)
        if sma20 is None or sma50 is None or sma200 is None:
            continue
        latest = float(c.iloc[-1])
        high_252 = float(c.tail(252).max())
        r60_m[sym] = r60
        rs60_m[sym] = r60 - spy_r60
        st[sym] = {
            "trend": 1.0 if latest > sma20 > sma50 > sma200 else 0.0,
            "near_high": 1.0 if latest >= 0.90 * high_252 else 0.0,
            "vol": _volume_component_v1(v),
        }

    r60_r = _percentile_rank_map(r60_m)
    rs60_r = _percentile_rank_map(rs60_m)
    scores: Dict[str, float] = {}
    for sym in symbols:
        s = st.get(sym)
        if not s:
            continue
        sc = (0.35 * 100 * r60_r.get(sym, 0.5)
              + 0.30 * 100 * rs60_r.get(sym, 0.5)
              + 0.15 * 100 * s["trend"]
              + 0.10 * 100 * s["near_high"]
              + 0.10 * s["vol"])
        scores[sym] = max(0.0, min(100.0, sc))
    return scores


# ---------------------------------------------------------------------------
# v2 raw component extraction (computed once per snapshot)
# ---------------------------------------------------------------------------

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


def extract_raw_components(
    close_map: Dict[str, pd.Series],
    volume_map: Dict[str, pd.Series],
    symbols: List[str],
    ts: pd.Timestamp,
) -> Dict[str, Dict[str, Optional[float]]]:
    """Per-symbol raw values: velocity, rel_str, mass, + one accel per formula."""
    spy_c = _sl(close_map.get("SPY"), ts)
    spy_r60 = _return_pct(spy_c, 60)

    out: Dict[str, Dict[str, Optional[float]]] = {}
    for sym in symbols:
        c = _sl(close_map.get(sym), ts)
        v = _sl(volume_map.get(sym), ts)
        if c is None or len(c) < 201:
            continue
        r60 = _return_pct(c, 60)
        if r60 is None or spy_r60 is None:
            continue
        mass = _mass_ratio(c, v)
        if mass is None:
            continue

        accels = {}
        for atype in ACCEL_CONFIGS:
            accels[atype] = compute_accel(c, atype)

        # Need at least one valid accel
        if all(a is None for a in accels.values()):
            continue

        out[sym] = {
            "vel": r60,
            "rs": r60 - spy_r60,
            "mass": mass,
            **{f"accel_{k}": v for k, v in accels.items()},
        }
    return out


def score_v2_variant(
    raw: Dict[str, Dict[str, Optional[float]]],
    accel_type: str,
    weights: Dict[str, float],
) -> Dict[str, float]:
    """Score all symbols using a specific accel formula + weight config."""
    accel_key = f"accel_{accel_type}"

    # Filter to symbols with valid accel for this type
    valid = {sym: r for sym, r in raw.items()
             if r.get(accel_key) is not None}
    if len(valid) < 10:
        return {}

    # Build raw maps
    vel_m = {s: r["vel"] for s, r in valid.items()}
    rs_m = {s: r["rs"] for s, r in valid.items()}
    mass_m = {s: r["mass"] for s, r in valid.items()}
    accel_m = {s: r[accel_key] for s, r in valid.items()}
    force_m = {s: r["mass"] * r[accel_key] for s, r in valid.items()}

    # Percentile-rank each
    vel_r = _percentile_rank_map(vel_m)
    rs_r = _percentile_rank_map(rs_m)
    mass_r = _percentile_rank_map(mass_m)
    accel_r = _percentile_rank_map(accel_m)
    force_r = _percentile_rank_map(force_m)

    scores: Dict[str, float] = {}
    for sym in valid:
        sc = (weights["vel"] * 100 * vel_r.get(sym, 0.5)
              + weights["accel"] * 100 * accel_r.get(sym, 0.5)
              + weights["mass"] * 100 * mass_r.get(sym, 0.5)
              + weights["force"] * 100 * force_r.get(sym, 0.5)
              + weights["rs"] * 100 * rs_r.get(sym, 0.5))
        scores[sym] = max(0.0, min(100.0, sc))
    return scores


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    today = dt.date.today()
    last_snapshot = today - dt.timedelta(days=25)
    fridays = build_friday_grid(last_snapshot, n_weeks=52)

    print(f"\nPrice Momentum IC Grid Search — v1 vs {len(ACCEL_CONFIGS)}×{len(WEIGHT_CONFIGS)} v2 variants")
    print(f"Range: {fridays[-1]} → {fridays[0]}, {len(fridays)} snapshots\n")

    symbols = load_sp100_tickers()
    all_symbols = list(dict.fromkeys(symbols + ["SPY"]))
    raw_df = download_bulk(all_symbols, days=540)
    if raw_df is None:
        print("ERROR: no data.")
        return

    close_map: Dict[str, pd.Series] = {}
    volume_map: Dict[str, pd.Series] = {}
    for sym in all_symbols:
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

    print(f"  Symbols with data: {len(close_map)}\n")

    # Build variant keys
    variant_keys = ["v1_current"]
    for at in ACCEL_CONFIGS:
        for wk in WEIGHT_CONFIGS:
            variant_keys.append(f"{at}|{wk}")

    # IC collectors: variant_key -> {"5d": [floats], "20d": [floats]}
    ic_lists: Dict[str, Dict[str, List[float]]] = {
        k: {"5d": [], "20d": []} for k in variant_keys
    }
    # Also track per-component IC for the winning combo
    comp_ic: Dict[str, Dict[str, List[float]]] = {
        k: {"5d": [], "20d": []}
        for k in list(ACCEL_CONFIGS.keys()) + ["velocity", "mass", "rel_str"]
    }

    for i, friday in enumerate(fridays):
        ts = pd.Timestamp(friday)

        # v1
        s1 = score_v1(close_map, volume_map, symbols, ts)

        # v2 raw components (computed once)
        raw = extract_raw_components(close_map, volume_map, symbols, ts)

        if len(s1) < 10 or len(raw) < 10:
            continue

        # Forward returns for common symbols
        common_all = set(s1.keys()) & set(raw.keys())
        fwd5: Dict[str, float] = {}
        fwd20: Dict[str, float] = {}
        for sym in common_all:
            c = close_map.get(sym)
            if c is None:
                continue
            r5 = forward_return(c, ts, 5)
            r20 = forward_return(c, ts, 20)
            if r5 is not None:
                fwd5[sym] = r5
            if r20 is not None:
                fwd20[sym] = r20

        # v1 IC
        def _ic_for(scores_map, fwd_map):
            syms = set(scores_map.keys()) & set(fwd_map.keys())
            if len(syms) < 10:
                return None
            s_list = [scores_map[s] for s in syms]
            r_list = [fwd_map[s] for s in syms]
            return spearman_ic(s_list, r_list)

        ic1_5 = _ic_for(s1, fwd5)
        ic1_20 = _ic_for(s1, fwd20)
        if ic1_5 is not None:
            ic_lists["v1_current"]["5d"].append(ic1_5)
        if ic1_20 is not None:
            ic_lists["v1_current"]["20d"].append(ic1_20)

        # v2 variants
        for at in ACCEL_CONFIGS:
            for wk, wv in WEIGHT_CONFIGS.items():
                key = f"{at}|{wk}"
                s2 = score_v2_variant(raw, at, wv)
                ic5 = _ic_for(s2, fwd5)
                ic20 = _ic_for(s2, fwd20)
                if ic5 is not None:
                    ic_lists[key]["5d"].append(ic5)
                if ic20 is not None:
                    ic_lists[key]["20d"].append(ic20)

        # Component ICs (raw values, not percentile-ranked — true signal)
        for at in ACCEL_CONFIGS:
            accel_key = f"accel_{at}"
            vals = {s: raw[s][accel_key] for s in raw if raw[s].get(accel_key) is not None}
            ic5 = _ic_for(vals, fwd5)
            ic20 = _ic_for(vals, fwd20)
            if ic5 is not None:
                comp_ic[at]["5d"].append(ic5)
            if ic20 is not None:
                comp_ic[at]["20d"].append(ic20)

        # Velocity, mass, rel_str component ICs
        vel_vals = {s: raw[s]["vel"] for s in raw}
        mass_vals = {s: raw[s]["mass"] for s in raw}
        rs_vals = {s: raw[s]["rs"] for s in raw}
        for name, vals in [("velocity", vel_vals), ("mass", mass_vals), ("rel_str", rs_vals)]:
            ic5 = _ic_for(vals, fwd5)
            ic20 = _ic_for(vals, fwd20)
            if ic5 is not None:
                comp_ic[name]["5d"].append(ic5)
            if ic20 is not None:
                comp_ic[name]["20d"].append(ic20)

        if (i + 1) % 13 == 0 or i == 0:
            print(f"  [{i+1:>2}/{len(fridays)}] {friday}")

    # --- Aggregate ---
    def _agg(vals: List[float]) -> dict:
        if not vals:
            return {"mean": None, "std": None, "hit_rate": None, "t_stat": None, "n": 0}
        n = len(vals)
        mean_ic = sum(vals) / n
        std_ic = (sum((v - mean_ic) ** 2 for v in vals) / max(n - 1, 1)) ** 0.5
        hit_rate = sum(1 for v in vals if v > 0) / n
        t_stat = (mean_ic / (std_ic / math.sqrt(n))) if std_ic > 0 else 0.0
        return {"mean": round(mean_ic, 4), "std": round(std_ic, 4),
                "hit_rate": round(hit_rate, 4), "t_stat": round(t_stat, 2), "n": n}

    grid_results = {}
    for k in variant_keys:
        grid_results[k] = {"5d": _agg(ic_lists[k]["5d"]), "20d": _agg(ic_lists[k]["20d"])}

    comp_results = {}
    for k in comp_ic:
        comp_results[k] = {"5d": _agg(comp_ic[k]["5d"]), "20d": _agg(comp_ic[k]["20d"])}

    output = {
        "computed_date": str(today),
        "universe": "SP100",
        "universe_size": len(symbols),
        "n_snapshots": len(fridays),
        "accel_configs": ACCEL_CONFIGS,
        "weight_configs": {k: v for k, v in WEIGHT_CONFIGS.items()},
        "grid": grid_results,
        "component_ic": comp_results,
    }

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(OUTPUT_DIR, "backtest_price_momentum_ic.json")
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nWrote {out_path}")

    # --- Console output ---
    print("\n" + "=" * 90)
    print("  COMPONENT IC (raw signal, before weighting)")
    print("=" * 90)
    print(f"  {'Component':<20} {'IC 5d':>8} {'t 5d':>8} {'IC 20d':>8} {'t 20d':>8}")
    print("  " + "-" * 56)
    for k in ["velocity", "mass", "rel_str"] + list(ACCEL_CONFIGS.keys()):
        c5 = comp_results[k]["5d"]
        c20 = comp_results[k]["20d"]
        label = k if k in ["velocity", "mass", "rel_str"] else f"accel:{k}"
        print(f"  {label:<20} {c5['mean'] or 0:>8.4f} {c5['t_stat'] or 0:>8.2f}"
              f" {c20['mean'] or 0:>8.4f} {c20['t_stat'] or 0:>8.2f}")

    print("\n" + "=" * 90)
    print("  FULL GRID — sorted by 20d Mean IC (our holding period)")
    print("=" * 90)
    print(f"  {'Variant':<32} {'IC 5d':>8} {'t 5d':>7} {'HR 5d':>7}"
          f" {'IC 20d':>8} {'t 20d':>7} {'HR 20d':>7}")
    print("  " + "-" * 80)

    # Sort by 20d mean IC descending
    sorted_keys = sorted(variant_keys,
                         key=lambda k: grid_results[k]["20d"]["mean"] or -999,
                         reverse=True)

    for k in sorted_keys:
        g5 = grid_results[k]["5d"]
        g20 = grid_results[k]["20d"]
        # Highlight significant results
        marker = ""
        if (g20["t_stat"] or 0) >= 2.0:
            marker = " ***"
        elif (g20["t_stat"] or 0) >= 1.5:
            marker = " **"
        elif (g20["t_stat"] or 0) >= 1.0:
            marker = " *"

        label = k.replace("|", " + ") if "|" in k else k
        if len(label) > 30:
            label = label[:30]
        print(f"  {label:<32}"
              f" {g5['mean'] or 0:>8.4f} {g5['t_stat'] or 0:>7.2f} {g5['hit_rate'] or 0:>6.0%}"
              f" {g20['mean'] or 0:>8.4f} {g20['t_stat'] or 0:>7.2f} {g20['hit_rate'] or 0:>6.0%}"
              f"{marker}")

    # Winner summary
    best_key = sorted_keys[0]
    best = grid_results[best_key]["20d"]
    v1 = grid_results["v1_current"]["20d"]
    print()
    print(f"  BEST 20d: {best_key.replace('|', ' + ')}")
    print(f"    IC={best['mean']}  t={best['t_stat']}  hit={best['hit_rate']}")
    delta = (best["mean"] or 0) - (v1["mean"] or 0)
    print(f"    vs v1 current: {delta:+.4f} IC improvement")
    print("=" * 90)


if __name__ == "__main__":
    main()
