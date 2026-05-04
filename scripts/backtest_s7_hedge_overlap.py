#!/usr/bin/env python3
"""
Overlap analysis: AdaptiveHedgeEngine vs S7a/S7b

Both operate below SMA200. The question: does S7a/S7b add incremental
edge beyond the continuous bear hedge, or is it already captured?

Adaptive Hedge: short SPY every day SPY < SMA200, at 75-85% of gross
S7a: short on specific days (SMA stack + VIX gate), overnight only
S7b: short on specific days (SMA stack + VIX gate), intraday only
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import pandas as pd
from tradingagents.phase_engine import data_engine, phase_engine

START = "2005-01-01"


def main():
    qqq = data_engine.load("QQQ", start=START)
    spy = data_engine.load("SPY", start=START)

    # Align dates
    qqq_dates = set(qqq["date"].values)
    spy_dates = set(spy["date"].values)
    common = sorted(qqq_dates & spy_dates)
    qqq = qqq[qqq["date"].isin(common)].reset_index(drop=True)
    spy = spy[spy["date"].isin(common)].reset_index(drop=True)

    phases_qqq = phase_engine.classify_phases(qqq)
    phases_spy = phase_engine.classify_phases(spy)
    n = len(qqq)
    WARMUP = 252

    # Identify bear days (SPY < SMA200)
    spy_close = spy["close"].values
    spy_sma200 = spy["sma200"].values

    bear_days = set()
    s7a_days_qqq = set()
    s7a_days_spy = set()
    s7b_days_qqq = set()
    s7b_days_spy = set()

    # Also track daily P&L for hedge vs S7
    hedge_daily = []  # P&L from being short SPY at 80% on bear days
    s7a_qqq_pnl = []
    s7b_qqq_pnl = []

    for i in range(WARMUP, n - 1):
        if np.isnan(spy_sma200[i]):
            continue

        is_bear = spy_close[i] < spy_sma200[i]
        date_val = qqq.iloc[i]["date"]

        if is_bear:
            bear_days.add(i)
            # Hedge P&L: short SPY at 80% notional
            spy_ret = (spy_close[i+1] - spy_close[i]) / spy_close[i]
            hedge_daily.append({
                "idx": i, "date": date_val,
                "hedge_pnl_bps": -spy_ret * 8000,  # 80% short, in bps
            })

        # S7a — QQQ
        sig_a = phase_engine.should_short_overnight(qqq, phases_qqq, i, "QQQ")
        if sig_a:
            s7a_days_qqq.add(i)
            entry = qqq.iloc[i]["close"]
            exit_p = qqq.iloc[i+1]["open"]
            s7a_qqq_pnl.append({
                "idx": i, "date": date_val, "in_bear": is_bear,
                "pnl": entry - exit_p,
            })

        # S7a — SPY
        sig_a_spy = phase_engine.should_short_overnight(spy, phases_spy, i, "SPY")
        if sig_a_spy:
            s7a_days_spy.add(i)

        # S7b — QQQ
        if phase_engine.is_weak_regime_rth(qqq, phases_qqq, i):
            s7b_days_qqq.add(i)
            entry = qqq.iloc[i+1]["open"]
            exit_p = qqq.iloc[i+1]["close"]
            s7b_qqq_pnl.append({
                "idx": i, "date": date_val, "in_bear": is_bear,
                "pnl": entry - exit_p,
            })

        # S7b — SPY
        if phase_engine.is_weak_regime_rth(spy, phases_spy, i):
            s7b_days_spy.add(i)

    # Overlap counts
    s7a_in_bear_qqq = len(s7a_days_qqq & bear_days)
    s7a_in_bear_spy = len(s7a_days_spy & bear_days)
    s7b_in_bear_qqq = len(s7b_days_qqq & bear_days)
    s7b_in_bear_spy = len(s7b_days_spy & bear_days)

    print("=" * 80)
    print("Overlap Analysis: AdaptiveHedgeEngine vs S7a/S7b")
    print("=" * 80)

    print(f"\n  Bear days (SPY < SMA200):        {len(bear_days)}")
    print(f"  S7a QQQ signals:                 {len(s7a_days_qqq)}  ({s7a_in_bear_qqq} in bear = {s7a_in_bear_qqq/max(1,len(s7a_days_qqq))*100:.0f}%)")
    print(f"  S7a SPY signals:                 {len(s7a_days_spy)}  ({s7a_in_bear_spy} in bear = {s7a_in_bear_spy/max(1,len(s7a_days_spy))*100:.0f}%)")
    print(f"  S7b QQQ signals:                 {len(s7b_days_qqq)}  ({s7b_in_bear_qqq} in bear = {s7b_in_bear_qqq/max(1,len(s7b_days_qqq))*100:.0f}%)")
    print(f"  S7b SPY signals:                 {len(s7b_days_spy)}  ({s7b_in_bear_spy} in bear = {s7b_in_bear_spy/max(1,len(s7b_days_spy))*100:.0f}%)")

    # Key question: on S7a/S7b signal days, how does the adaptive hedge perform
    # vs the S7 signal itself?
    print(f"\n{'='*80}")
    print("On S7a signal days: Adaptive Hedge P&L vs S7a P&L")
    print(f"{'='*80}")

    hedge_df = pd.DataFrame(hedge_daily)
    s7a_df = pd.DataFrame(s7a_qqq_pnl)

    if not s7a_df.empty:
        s7a_bear = s7a_df[s7a_df["in_bear"]]
        # Get hedge P&L on those same days
        s7a_idxs = set(s7a_bear["idx"].values)
        hedge_on_s7a = hedge_df[hedge_df["idx"].isin(s7a_idxs)]

        print(f"\n  S7a signals in bear: {len(s7a_bear)}")
        print(f"  S7a avg P&L (overnight short QQQ): ${s7a_bear['pnl'].mean():+.2f}/share")
        print(f"  S7a total P&L:                     ${s7a_bear['pnl'].sum():+.2f}")
        if not hedge_on_s7a.empty:
            print(f"  Hedge avg P&L on same days (80% short SPY): {hedge_on_s7a['hedge_pnl_bps'].mean():+.1f} bps")
        print(f"  S7a WR: {(s7a_bear['pnl'] > 0).sum()}/{len(s7a_bear)} ({(s7a_bear['pnl'] > 0).mean()*100:.1f}%)")

    print(f"\n{'='*80}")
    print("On S7b signal days: Adaptive Hedge P&L vs S7b P&L")
    print(f"{'='*80}")

    s7b_df = pd.DataFrame(s7b_qqq_pnl)
    if not s7b_df.empty:
        s7b_bear = s7b_df[s7b_df["in_bear"]]
        s7b_idxs = set(s7b_bear["idx"].values)
        hedge_on_s7b = hedge_df[hedge_df["idx"].isin(s7b_idxs)]

        print(f"\n  S7b signals in bear: {len(s7b_bear)}")
        print(f"  S7b avg P&L (RTH short QQQ): ${s7b_bear['pnl'].mean():+.2f}/share")
        print(f"  S7b total P&L:               ${s7b_bear['pnl'].sum():+.2f}")
        if not hedge_on_s7b.empty:
            print(f"  Hedge avg P&L on same days:  {hedge_on_s7b['hedge_pnl_bps'].mean():+.1f} bps")
        print(f"  S7b WR: {(s7b_bear['pnl'] > 0).sum()}/{len(s7b_bear)} ({(s7b_bear['pnl'] > 0).mean()*100:.1f}%)")

    # Non-S7 bear days — what does the hedge do on days S7 doesn't fire?
    print(f"\n{'='*80}")
    print("Bear days breakdown: S7 signal days vs non-signal days")
    print(f"{'='*80}")

    all_s7_days = (s7a_days_qqq | s7b_days_qqq) & bear_days
    non_s7_bear = bear_days - all_s7_days

    hedge_on_s7 = hedge_df[hedge_df["idx"].isin(all_s7_days)]
    hedge_non_s7 = hedge_df[hedge_df["idx"].isin(non_s7_bear)]

    print(f"\n  Bear days with S7 signal:    {len(all_s7_days):>5}  hedge avg: {hedge_on_s7['hedge_pnl_bps'].mean():>+6.1f} bps")
    print(f"  Bear days WITHOUT S7 signal: {len(non_s7_bear):>5}  hedge avg: {hedge_non_s7['hedge_pnl_bps'].mean():>+6.1f} bps")
    print(f"  ALL bear days:               {len(bear_days):>5}  hedge avg: {hedge_df['hedge_pnl_bps'].mean():>+6.1f} bps")

    # The real question: is S7 ADDITIVE or REDUNDANT?
    print(f"\n{'='*80}")
    print("VERDICT: Is S7a/S7b additive or redundant with adaptive hedge?")
    print(f"{'='*80}")
    print(f"\n  Adaptive hedge is short SPY 80% on ALL {len(bear_days)} bear days.")
    print(f"  S7a/S7b fires on {len(all_s7_days)} of those days ({len(all_s7_days)/len(bear_days)*100:.1f}%).")
    print(f"  On the other {len(non_s7_bear)} bear days, ONLY the adaptive hedge is active.")
    print(f"\n  If you run BOTH, on S7 days you'd be ~160-185% short (80% hedge + S7 position).")
    print(f"  The question: does doubling down on S7 days beat the steady 80% hedge?")

    if not hedge_on_s7.empty and not hedge_non_s7.empty:
        s7_day_hedge_avg = hedge_on_s7['hedge_pnl_bps'].mean()
        non_s7_hedge_avg = hedge_non_s7['hedge_pnl_bps'].mean()
        print(f"\n  Hedge P&L on S7 signal days:     {s7_day_hedge_avg:>+6.1f} bps (hedge alone already captures this)")
        print(f"  Hedge P&L on non-S7 bear days:   {non_s7_hedge_avg:>+6.1f} bps")
        if s7_day_hedge_avg > non_s7_hedge_avg:
            print(f"\n  → S7 days are BETTER bear days for the hedge ({s7_day_hedge_avg:+.1f} vs {non_s7_hedge_avg:+.1f} bps)")
            print(f"    S7 would add incremental P&L on top of the hedge on these high-conviction days.")
        else:
            print(f"\n  → S7 days are WEAKER bear days for the hedge ({s7_day_hedge_avg:+.1f} vs {non_s7_hedge_avg:+.1f} bps)")
            print(f"    S7 doesn't pick the best bear days — adaptive hedge captures edge more broadly.")


if __name__ == "__main__":
    main()
