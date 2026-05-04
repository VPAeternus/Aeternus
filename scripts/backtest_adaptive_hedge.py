#!/usr/bin/env python3
"""
Backtest AdaptiveHedgeEngine — does the regime-adaptive hedge protect?

Setup:
  - $100K static long QQQ portfolio (tech_conc=100%, beta=1.25)
  - Each day: feed SPY/VIX into hedge engine → get target_hedge_pct
  - Hedge via short SPY (or QQQ) at target_hedge_pct of gross
  - Compare: QQQ alone vs QQQ + adaptive hedge

No transaction costs on hedge rebalances (conservative: daily rebal allowed).
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import pandas as pd
from tradingagents.phase_engine import data_engine
from tradingagents.graph.hedging import AdaptiveHedgeEngine, _classify_market_regime

START = "2005-01-01"
CAPITAL = 100_000.0


def load_market_data():
    """Load QQQ, SPY, VIX with aligned dates."""
    qqq = data_engine.load("QQQ", start=START)
    spy = data_engine.load("SPY", start=START)

    # Align on date
    qqq_dates = set(qqq["date"].values)
    spy_dates = set(spy["date"].values)
    common = sorted(qqq_dates & spy_dates)

    qqq = qqq[qqq["date"].isin(common)].reset_index(drop=True)
    spy = spy[spy["date"].isin(common)].reset_index(drop=True)
    return qqq, spy


def run_backtest(qqq, spy):
    """Simulate adaptive hedge on a 100% long QQQ portfolio."""
    n = len(qqq)
    WARMUP = 252  # Need SMA200 to be valid

    # Pre-compute SPY SMAs
    spy_close = spy["close"].values
    spy_sma20 = spy["sma20"].values
    spy_sma200 = spy["sma200"].values
    vix = spy["vix"].values if "vix" in spy.columns else qqq["vix"].values

    qqq_close = qqq["close"].values
    qqq_ret = np.zeros(n)
    spy_ret = np.zeros(n)
    for i in range(1, n):
        qqq_ret[i] = (qqq_close[i] - qqq_close[i-1]) / qqq_close[i-1]
        spy_ret[i] = (spy_close[i] - spy_close[i-1]) / spy_close[i-1]

    # Track daily state
    records = []
    hedge_pct = 0.0
    portfolio_equity = CAPITAL
    qqq_equity = CAPITAL  # buy-and-hold benchmark

    # Rolling drawdown tracker
    peak_equity = CAPITAL

    for i in range(WARMUP, n):
        # Update benchmarks
        qqq_equity *= (1 + qqq_ret[i])

        # Portfolio: long QQQ + short hedge
        long_return = qqq_ret[i]
        hedge_return = -spy_ret[i] * (hedge_pct / 100.0)  # short SPY
        portfolio_return = long_return + hedge_return
        portfolio_equity *= (1 + portfolio_return)

        # Track drawdown
        peak_equity = max(peak_equity, portfolio_equity)
        drawdown_pct = (peak_equity - portfolio_equity) / peak_equity * 100.0

        # Compute rolling VaR proxy (20-day)
        if i >= WARMUP + 20:
            recent_rets = [qqq_ret[j] + (-spy_ret[j] * hedge_pct / 100.0) for j in range(i-19, i+1)]
            var95 = max(0, -np.percentile(recent_rets, 5) * 100.0)
        else:
            var95 = 2.5

        # Build market snapshot
        sma200_val = spy_sma200[i]
        sma20_val = spy_sma20[i]
        if np.isnan(sma200_val) or np.isnan(sma20_val) or sma200_val == 0 or sma20_val == 0:
            records.append({
                "date": qqq.iloc[i]["date"],
                "qqq_equity": qqq_equity,
                "portfolio_equity": portfolio_equity,
                "hedge_pct": hedge_pct,
                "regime": "UNKNOWN",
            })
            continue

        # SMA200 5d ago
        sma200_5d = spy_sma200[max(0, i-5)]
        if np.isnan(sma200_5d) or sma200_5d == 0:
            sma200_5d = sma200_val

        vix_val = vix[i] if not np.isnan(vix[i]) else 20.0

        # Classify regime
        crash_trigger = all([
            spy_close[i] < sma200_val,
            ((sma200_val - sma200_5d) / sma200_5d * 100.0) < -0.10,
            1.25 > 1.05,  # beta > 1.05 (tech portfolio)
            var95 > 3.0,
            drawdown_pct > 5.0,
        ])

        regime = _classify_market_regime(
            spy_close=spy_close[i],
            spy_sma200=sma200_val,
            vix_close=vix_val,
            crash_trigger_active=crash_trigger,
        )

        # Compute hedge target using engine logic (inlined for speed)
        # Beta component
        beta = 1.25  # tech-heavy portfolio
        beta_component = max(0, min(75, (beta - 1.0) * 100.0))
        var_component = 0.0 if var95 <= 2.5 else max(25, min(75, 25 + 10 * (var95 - 2.5)))
        base = max(beta_component, var_component)

        # Deviation bucket
        spy_dev = ((spy_close[i] - sma20_val) / sma20_val) * 100.0
        if spy_dev > 5.0:
            dev_bucket = 50.0
        elif spy_dev > 3.0:
            dev_bucket = 25.0
        elif spy_dev > 2.0:
            dev_bucket = 12.5
        elif spy_dev >= 0.0:
            dev_bucket = 0.0
        else:
            dev_bucket = 25.0

        # VIX adjustment
        if vix_val < 12:
            vix_adj = 10.0
        elif vix_val < 15:
            vix_adj = 5.0
        elif vix_val < 20:
            vix_adj = 0.0
        elif vix_val <= 25:
            vix_adj = 10.0
        else:
            vix_adj = 20.0

        adaptive = dev_bucket + vix_adj
        bear_trigger = spy_close[i] < sma200_val
        if bear_trigger:
            adaptive = max(adaptive, 75.0)

        long_only_target = min(100.0, max(base, adaptive))

        # Stress overlay
        stress = 0.0
        if regime == "BEAR_STRESS":
            stress = 85.0
        elif regime == "BEAR":
            stress = 75.0
        elif regime == "VOLATILITY_SHOCK":
            stress = 90.0
        elif regime == "HIGH_VOLATILITY":
            stress = 65.0
        elif regime == "RISK_OFF":
            stress = 55.0
        elif regime == "EUPHORIA":
            stress = 20.0

        if drawdown_pct >= 10 or var95 >= 4.5:
            stress = max(stress, 85.0)
        elif drawdown_pct >= 7 or var95 >= 3.5:
            stress = max(stress, 70.0)

        if crash_trigger:
            extra_short = 25.0 if vix_val <= 30 else 50.0
            target = min(150.0, 100.0 + extra_short)
        else:
            target = max(long_only_target, stress)

        # Hysteresis: only rebalance if delta >= 5%
        if abs(target - hedge_pct) >= 5.0:
            hedge_pct = target

        records.append({
            "date": qqq.iloc[i]["date"],
            "qqq_equity": qqq_equity,
            "portfolio_equity": portfolio_equity,
            "hedge_pct": hedge_pct,
            "regime": regime,
            "vix": vix_val,
            "drawdown_pct": drawdown_pct,
        })

    return pd.DataFrame(records)


def compute_stats(equity_series):
    """Compute key stats from an equity curve."""
    returns = equity_series.pct_change().dropna()
    total_ret = (equity_series.iloc[-1] / equity_series.iloc[0] - 1) * 100
    years = len(returns) / 252
    cagr = ((equity_series.iloc[-1] / equity_series.iloc[0]) ** (1 / years) - 1) * 100 if years > 0 else 0
    sharpe = returns.mean() / returns.std() * np.sqrt(252) if returns.std() > 0 else 0
    peak = equity_series.cummax()
    dd = (equity_series - peak) / peak * 100
    max_dd = dd.min()
    return {
        "total_ret": round(total_ret, 1),
        "cagr": round(cagr, 2),
        "sharpe": round(sharpe, 3),
        "max_dd": round(max_dd, 1),
        "final_equity": round(equity_series.iloc[-1], 0),
    }


def run_backtest_neutral_cap(qqq, spy, neutral_cap: float):
    """Same as run_backtest but caps hedge_pct to neutral_cap when regime is NEUTRAL."""
    n = len(qqq)
    WARMUP = 252

    spy_close = spy["close"].values
    spy_sma20 = spy["sma20"].values
    spy_sma200 = spy["sma200"].values
    vix = spy["vix"].values if "vix" in spy.columns else qqq["vix"].values

    qqq_close = qqq["close"].values
    qqq_ret = np.zeros(n)
    spy_ret = np.zeros(n)
    for i in range(1, n):
        qqq_ret[i] = (qqq_close[i] - qqq_close[i-1]) / qqq_close[i-1]
        spy_ret[i] = (spy_close[i] - spy_close[i-1]) / spy_close[i-1]

    records = []
    hedge_pct = 0.0
    portfolio_equity = CAPITAL
    qqq_equity = CAPITAL
    peak_equity = CAPITAL

    for i in range(WARMUP, n):
        qqq_equity *= (1 + qqq_ret[i])
        long_return = qqq_ret[i]
        hedge_return = -spy_ret[i] * (hedge_pct / 100.0)
        portfolio_equity *= (1 + long_return + hedge_return)
        peak_equity = max(peak_equity, portfolio_equity)
        drawdown_pct = (peak_equity - portfolio_equity) / peak_equity * 100.0

        if i >= WARMUP + 20:
            recent_rets = [qqq_ret[j] + (-spy_ret[j] * hedge_pct / 100.0) for j in range(i-19, i+1)]
            var95 = max(0, -np.percentile(recent_rets, 5) * 100.0)
        else:
            var95 = 2.5

        sma200_val = spy_sma200[i]
        sma20_val = spy_sma20[i]
        if np.isnan(sma200_val) or np.isnan(sma20_val) or sma200_val == 0 or sma20_val == 0:
            records.append({"date": qqq.iloc[i]["date"], "qqq_equity": qqq_equity,
                            "portfolio_equity": portfolio_equity, "hedge_pct": hedge_pct, "regime": "UNKNOWN"})
            continue

        sma200_5d = spy_sma200[max(0, i-5)]
        if np.isnan(sma200_5d) or sma200_5d == 0:
            sma200_5d = sma200_val
        vix_val = vix[i] if not np.isnan(vix[i]) else 20.0

        # Full engine logic (same as run_backtest)
        beta = 1.25
        crash_trigger = all([
            spy_close[i] < sma200_val,
            ((sma200_val - sma200_5d) / sma200_5d * 100.0) < -0.10,
            beta > 1.05, var95 > 3.0, drawdown_pct > 5.0,
        ])
        regime = _classify_market_regime(spy_close[i], sma200_val, vix_val, crash_trigger)

        beta_component = max(0, min(75, (beta - 1.0) * 100.0))
        var_component = 0.0 if var95 <= 2.5 else max(25, min(75, 25 + 10 * (var95 - 2.5)))
        base = max(beta_component, var_component)
        spy_dev = ((spy_close[i] - sma20_val) / sma20_val) * 100.0
        if spy_dev > 5.0: dev_bucket = 50.0
        elif spy_dev > 3.0: dev_bucket = 25.0
        elif spy_dev > 2.0: dev_bucket = 12.5
        elif spy_dev >= 0.0: dev_bucket = 0.0
        else: dev_bucket = 25.0
        if vix_val < 12: vix_adj = 10.0
        elif vix_val < 15: vix_adj = 5.0
        elif vix_val < 20: vix_adj = 0.0
        elif vix_val <= 25: vix_adj = 10.0
        else: vix_adj = 20.0
        adaptive = dev_bucket + vix_adj
        bear_trigger = spy_close[i] < sma200_val
        if bear_trigger:
            adaptive = max(adaptive, 75.0)
        long_only_target = min(100.0, max(base, adaptive))

        stress = 0.0
        if regime == "BEAR_STRESS": stress = 85.0
        elif regime == "BEAR": stress = 75.0
        elif regime == "VOLATILITY_SHOCK": stress = 90.0
        elif regime == "HIGH_VOLATILITY": stress = 65.0
        elif regime == "RISK_OFF": stress = 55.0
        elif regime == "EUPHORIA": stress = 20.0
        if drawdown_pct >= 10 or var95 >= 4.5: stress = max(stress, 85.0)
        elif drawdown_pct >= 7 or var95 >= 3.5: stress = max(stress, 70.0)

        if crash_trigger:
            extra_short = 25.0 if vix_val <= 30 else 50.0
            target = min(150.0, 100.0 + extra_short)
        else:
            target = max(long_only_target, stress)

        # ── THE KEY CHANGE: cap target in NEUTRAL regime ──
        if regime == "NEUTRAL" and target > neutral_cap:
            target = neutral_cap

        if abs(target - hedge_pct) >= 5.0:
            hedge_pct = target

        records.append({"date": qqq.iloc[i]["date"], "qqq_equity": qqq_equity,
                        "portfolio_equity": portfolio_equity, "hedge_pct": hedge_pct,
                        "regime": regime, "vix": vix_val, "drawdown_pct": drawdown_pct})

    return pd.DataFrame(records)


def main():
    print("=" * 80)
    print("AdaptiveHedgeEngine Backtest — $100K Long QQQ + Adaptive SPY Hedge")
    print("=" * 80)

    print("\nLoading data...")
    qqq, spy = load_market_data()
    print(f"  QQQ: {len(qqq)} bars, SPY: {len(spy)} bars")

    results = run_backtest(qqq, spy)
    print(f"  Backtest: {len(results)} days ({results['date'].iloc[0]} → {results['date'].iloc[-1]})")

    # Overall stats
    qqq_stats = compute_stats(results["qqq_equity"])
    hedged_stats = compute_stats(results["portfolio_equity"])

    print(f"\n{'='*80}")
    print(f"{'Metric':<25} {'QQQ Buy & Hold':>18} {'QQQ + Adaptive Hedge':>22}")
    print(f"{'-'*65}")
    print(f"{'Total Return':<25} {qqq_stats['total_ret']:>17.1f}% {hedged_stats['total_ret']:>21.1f}%")
    print(f"{'CAGR':<25} {qqq_stats['cagr']:>17.2f}% {hedged_stats['cagr']:>21.2f}%")
    print(f"{'Sharpe':<25} {qqq_stats['sharpe']:>18.3f} {hedged_stats['sharpe']:>22.3f}")
    print(f"{'Max Drawdown':<25} {qqq_stats['max_dd']:>17.1f}% {hedged_stats['max_dd']:>21.1f}%")
    print(f"{'Final Equity':<25} ${qqq_stats['final_equity']:>16,.0f} ${hedged_stats['final_equity']:>20,.0f}")

    # Regime distribution
    print(f"\n{'='*80}")
    print("Regime Distribution & Hedge Levels")
    print(f"{'='*80}")
    regime_counts = results["regime"].value_counts()
    for regime, count in regime_counts.items():
        pct = count / len(results) * 100
        avg_hedge = results[results["regime"] == regime]["hedge_pct"].mean()
        print(f"  {regime:<20} {count:>6d} days ({pct:>5.1f}%)  avg hedge: {avg_hedge:>5.1f}%")

    # Annual breakdown
    results["year"] = pd.to_datetime(results["date"]).dt.year
    print(f"\n{'='*80}")
    print("Annual Breakdown")
    print(f"{'='*80}")
    print(f"{'Year':<6} {'QQQ':>9} {'Hedged':>9} {'Delta':>9} {'Avg Hedge%':>11} {'Max DD%':>9} {'Regime (most common)':>22}")
    print(f"{'-'*80}")

    for year, grp in results.groupby("year"):
        qqq_yr_ret = (grp["qqq_equity"].iloc[-1] / grp["qqq_equity"].iloc[0] - 1) * 100
        hedged_yr_ret = (grp["portfolio_equity"].iloc[-1] / grp["portfolio_equity"].iloc[0] - 1) * 100
        delta = hedged_yr_ret - qqq_yr_ret
        avg_hedge = grp["hedge_pct"].mean()
        # Max drawdown within year
        peak = grp["portfolio_equity"].cummax()
        yr_dd = ((grp["portfolio_equity"] - peak) / peak * 100).min()
        top_regime = grp["regime"].value_counts().index[0]
        print(f"{year:<6} {qqq_yr_ret:>+8.1f}% {hedged_yr_ret:>+8.1f}% {delta:>+8.1f}% {avg_hedge:>10.1f}% {yr_dd:>+8.1f}% {top_regime:>22}")

    # Key stress periods
    print(f"\n{'='*80}")
    print("Key Stress Periods — Did the hedge protect?")
    print(f"{'='*80}")
    stress_periods = [
        ("GFC", "2008-09-01", "2009-03-09"),
        ("COVID Crash", "2020-02-19", "2020-03-23"),
        ("2022 Bear", "2022-01-03", "2022-10-12"),
        ("Tariff Shock", "2025-02-19", "2025-04-08"),
    ]
    for label, start_dt, end_dt in stress_periods:
        mask = (pd.to_datetime(results["date"]) >= start_dt) & (pd.to_datetime(results["date"]) <= end_dt)
        period = results[mask]
        if len(period) < 2:
            print(f"  {label}: insufficient data")
            continue
        qqq_dd = (period["qqq_equity"].iloc[-1] / period["qqq_equity"].iloc[0] - 1) * 100
        hedged_dd = (period["portfolio_equity"].iloc[-1] / period["portfolio_equity"].iloc[0] - 1) * 100
        avg_h = period["hedge_pct"].mean()
        top_r = period["regime"].value_counts().index[0]
        print(f"  {label:<20} QQQ: {qqq_dd:>+7.1f}%  Hedged: {hedged_dd:>+7.1f}%  "
              f"Protection: {qqq_dd - hedged_dd:>+7.1f}%  Avg hedge: {avg_h:.0f}%  Regime: {top_r}")

    # ══════════════════════════════════════════════════════════════════════
    # NEUTRAL CAP SWEEP — can we keep stress protection + reduce bull drag?
    # ══════════════════════════════════════════════════════════════════════
    print("\n\n" + "=" * 100)
    print("NEUTRAL CAP SWEEP — Same bear/stress logic, different NEUTRAL hedge ceiling")
    print("=" * 100)

    caps = [0, 5, 10, 15, 25, 35]  # 35 = current effective level
    stress_periods = [
        ("GFC", "2008-09-01", "2009-03-09"),
        ("COVID", "2020-02-19", "2020-03-23"),
        ("2022 Bear", "2022-01-03", "2022-10-12"),
        ("Tariffs", "2025-02-19", "2025-04-08"),
    ]

    # Header
    print(f"\n{'Cap':>5} {'CAGR':>7} {'Sharpe':>7} {'MaxDD':>8} {'Final $':>12}", end="")
    for sp_label, _, _ in stress_periods:
        print(f" {sp_label:>10}", end="")
    print()
    print("-" * (45 + 11 * len(stress_periods)))

    # QQQ baseline
    qqq_stats = compute_stats(results["qqq_equity"])
    print(f"{'QQQ':>5} {qqq_stats['cagr']:>6.2f}% {qqq_stats['sharpe']:>7.3f} {qqq_stats['max_dd']:>7.1f}% ${qqq_stats['final_equity']:>10,.0f}", end="")
    for sp_label, sp_start, sp_end in stress_periods:
        mask = (pd.to_datetime(results["date"]) >= sp_start) & (pd.to_datetime(results["date"]) <= sp_end)
        period = results[mask]
        if len(period) >= 2:
            dd = (period["qqq_equity"].iloc[-1] / period["qqq_equity"].iloc[0] - 1) * 100
            print(f" {dd:>+9.1f}%", end="")
        else:
            print(f" {'N/A':>10}", end="")
    print()

    for cap in caps:
        r = run_backtest_neutral_cap(qqq, spy, float(cap))
        s = compute_stats(r["portfolio_equity"])
        label = f"{cap}%" if cap > 0 else "0%"
        print(f"{label:>5} {s['cagr']:>6.2f}% {s['sharpe']:>7.3f} {s['max_dd']:>7.1f}% ${s['final_equity']:>10,.0f}", end="")
        for sp_label, sp_start, sp_end in stress_periods:
            mask = (pd.to_datetime(r["date"]) >= sp_start) & (pd.to_datetime(r["date"]) <= sp_end)
            period = r[mask]
            if len(period) >= 2:
                dd = (period["portfolio_equity"].iloc[-1] / period["portfolio_equity"].iloc[0] - 1) * 100
                print(f" {dd:>+9.1f}%", end="")
            else:
                print(f" {'N/A':>10}", end="")
        print()

    print(f"\n  Note: Bear/stress regime logic is IDENTICAL across all rows.")
    print(f"  Only the NEUTRAL regime hedge ceiling changes.")

    # ══════════════════════════════════════════════════════════════════════
    # BEAR-ONLY HEDGE P&L — what does the short SPY position make?
    # ══════════════════════════════════════════════════════════════════════
    print("\n\n" + "=" * 100)
    print("BEAR-ONLY HEDGE P&L — 0% neutral cap, hedge only active below SMA200")
    print("=" * 100)

    r0 = run_backtest_neutral_cap(qqq, spy, 0.0)
    n = len(r0)

    # Track bear episodes and per-day hedge P&L
    spy_close = spy["close"].values
    spy_sma200 = spy["sma200"].values
    qqq_close = qqq["close"].values
    spy_ret = np.zeros(len(spy))
    qqq_ret = np.zeros(len(qqq))
    for i in range(1, len(spy)):
        spy_ret[i] = (spy_close[i] - spy_close[i-1]) / spy_close[i-1]
        qqq_ret[i] = (qqq_close[i] - qqq_close[i-1]) / qqq_close[i-1]

    WARMUP = 252
    episodes = []
    current_episode = None
    total_hedge_pnl_pct = 0.0
    total_qqq_pnl_pct = 0.0
    bear_days = 0

    for idx in range(len(r0)):
        i = idx + WARMUP
        if i >= len(spy):
            break
        regime = r0.iloc[idx]["regime"]
        hedge_pct = r0.iloc[idx]["hedge_pct"]
        date = r0.iloc[idx]["date"]

        is_bear = regime in ("BEAR", "BEAR_STRESS", "CRASH", "VOLATILITY_SHOCK")

        if is_bear and i > 0:
            bear_days += 1
            # Hedge P&L: short SPY at hedge_pct of gross
            day_hedge_pnl = -spy_ret[i] * (hedge_pct / 100.0) * 100  # as % of portfolio
            day_qqq_pnl = qqq_ret[i] * 100
            total_hedge_pnl_pct += day_hedge_pnl
            total_qqq_pnl_pct += day_qqq_pnl

            if current_episode is None:
                current_episode = {
                    "start": date, "end": date, "days": 1,
                    "hedge_pnl_pct": day_hedge_pnl, "qqq_pnl_pct": day_qqq_pnl,
                    "avg_hedge": hedge_pct, "hedge_sum": hedge_pct,
                }
            else:
                current_episode["end"] = date
                current_episode["days"] += 1
                current_episode["hedge_pnl_pct"] += day_hedge_pnl
                current_episode["qqq_pnl_pct"] += day_qqq_pnl
                current_episode["hedge_sum"] += hedge_pct
        else:
            if current_episode is not None:
                current_episode["avg_hedge"] = current_episode["hedge_sum"] / current_episode["days"]
                episodes.append(current_episode)
                current_episode = None

    if current_episode is not None:
        current_episode["avg_hedge"] = current_episode["hedge_sum"] / current_episode["days"]
        episodes.append(current_episode)

    # Filter to episodes >= 5 days (skip noise)
    sig_episodes = [e for e in episodes if e["days"] >= 5]

    print(f"\n  Total bear days: {bear_days} ({bear_days/len(r0)*100:.1f}% of all days)")
    print(f"  Total bear episodes (≥5 days): {len(sig_episodes)}")
    print(f"\n  Cumulative hedge P&L (% of portfolio): {total_hedge_pnl_pct:+.1f}%")
    print(f"  Cumulative QQQ P&L during bear days:    {total_qqq_pnl_pct:+.1f}%")
    print(f"  Net (QQQ + hedge):                      {total_qqq_pnl_pct + total_hedge_pnl_pct:+.1f}%")

    print(f"\n  Bear Episodes (≥5 days):")
    print(f"  {'Start':<12} {'End':<12} {'Days':>5} {'QQQ':>9} {'Hedge':>9} {'Net':>9} {'Avg H%':>7}")
    print(f"  {'-'*68}")
    for e in sig_episodes:
        start_str = str(e['start'])[:10]
        end_str = str(e['end'])[:10]
        net = e['qqq_pnl_pct'] + e['hedge_pnl_pct']
        print(f"  {start_str:<12} {end_str:<12} {e['days']:>5} "
              f"{e['qqq_pnl_pct']:>+8.1f}% {e['hedge_pnl_pct']:>+8.1f}% "
              f"{net:>+8.1f}% {e['avg_hedge']:>6.0f}%")

    # Summary: wins vs losses
    winning = [e for e in sig_episodes if e['hedge_pnl_pct'] > 0]
    losing = [e for e in sig_episodes if e['hedge_pnl_pct'] <= 0]
    print(f"\n  Episodes where hedge was profitable: {len(winning)}/{len(sig_episodes)}")
    if winning:
        print(f"    Avg hedge P&L on wins:  {np.mean([e['hedge_pnl_pct'] for e in winning]):+.1f}%")
    if losing:
        print(f"    Avg hedge P&L on losses: {np.mean([e['hedge_pnl_pct'] for e in losing]):+.1f}%")


if __name__ == "__main__":
    main()
