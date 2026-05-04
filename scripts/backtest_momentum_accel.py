"""
Druckenmiller Momentum Acceleration Study
==========================================
Second-derivative of SMA slope as a turn predictor.

Instead of asking "is the moving average rising?" (first derivative = slope),
we ask "is the rate of rise accelerating or decelerating?" (second derivative).
Zero-crossings of acceleration often precede actual trend reversals.

Usage:
    python3 scripts/backtest_momentum_accel.py

Output:
    Per-ticker summary (top signals only to keep output manageable).
    Cross-stock agreement table: which parameter combos work on many stocks.
    Pooled analysis: all signals aggregated across the universe.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
from tradingagents.phase_engine import data_engine

# ── Configuration ────────────────────────────────────────────────────────────

# Individual stocks — diverse sectors, all liquid with long history (2000+)
STOCKS = [
    # Tech
    "AAPL", "MSFT", "AMZN", "NVDA",
    # Finance
    "JPM", "GS",
    # Healthcare
    "JNJ", "UNH",
    # Consumer
    "WMT", "HD", "COST",
    # Energy / Industrial
    "XOM", "CAT",
    # Benchmarks for comparison
    "QQQ", "SPY",
]

SMA_BASES = [10, 20, 50]
ACCEL_LOOKBACKS = [5, 10, 20]
FWD_WINDOWS = [1, 5, 10, 20]
MIN_SIGNALS = 20  # minimum signal count for statistical validity
TOP_N_PER_TICKER = 10  # only print top N signals per ticker to keep output readable


# ── Helpers ──────────────────────────────────────────────────────────────────

def ttest_1samp(values, popmean):
    """One-sample t-test without scipy. Returns (t_stat, p_value)."""
    arr = np.asarray(values, dtype=float)
    n = len(arr)
    if n < 2:
        return 0.0, 1.0
    mean = arr.mean()
    se = arr.std(ddof=1) / np.sqrt(n)
    if se == 0:
        return 0.0, 1.0
    t = (mean - popmean) / se
    # Normal approximation for p-value (accurate for n > 30)
    # Two-tailed
    df = n - 1
    # Use the t-distribution CDF via the regularized incomplete beta function
    # For simplicity, use normal approx since our samples are large (>= 20)
    from math import erfc, sqrt
    p = erfc(abs(t) / sqrt(2))  # two-tailed p from normal approx
    return t, p


def compute_acceleration(close, sma_col, accel_lookback):
    """
    Compute second derivative of SMA slope.

    slope = (sma - sma.shift(lb)) / (close * lb)   [same as data_engine]
    accel = slope - slope.shift(lb)                 [second derivative]
    """
    slope = (sma_col - sma_col.shift(accel_lookback)) / (close * accel_lookback)
    accel = slope - slope.shift(accel_lookback)
    return slope, accel


def find_zero_crossings(accel):
    """
    Find indices where acceleration flips sign.

    Returns:
        neg_to_pos: acceleration onset indices (potential bottoms)
        pos_to_neg: deceleration onset indices (potential tops)
    """
    vals = accel.values
    prev = np.roll(vals, 1)
    prev[0] = np.nan

    valid = ~(np.isnan(vals) | np.isnan(prev))
    neg_to_pos = np.where(valid & (vals > 0) & (prev <= 0))[0]
    pos_to_neg = np.where(valid & (vals < 0) & (prev >= 0))[0]

    return neg_to_pos.tolist(), pos_to_neg.tolist()


def compute_forward_returns(close_arr, indices, window):
    """Compute forward returns at given bar indices."""
    n = len(close_arr)
    valid = [i for i in indices if i + window < n]
    if not valid:
        return np.array([])
    idx = np.array(valid)
    return (close_arr[idx + window] - close_arr[idx]) / close_arr[idx]


# ── Main study ───────────────────────────────────────────────────────────────

def run_study(ticker):
    """Run full parameter sweep for one ticker. Returns results DataFrame."""
    try:
        df = data_engine.load(ticker)
    except Exception as e:
        print(f"  {ticker:5s}: FAILED ({e})")
        return pd.DataFrame(), 0

    close = df["close"].values
    baseline_daily = np.nanmean(np.diff(close) / close[:-1])

    # Pre-compute SMA columns (reuse data_engine's sma10/sma20, compute sma50)
    sma_map = {
        10: df["sma10"],
        20: df["sma20"],
        50: df["sma50"],
    }

    results = []

    for sma_p in SMA_BASES:
        sma_col = sma_map[sma_p]
        for accel_lb in ACCEL_LOOKBACKS:
            slope, accel = compute_acceleration(df["close"], sma_col, accel_lb)
            accel_up, accel_down = find_zero_crossings(accel)

            for fwd_w in FWD_WINDOWS:
                baseline_ret = baseline_daily * fwd_w

                # ── Acceleration onset (accel flips positive → potential buy) ──
                up_rets = compute_forward_returns(close, accel_up, fwd_w)
                if len(up_rets) >= MIN_SIGNALS:
                    mean_ret = up_rets.mean()
                    t_stat, p_val = ttest_1samp(up_rets, baseline_ret)
                    results.append({
                        "signal": "accel_up",
                        "sma": sma_p,
                        "accel_lb": accel_lb,
                        "fwd_days": fwd_w,
                        "count": len(up_rets),
                        "mean_ret_pct": mean_ret * 100,
                        "baseline_pct": baseline_ret * 100,
                        "edge_bps": (mean_ret - baseline_ret) * 10000,
                        "win_rate": (up_rets > 0).mean() * 100,
                        "t_stat": t_stat,
                        "p_value": p_val,
                    })

                # ── Deceleration onset (accel flips negative → potential sell) ──
                dn_rets = compute_forward_returns(close, accel_down, fwd_w)
                if len(dn_rets) >= MIN_SIGNALS:
                    mean_ret = dn_rets.mean()
                    t_stat, p_val = ttest_1samp(dn_rets, baseline_ret)
                    results.append({
                        "signal": "accel_dn",
                        "sma": sma_p,
                        "accel_lb": accel_lb,
                        "fwd_days": fwd_w,
                        "count": len(dn_rets),
                        "mean_ret_pct": mean_ret * 100,
                        "baseline_pct": baseline_ret * 100,
                        "edge_bps": (mean_ret - baseline_ret) * 10000,
                        "win_rate": (dn_rets < 0).mean() * 100,
                        "t_stat": t_stat,
                        "p_value": p_val,
                    })

    return pd.DataFrame(results), len(df)


def print_ticker_summary(ticker, df_results, n_bars=0):
    """Print compact top-N results for one ticker."""
    if df_results.empty:
        return

    sig = df_results[df_results["p_value"] < 0.05]
    top = df_results.sort_values("edge_bps", key=abs, ascending=False).head(TOP_N_PER_TICKER)

    print(f"  {ticker:5s} ({n_bars:5d} bars): {len(sig):2d} sig / {len(df_results)} combos | "
          f"top |edge|: {top.iloc[0]['edge_bps']:+.0f} bps "
          f"(sma{int(top.iloc[0]['sma'])}/lb{int(top.iloc[0]['accel_lb'])}/"
          f"{top.iloc[0]['signal']}/{int(top.iloc[0]['fwd_days'])}d)")


def cross_stock_analysis(all_results):
    """Aggregate analysis across all stocks."""
    tickers = [t for t in all_results if not all_results[t].empty]
    if len(tickers) < 3:
        print("  Too few tickers for cross-stock analysis.\n")
        return

    pd.set_option("display.max_rows", None)
    pd.set_option("display.width", 160)
    pd.set_option("display.float_format", lambda x: f"{x:8.2f}")

    key_cols = ["signal", "sma", "accel_lb", "fwd_days"]

    # ── 1. Agreement table: for each param combo, how many stocks show same-sign edge? ──
    print(f"\n{'='*70}")
    print("  CROSS-STOCK AGREEMENT TABLE")
    print(f"  ({len(tickers)} tickers analyzed)")
    print(f"{'='*70}\n")

    # Collect edge_bps and p_value per combo per ticker
    rows = []
    for t in tickers:
        for _, r in all_results[t].iterrows():
            rows.append({**{c: r[c] for c in key_cols},
                         "ticker": t, "edge_bps": r["edge_bps"],
                         "t_stat": r["t_stat"], "p_value": r["p_value"]})
    pool = pd.DataFrame(rows)

    combo_stats = []
    for combo, grp in pool.groupby(key_cols):
        sig, sma, alb, fwd = combo
        n_tickers = len(grp)
        pos_edge = (grp["edge_bps"] > 0).sum()
        neg_edge = (grp["edge_bps"] < 0).sum()
        n_sig = (grp["p_value"] < 0.05).sum()
        # "Agreement" = max of pos/neg count (majority direction)
        majority = max(pos_edge, neg_edge)
        direction = "+" if pos_edge >= neg_edge else "-"
        avg_edge = grp["edge_bps"].mean()
        med_edge = grp["edge_bps"].median()
        avg_t = grp["t_stat"].mean()
        combo_stats.append({
            "signal": sig, "sma": int(sma), "accel_lb": int(alb),
            "fwd_days": int(fwd), "n_tickers": n_tickers,
            "agree": majority, "agree_pct": majority / n_tickers * 100,
            "direction": direction, "n_sig": n_sig,
            "avg_edge": avg_edge, "med_edge": med_edge, "avg_t": avg_t,
        })

    df_combos = pd.DataFrame(combo_stats)
    # Sort by agreement % then avg edge magnitude
    df_combos = df_combos.sort_values(["agree_pct", "avg_edge"],
                                       ascending=[False, False], key=lambda s: abs(s))

    # Show top combos with >= 60% agreement
    strong = df_combos[df_combos["agree_pct"] >= 60]
    print(f"  Combos with >= 60% directional agreement ({len(strong)}):\n")
    if not strong.empty:
        cols = ["signal", "sma", "accel_lb", "fwd_days",
                "agree", "n_tickers", "agree_pct", "direction",
                "n_sig", "avg_edge", "med_edge", "avg_t"]
        print(strong.head(30)[cols].to_string(index=False))
    else:
        print("  None found.")
    print()

    # ── 2. Pooled signal analysis: aggregate all signal events across stocks ──
    print(f"\n{'='*70}")
    print("  POOLED SIGNAL ANALYSIS (all stocks combined)")
    print(f"{'='*70}\n")

    # For the top combos, show which individual stocks contribute
    top_combos = df_combos.head(10)
    for _, combo_row in top_combos.iterrows():
        sig = combo_row["signal"]
        sma = int(combo_row["sma"])
        alb = int(combo_row["accel_lb"])
        fwd = int(combo_row["fwd_days"])
        mask = ((pool["signal"] == sig) & (pool["sma"] == sma) &
                (pool["accel_lb"] == alb) & (pool["fwd_days"] == fwd))
        subset = pool[mask].sort_values("edge_bps", key=abs, ascending=False)
        print(f"  {sig} | sma{sma} | lb{alb} | {fwd}d fwd | "
              f"avg_edge={combo_row['avg_edge']:+.1f} bps | "
              f"agree={int(combo_row['agree'])}/{int(combo_row['n_tickers'])}")
        for _, row in subset.iterrows():
            star = "*" if row["p_value"] < 0.05 else " "
            print(f"    {star} {row['ticker']:5s}  edge={row['edge_bps']:+7.1f}  "
                  f"t={row['t_stat']:+5.2f}  p={row['p_value']:.3f}")
        print()

    # ── 3. Best signals per ticker (significant only) ──
    print(f"\n{'='*70}")
    print("  BEST SIGNIFICANT SIGNAL PER TICKER")
    print(f"{'='*70}\n")

    for t in sorted(tickers):
        df_t = all_results[t]
        sig_df = df_t[df_t["p_value"] < 0.05]
        if sig_df.empty:
            print(f"  {t:5s}: no significant signals")
            continue
        best = sig_df.loc[sig_df["edge_bps"].abs().idxmax()]
        print(f"  {t:5s}: {best['signal']} sma{int(best['sma'])}/lb{int(best['accel_lb'])} "
              f"{int(best['fwd_days'])}d → edge={best['edge_bps']:+.0f} bps "
              f"(t={best['t_stat']:+.2f}, p={best['p_value']:.3f}, "
              f"n={int(best['count'])}, win={best['win_rate']:.0f}%)")
    print()


# ── Entry point ──────────────────────────────────────────────────────────────

def main():
    print("Druckenmiller Momentum Acceleration Study — Stock Universe")
    print("Second-derivative of SMA slope as a turn predictor")
    print(f"Universe: {len(STOCKS)} tickers ({', '.join(STOCKS)})")
    print(f"SMA bases: {SMA_BASES}, Accel lookbacks: {ACCEL_LOOKBACKS}")
    print(f"Forward windows: {FWD_WINDOWS} days")
    print(f"Parameter grid: {len(SMA_BASES)*len(ACCEL_LOOKBACKS)} combos "
          f"× 2 signals × {len(FWD_WINDOWS)} windows = "
          f"{len(SMA_BASES)*len(ACCEL_LOOKBACKS)*2*len(FWD_WINDOWS)} cells per ticker\n")

    all_results = {}
    for ticker in STOCKS:
        result = run_study(ticker)
        if isinstance(result, tuple):
            df_results, n_bars = result
        else:
            df_results, n_bars = result, 0
        all_results[ticker] = df_results
        print_ticker_summary(ticker, df_results, n_bars)

    cross_stock_analysis(all_results)

    print("Done. Look for: high agreement %, |avg_edge| > 10 bps, "
          "multiple significant stocks per combo.")


if __name__ == "__main__":
    main()
