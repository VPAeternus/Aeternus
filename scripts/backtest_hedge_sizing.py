#!/usr/bin/env python3
"""
Hedge sizing optimization: base bear hedge % vs S7 boost %

Tests combinations of:
  - Base hedge: 25%, 40%, 50%, 65%, 75%, 85% (applied on all bear days)
  - S7 boost: +0%, +25%, +50%, +75% (added on S7a/S7b signal days)

All with 0% in NEUTRAL (bull market). Bear = SPY < SMA200.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import pandas as pd
from tradingagents.phase_engine import data_engine, phase_engine

START = "2005-01-01"
CAPITAL = 100_000.0
WARMUP = 252


def load_data():
    qqq = data_engine.load("QQQ", start=START)
    spy = data_engine.load("SPY", start=START)
    common = sorted(set(qqq["date"].values) & set(spy["date"].values))
    qqq = qqq[qqq["date"].isin(common)].reset_index(drop=True)
    spy = spy[spy["date"].isin(common)].reset_index(drop=True)
    return qqq, spy


def run_sized_hedge(qqq, spy, base_bear_pct, s7_boost_pct):
    """
    Backtest with configurable bear hedge % and S7 boost.
    Returns stats dict.
    """
    phases_qqq = phase_engine.classify_phases(qqq)
    n = len(qqq)

    spy_close = spy["close"].values
    spy_sma200 = spy["sma200"].values
    qqq_close = qqq["close"].values
    spy_ret = np.zeros(n)
    qqq_ret = np.zeros(n)
    for i in range(1, n):
        spy_ret[i] = (spy_close[i] - spy_close[i-1]) / spy_close[i-1]
        qqq_ret[i] = (qqq_close[i] - qqq_close[i-1]) / qqq_close[i-1]

    portfolio_equity = CAPITAL
    qqq_equity = CAPITAL
    peak = CAPITAL
    max_dd = 0.0

    daily_rets = []
    bear_days = 0
    s7_days = 0
    hedge_pnl_total = 0.0

    for i in range(WARMUP, n):
        qqq_equity *= (1 + qqq_ret[i])

        is_bear = not np.isnan(spy_sma200[i]) and spy_close[i] < spy_sma200[i]

        if is_bear:
            bear_days += 1
            # Check if S7a or S7b fires (signal on day i-1, checking previous bar)
            s7_active = False
            if i > 0:
                sig_a = phase_engine.should_short_overnight(qqq, phases_qqq, i - 1, "QQQ")
                sig_b = phase_engine.is_weak_regime_rth(qqq, phases_qqq, i - 1)
                s7_active = bool(sig_a or sig_b)

            if s7_active:
                s7_days += 1
                hedge_pct = min(150, base_bear_pct + s7_boost_pct)
            else:
                hedge_pct = base_bear_pct

            hedge_return = -spy_ret[i] * (hedge_pct / 100.0)
            hedge_pnl_total += hedge_return * 100  # as pct
        else:
            hedge_return = 0.0

        port_ret = qqq_ret[i] + hedge_return
        portfolio_equity *= (1 + port_ret)
        daily_rets.append(port_ret)

        peak = max(peak, portfolio_equity)
        dd = (peak - portfolio_equity) / peak * 100
        max_dd = max(max_dd, dd)

    years = len(daily_rets) / 252
    cagr = ((portfolio_equity / CAPITAL) ** (1 / years) - 1) * 100 if years > 0 else 0
    arr = np.array(daily_rets)
    sharpe = arr.mean() / arr.std() * np.sqrt(252) if arr.std() > 0 else 0

    return {
        "cagr": round(cagr, 2),
        "sharpe": round(sharpe, 3),
        "max_dd": round(-max_dd, 1),
        "final": round(portfolio_equity, 0),
        "bear_days": bear_days,
        "s7_days": s7_days,
        "hedge_pnl_pct": round(hedge_pnl_total, 1),
    }


def run_stress_test(qqq, spy, base_bear_pct, s7_boost_pct, start_dt, end_dt):
    """Return drawdown during a specific stress period."""
    phases_qqq = phase_engine.classify_phases(qqq)
    n = len(qqq)
    spy_close = spy["close"].values
    spy_sma200 = spy["sma200"].values
    qqq_close = qqq["close"].values
    spy_ret = np.zeros(n)
    qqq_ret = np.zeros(n)
    for i in range(1, n):
        spy_ret[i] = (spy_close[i] - spy_close[i-1]) / spy_close[i-1]
        qqq_ret[i] = (qqq_close[i] - qqq_close[i-1]) / qqq_close[i-1]

    dates = pd.to_datetime(qqq["date"])
    mask_start = dates >= start_dt
    mask_end = dates <= end_dt

    portfolio = 100.0
    started = False
    for i in range(WARMUP, n):
        if not mask_start.iloc[i]:
            continue
        if not mask_end.iloc[i]:
            break
        started = True

        is_bear = not np.isnan(spy_sma200[i]) and spy_close[i] < spy_sma200[i]
        if is_bear:
            s7_active = False
            if i > 0:
                sig_a = phase_engine.should_short_overnight(qqq, phases_qqq, i - 1, "QQQ")
                sig_b = phase_engine.is_weak_regime_rth(qqq, phases_qqq, i - 1)
                s7_active = bool(sig_a or sig_b)
            hedge_pct = min(150, base_bear_pct + s7_boost_pct) if s7_active else base_bear_pct
            hedge_return = -spy_ret[i] * (hedge_pct / 100.0)
        else:
            hedge_return = 0.0

        portfolio *= (1 + qqq_ret[i] + hedge_return)

    return round(portfolio - 100, 1) if started else None


def main():
    print("Loading data...")
    qqq, spy = load_data()

    base_levels = [25, 40, 50, 65, 75, 85]
    boost_levels = [0, 25, 50, 75]

    stress_periods = [
        ("GFC", "2008-09-01", "2009-03-09"),
        ("COVID", "2020-02-19", "2020-03-23"),
        ("2022", "2022-01-03", "2022-10-12"),
        ("Tariffs", "2025-02-19", "2025-04-08"),
    ]

    print("\n" + "=" * 120)
    print("Hedge Sizing Grid — 0% neutral (bull), variable bear base + S7 boost")
    print("=" * 120)

    # Header
    print(f"\n{'Base':>5} {'Boost':>6} {'Eff S7':>7} {'CAGR':>7} {'Sharpe':>7} {'MaxDD':>8} {'Final $':>12} {'HedgePnL':>9}", end="")
    for label, _, _ in stress_periods:
        print(f" {label:>8}", end="")
    print()
    print("-" * (62 + 9 * len(stress_periods)))

    # QQQ baseline
    qqq_stats = run_sized_hedge(qqq, spy, 0, 0)
    print(f"{'QQQ':>5} {'---':>6} {'---':>7} {qqq_stats['cagr']:>6.2f}% {qqq_stats['sharpe']:>7.3f} {qqq_stats['max_dd']:>7.1f}% ${qqq_stats['final']:>10,.0f} {'---':>9}", end="")
    for label, s, e in stress_periods:
        dd = run_stress_test(qqq, spy, 0, 0, s, e)
        print(f" {dd:>+7.1f}%", end="")
    print()
    print("-" * (62 + 9 * len(stress_periods)))

    for base in base_levels:
        for boost in boost_levels:
            eff_s7 = min(150, base + boost)
            stats = run_sized_hedge(qqq, spy, base, boost)
            label_boost = f"+{boost}%" if boost > 0 else "---"
            print(f"{base:>4}% {label_boost:>6} {eff_s7:>6}% {stats['cagr']:>6.2f}% {stats['sharpe']:>7.3f} {stats['max_dd']:>7.1f}% ${stats['final']:>10,.0f} {stats['hedge_pnl_pct']:>+8.1f}%", end="")

            for label, s, e in stress_periods:
                dd = run_stress_test(qqq, spy, base, boost, s, e)
                if dd is not None:
                    print(f" {dd:>+7.1f}%", end="")
                else:
                    print(f" {'N/A':>8}", end="")
            print()
        if base < base_levels[-1]:
            print()  # spacing between base groups


if __name__ == "__main__":
    main()
