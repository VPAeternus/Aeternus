"""
Momentum Acceleration Strategy v3 — Full Backtest
==================================================
Three RTH legs + filtered overnight. 1 share, no compounding.

OVERNIGHT (filtered):
  Buy at Close[i-1], sell at Open[i]. Default: every night.
  Skip if: VIX 30-40 AND accel_up regime
  Skip if: VIX >= 40 AND close < SMA20

RTH LEG 1 — Dip-Buy:
  Buy at Open[i], sell at Close[i]. Conditions (previous day):
    accel_dn regime + close < SMA3/SMA10/SMA20
    + VIX in [20-25] or [30-40] or [40+]

RTH LEG 2 — Stay-Long (calm uptrend drift):
  Buy at Open[i], sell at Close[i]. Conditions (previous day):
    VIX <= 15 + close > SMA10 + SMA10 > SMA20

RTH LEG 3 — Uptrend Decel (volume-confirmed):
  Buy at Open[i], sell at Close[i]. Conditions (previous day):
    accel_dn regime + close > SMA3/SMA10/SMA20/SMA50/SMA200
    + volume > 5-day average volume (no VIX filter)

Acceleration (SMA10, lookback 5):
    slope = (sma10 - sma10.shift(5)) / (close * 5)
    accel = slope - slope.shift(5)
    Zero-crossings define persistent regime (carries until opposite signal).

Leg attribution: non-overlapping priority leg1 > leg2 > leg3.
Legs 1 & 3 cannot overlap by construction (close < SMA vs close > SMA).
Legs 1 & 2 cannot overlap (VIX >= 20 vs VIX <= 15).

Usage: python3 scripts/backtest_accel_rth.py
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
from tradingagents.phase_engine import data_engine
from tradingagents.phase_engine.v3_backtest import compute_accel, build_regime, run_backtest


# ── Universe ──────────────────────────────────────────────────────────────────

TICKERS = ["QQQ", "SPY"]

VIX_BUCKETS = [(0, 15), (15, 20), (20, 25), (25, 30), (30, 40), (40, 200)]
VIX_LABELS  = ["0-15", "15-20", "20-25", "25-30", "30-40", "40+"]


# ── Metric helpers ────────────────────────────────────────────────────────────

def fmt_pts(v: float) -> str:
    sign = "+" if v >= 0 else ""
    return f"{sign}{v:.2f}"


def win_rate(series) -> float:
    active = series[series != 0]
    if len(active) == 0:
        return 0.0
    return (active > 0).sum() / len(active) * 100


def sharpe_like(pnl) -> float:
    std = pnl.std()
    if std == 0:
        return 0.0
    return pnl.mean() / std * np.sqrt(252)


def max_drawdown(pnl) -> float:
    cum = pnl.cumsum()
    peak = cum.cummax()
    return (cum - peak).min()


def profit_factor(pnl) -> float:
    winners = pnl[pnl > 0].sum()
    losers  = pnl[pnl < 0].sum()
    if losers == 0:
        return float("inf")
    return winners / abs(losers)


# ── Display helpers ───────────────────────────────────────────────────────────

def print_summary(results: pd.DataFrame, df_raw: pd.DataFrame, ticker: str):
    total_rth = results["rth_pnl"].sum()
    total_on  = results["on_pnl"].sum()
    total_all = results["total_pnl"].sum()

    rth_days   = int(results["rth_cond"].sum())
    leg1_ct    = int(results["leg1"].sum())
    leg2_ct    = int(results["leg2"].sum())
    leg3_ct    = int(results["leg3"].sum())
    total_days = len(results) - 1
    on_nights  = int(results["on_active"].iloc[1:].sum())
    on_skipped = total_days - on_nights

    leg1_pts = results["leg1_pnl"].sum()
    leg2_pts = results["leg2_pnl"].sum()
    leg3_pts = results["leg3_pnl"].sum()

    leg1_avg = leg1_pts / leg1_ct if leg1_ct > 0 else 0.0
    leg2_avg = leg2_pts / leg2_ct if leg2_ct > 0 else 0.0
    leg3_avg = leg3_pts / leg3_ct if leg3_ct > 0 else 0.0

    # Strategy metrics
    strat_sharpe = sharpe_like(results["total_pnl"])
    strat_mdd    = max_drawdown(results["total_pnl"])
    strat_pf     = profit_factor(results["total_pnl"])

    # B&H metrics
    bh_daily  = df_raw["close"].diff().fillna(0.0)
    bh_pts    = df_raw["close"].iloc[-1] - df_raw["close"].iloc[0]
    start_px  = df_raw["close"].iloc[0]
    bh_sharpe = sharpe_like(bh_daily)
    bh_mdd    = max_drawdown(bh_daily)

    print("=" * 70)
    print(f"  Momentum Accel Strategy v3 — {ticker}  (1 share, no compounding)")
    print("=" * 70)
    d0 = pd.to_datetime(results["date"].iloc[0]).strftime("%Y-%m-%d")
    d1 = pd.to_datetime(results["date"].iloc[-1]).strftime("%Y-%m-%d")
    print(f"\n  Period : {d0}  →  {d1}  ({len(results)} bars)")
    print()

    print("  ── Per-Leg Breakdown ────────────────────────────────────────")
    print(f"  {'Leg':<25s} {'Trades':>7s} {'Points':>10s} {'Avg/Trade':>10s}")
    print(f"  {'─' * 55}")
    print(f"  {'Leg 1 (Dip-Buy)':<25s} {leg1_ct:>7d} {fmt_pts(leg1_pts):>10s} {leg1_avg:>10.3f}")
    print(f"  {'Leg 2 (Stay-Long)':<25s} {leg2_ct:>7d} {fmt_pts(leg2_pts):>10s} {leg2_avg:>10.3f}")
    print(f"  {'Leg 3 (Uptrend Decel)':<25s} {leg3_ct:>7d} {fmt_pts(leg3_pts):>10s} {leg3_avg:>10.3f}")
    print(f"  {'─' * 55}")
    print(f"  {'RTH Combined':<25s} {rth_days:>7d} {fmt_pts(total_rth):>10s}")
    print(f"  {'Overnight':<25s} {on_nights:>7d} {fmt_pts(total_on):>10s}  ({on_skipped} skipped)")
    print(f"  {'─' * 55}")
    print(f"  {'TOTAL':<25s} {'':>7s} {fmt_pts(total_all):>10s}")
    print()

    print("  ── Strategy vs Buy & Hold ──────────────────────────────────")
    print(f"  {'B&H Total (pts)':<40s} {fmt_pts(bh_pts):>10s}")
    print(f"  {'Strategy Total (pts)':<40s} {fmt_pts(total_all):>10s}")
    print(f"  {'Delta (pts)':<40s} {fmt_pts(total_all - bh_pts):>10s}")
    print()

    print("  ── Risk Metrics ────────────────────────────────────────────")
    print(f"  {'Sharpe (strategy / B&H)':<40s} {strat_sharpe:>6.3f} / {bh_sharpe:.3f}")
    print(f"  {'MaxDD  (strategy / B&H)':<40s} {strat_mdd:>6.2f} / {bh_mdd:.2f}")
    print(f"  {'Profit Factor (strategy)':<40s} {strat_pf:>10.3f}")
    print()


def print_annual(results: pd.DataFrame, df_raw: pd.DataFrame):
    r = results.copy()
    r["year"] = pd.to_datetime(r["date"]).dt.year

    raw = df_raw.copy()
    raw["year"] = pd.to_datetime(raw["date"]).dt.year

    close_by_year = raw.groupby("year")["close"].agg(["first", "last"])
    years_sorted  = sorted(close_by_year.index.tolist())
    bh_pts_by_year = {}
    for i, yr in enumerate(years_sorted):
        if i == 0:
            bh_pts_by_year[yr] = close_by_year.loc[yr, "last"] - close_by_year.loc[yr, "first"]
        else:
            prev_yr = years_sorted[i - 1]
            bh_pts_by_year[yr] = close_by_year.loc[yr, "last"] - close_by_year.loc[prev_yr, "last"]

    print("  ── Annual Breakdown ─────────────────────────────────────────────────────────")
    print(f"  {'Year':<6s} {'RTH':>9s} {'ON':>9s} {'Total':>10s} "
          f"{'B&H':>9s} {'Delta':>9s} {'L1':>5s} {'L2':>5s} {'L3':>5s}")
    print(f"  {'─' * 78}")

    annual_rows = []
    for year, grp in r.groupby("year"):
        rth_pts = grp["rth_pnl"].sum()
        on_pts  = grp["on_pnl"].sum()
        tot_pts = grp["total_pnl"].sum()
        bh_yr   = bh_pts_by_year.get(year, 0.0)
        delta   = tot_pts - bh_yr
        l1 = int(grp["leg1"].sum())
        l2 = int(grp["leg2"].sum())
        l3 = int(grp["leg3"].sum())

        print(f"  {year:<6d} {fmt_pts(rth_pts):>9s} {fmt_pts(on_pts):>9s} "
              f"{fmt_pts(tot_pts):>10s} {fmt_pts(bh_yr):>9s} {fmt_pts(delta):>9s} "
              f"{l1:>5d} {l2:>5d} {l3:>5d}")

        annual_rows.append({"year": year, "total_pts": tot_pts, "bh_pts": bh_yr})

    print(f"  {'─' * 78}")
    adf = pd.DataFrame(annual_rows)
    pos_yrs = (adf["total_pts"] > 0).sum()
    beat_bh = (adf["total_pts"] > adf["bh_pts"]).sum()
    print(f"  Positive years: {pos_yrs}/{len(adf)}  |  Beat B&H: {beat_bh}/{len(adf)}")
    print()


def print_vix_analysis(results: pd.DataFrame, df_raw: pd.DataFrame):
    """Slice performance by VIX bucket (using previous day's VIX)."""
    r = results.copy()
    r["prev_vix"] = r["vix"].shift(1)

    raw = df_raw.copy().reset_index(drop=True)
    r["bh_pnl"] = raw["close"].diff().fillna(0.0).values

    def _bucket_label(v):
        for (lo, hi), label in zip(VIX_BUCKETS, VIX_LABELS):
            if lo <= v < hi:
                return label
        return VIX_LABELS[-1]

    valid = r.dropna(subset=["prev_vix"]).copy()
    valid["vix_bucket"] = valid["prev_vix"].apply(_bucket_label)

    print("  ── VIX Bucket Analysis ──────────────────────────────────────────────────────")
    print()

    # Table 1: RTH by VIX
    print("  RTH Performance by VIX Bucket")
    print(f"  {'Bucket':<8s} {'Days':>6s} {'Trades':>7s} {'RTH Pts':>9s} "
          f"{'Avg':>9s} {'Win%':>6s}")
    print(f"  {'─' * 50}")
    for label in VIX_LABELS:
        grp = valid[valid["vix_bucket"] == label]
        if grp.empty:
            continue
        days   = len(grp)
        trades = int(grp["rth_cond"].sum())
        pts    = grp["rth_pnl"].sum()
        active = grp.loc[grp["rth_cond"], "rth_pnl"]
        avg    = active.mean() if len(active) > 0 else 0.0
        wr     = win_rate(grp["rth_pnl"])
        print(f"  {label:<8s} {days:>6d} {trades:>7d} {fmt_pts(pts):>9s} "
              f"{avg:>9.3f} {wr:>5.1f}%")
    print()

    # Table 2: Overnight by VIX
    print("  Overnight Performance by VIX Bucket")
    print(f"  {'Bucket':<8s} {'Nights':>7s} {'Skipped':>8s} {'ON Pts':>9s} "
          f"{'Avg':>9s} {'Win%':>6s}")
    print(f"  {'─' * 52}")
    for label in VIX_LABELS:
        grp = valid[valid["vix_bucket"] == label]
        if grp.empty:
            continue
        nights  = int(grp["on_active"].sum())
        skipped = len(grp) - nights
        pts     = grp["on_pnl"].sum()
        avg     = grp["on_pnl"].mean()
        wr      = win_rate(grp["on_pnl"])
        print(f"  {label:<8s} {nights:>7d} {skipped:>8d} {fmt_pts(pts):>9s} "
              f"{avg:>9.3f} {wr:>5.1f}%")
    print()

    # Table 3: Combined vs B&H
    print("  Combined Strategy vs B&H by VIX Bucket")
    print(f"  {'Bucket':<8s} {'Days':>6s} {'Strat':>10s} {'B&H':>9s} {'Delta':>9s}")
    print(f"  {'─' * 47}")
    for label in VIX_LABELS:
        grp = valid[valid["vix_bucket"] == label]
        if grp.empty:
            continue
        days  = len(grp)
        strat = grp["total_pnl"].sum()
        bh    = grp["bh_pnl"].sum()
        delta = strat - bh
        print(f"  {label:<8s} {days:>6d} {fmt_pts(strat):>10s} {fmt_pts(bh):>9s} "
              f"{fmt_pts(delta):>9s}")
    print()


def collect_summary(results: pd.DataFrame, df_raw: pd.DataFrame, ticker: str) -> dict:
    """Collect key metrics for cross-ticker comparison table."""
    total_all = results["total_pnl"].sum()
    bh_pts    = df_raw["close"].iloc[-1] - df_raw["close"].iloc[0]
    return {
        "ticker":  ticker,
        "total":   total_all,
        "bh":      bh_pts,
        "delta":   total_all - bh_pts,
        "sharpe":  sharpe_like(results["total_pnl"]),
        "mdd":     max_drawdown(results["total_pnl"]),
        "pf":      profit_factor(results["total_pnl"]),
        "leg1":    results["leg1_pnl"].sum(),
        "leg2":    results["leg2_pnl"].sum(),
        "leg3":    results["leg3_pnl"].sum(),
        "on":      results["on_pnl"].sum(),
        "l1_ct":   int(results["leg1"].sum()),
        "l2_ct":   int(results["leg2"].sum()),
        "l3_ct":   int(results["leg3"].sum()),
    }


def print_cross_ticker(summaries: list):
    """Print compact cross-ticker comparison."""
    print("\n" + "=" * 100)
    print("  CROSS-TICKER COMPARISON — Momentum Accel Strategy v3")
    print("=" * 100)
    print()
    print(f"  {'Ticker':<7s} {'Total':>9s} {'B&H':>9s} {'Delta':>9s} "
          f"{'Sharpe':>7s} {'MaxDD':>8s} {'PF':>6s} "
          f"{'Leg1':>8s} {'Leg2':>8s} {'Leg3':>8s} {'ON':>9s}")
    print(f"  {'─' * 93}")

    for s in summaries:
        print(f"  {s['ticker']:<7s} {fmt_pts(s['total']):>9s} {fmt_pts(s['bh']):>9s} "
              f"{fmt_pts(s['delta']):>9s} {s['sharpe']:>7.3f} {s['mdd']:>8.2f} "
              f"{s['pf']:>6.2f} {fmt_pts(s['leg1']):>8s} {fmt_pts(s['leg2']):>8s} "
              f"{fmt_pts(s['leg3']):>8s} {fmt_pts(s['on']):>9s}")

    print(f"  {'─' * 93}")

    # Summary stats
    totals  = [s["total"] for s in summaries]
    deltas  = [s["delta"] for s in summaries]
    sharpes = [s["sharpe"] for s in summaries]
    beat_ct = sum(1 for s in summaries if s["delta"] > 0)
    print(f"\n  Beat B&H: {beat_ct}/{len(summaries)} tickers")
    print(f"  Avg delta vs B&H: {fmt_pts(np.mean(deltas))} pts")
    print(f"  Avg Sharpe: {np.mean(sharpes):.3f}")
    print(f"  Median total pts: {fmt_pts(np.median(totals))}")
    print()


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    print("Momentum Acceleration Strategy v3 — Universe Backtest")
    print(f"Tickers: {', '.join(TICKERS)}")
    print()

    summaries = []

    for ticker in TICKERS:
        try:
            df = data_engine.load(ticker)
        except Exception as e:
            print(f"  {ticker}: FAILED to load ({e})\n")
            continue

        print(f"  Loaded {ticker}: {len(df)} bars  "
              f"({df['date'].iloc[0].strftime('%Y-%m-%d')} → "
              f"{df['date'].iloc[-1].strftime('%Y-%m-%d')})")

        results = run_backtest(df)

        print()
        print_summary(results, df, ticker)
        print_annual(results, df)
        print_vix_analysis(results, df)

        summaries.append(collect_summary(results, df, ticker))

    # Cross-ticker comparison
    if len(summaries) > 1:
        print_cross_ticker(summaries)


if __name__ == "__main__":
    main()
