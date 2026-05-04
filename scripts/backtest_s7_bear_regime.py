#!/usr/bin/env python3
"""
Backtest S7a (Bear Overnight) and S7b (Bear Day Trade) signals.

1-share fixed sizing, GROSS P&L (zero transaction costs), 1999-2026.

S7a — Bear Overnight: SHORT at Close[i], COVER at Open[i+1]
S7b — Bear Day Trade:  SHORT at Open[i+1], COVER at Close[i+1]

Shared gate (_weak_regime_sma_check):
  Close > SMA3, Close < SMA20, Close < SMA50, Close < SMA200

S7a VIX: [20,30) OR [40,200)
S7b VIX: [20,25) OR [30,40)
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tradingagents.phase_engine import data_engine, phase_engine, config as cfg

TICKERS = ["QQQ", "SPY"]
START = "1999-01-01"


def backtest_s7(ticker: str):
    """Run S7a and S7b backtest for a single ticker. Returns per-signal trade lists."""
    df = data_engine.load(ticker, start=START)
    phases = phase_engine.classify_phases(df)
    n = len(df)

    overnight_trades = []  # S7a
    daytrade_trades = []   # S7b

    for i in range(n - 1):
        # S7a — overnight
        sig_on = phase_engine.should_short_overnight(df, phases, i, ticker)
        if sig_on:
            entry = df.iloc[i]["close"]
            exit_p = df.iloc[i + 1]["open"]
            pnl = entry - exit_p  # short P&L
            overnight_trades.append({
                "date": str(df.iloc[i]["date"]),
                "entry": round(entry, 4),
                "exit": round(exit_p, 4),
                "pnl": round(pnl, 4),
            })

        # S7b — day trade (RTH) — test independently, not via priority router
        if phase_engine.is_weak_regime_rth(df, phases, i):
            entry = df.iloc[i + 1]["open"]
            exit_p = df.iloc[i + 1]["close"]
            pnl = entry - exit_p
            daytrade_trades.append({
                "date": str(df.iloc[i + 1]["date"]),
                "entry": round(entry, 4),
                "exit": round(exit_p, 4),
                "pnl": round(pnl, 4),
            })

    return overnight_trades, daytrade_trades


def stats(trades: list) -> dict:
    """Compute full stats from a trade list."""
    if not trades:
        return {"trades": 0}
    pnls = [t["pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    total_pnl = sum(pnls)
    gross_wins = sum(wins) if wins else 0.0
    gross_losses = abs(sum(losses)) if losses else 0.0001
    return {
        "trades": len(pnls),
        "pnl": round(total_pnl, 2),
        "wr_pct": round(len(wins) / len(pnls) * 100, 1),
        "pf": round(gross_wins / gross_losses, 2) if gross_losses > 0 else float("inf"),
        "avg_win": round(gross_wins / len(wins), 2) if wins else 0.0,
        "avg_loss": round(-gross_losses / len(losses), 2) if losses else 0.0,
    }


def main():
    print("=" * 80)
    print("S7 Bear Regime Backtest — 1-share, zero costs, 1999-2026")
    print("=" * 80)

    rows = []
    for ticker in TICKERS:
        print(f"\nLoading {ticker}...")
        overnight, daytrade = backtest_s7(ticker)
        s_on = stats(overnight)
        s_dt = stats(daytrade)
        rows.append(("Bear Overnight", ticker, s_on))
        rows.append(("Bear Day", ticker, s_dt))

    print("\n" + "-" * 90)
    print(f"{'Signal':<18} {'Ticker':<8} {'Trades':>7} {'PnL':>10} {'WR%':>7} {'PF':>7} {'Avg Win':>10} {'Avg Loss':>10}")
    print("-" * 90)
    for label, ticker, s in rows:
        if s["trades"] == 0:
            print(f"{label:<18} {ticker:<8} {'0':>7}")
            continue
        print(
            f"{label:<18} {ticker:<8} {s['trades']:>7} "
            f"${s['pnl']:>+8.2f} {s['wr_pct']:>6.1f}% {s['pf']:>6.2f} "
            f"${s['avg_win']:>8.2f} ${s['avg_loss']:>8.2f}"
        )
    print("-" * 90)

    # ── S7a hold-period analysis (naive, allows overlapping entries) ─────
    print("\n\nS7a Bear Overnight — Hold Period Analysis (SHORT at Close[i], COVER at Close[i+N])")
    print("  NOTE: Naive — each signal is an independent trade, overlaps allowed")
    print("=" * 95)
    hold_days = [1, 2, 3, 4, 5]
    for ticker in TICKERS:
        df = data_engine.load(ticker, start=START)
        phases = phase_engine.classify_phases(df)
        n = len(df)

        print(f"\n  {ticker}")
        print(f"  {'Hold':>6} {'Trades':>7} {'PnL':>10} {'WR%':>7} {'PF':>7} {'Avg Win':>10} {'Avg Loss':>10} {'Avg PnL':>10}")
        print(f"  {'-'*75}")

        for hold in hold_days:
            trades_pnl = []
            for i in range(n - hold):
                sig = phase_engine.should_short_overnight(df, phases, i, ticker)
                if not sig:
                    continue
                entry = df.iloc[i]["close"]
                exit_p = df.iloc[i + hold]["close"]
                trades_pnl.append(entry - exit_p)

            if not trades_pnl:
                print(f"  {hold:>4}d  {'0':>7}")
                continue
            wins = [p for p in trades_pnl if p > 0]
            losses = [p for p in trades_pnl if p <= 0]
            total = sum(trades_pnl)
            gw = sum(wins) if wins else 0.0
            gl = abs(sum(losses)) if losses else 0.0001
            print(
                f"  {hold:>4}d  {len(trades_pnl):>7} ${total:>+8.2f} "
                f"{len(wins)/len(trades_pnl)*100:>6.1f}% {gw/gl:>6.2f} "
                f"${gw/len(wins) if wins else 0:>8.2f} "
                f"${-gl/len(losses) if losses else 0:>8.2f} "
                f"${total/len(trades_pnl):>8.2f}"
            )

    # ── Combined S7 position manager (no stacking) ───────────────────────
    print("\n\n" + "=" * 95)
    print("Combined S7 Position Manager — 1 position at a time, no stacking")
    print("  Entry: S7a fires → SHORT at Close[i]")
    print("  Hold:  N days (cover at Close[i+N])")
    print("  Re-signal while short → extend hold (reset exit to i+N)")
    print("  S7b signals during hold are absorbed (already short)")
    print("=" * 95)

    for ticker in TICKERS:
        df = data_engine.load(ticker, start=START)
        phases = phase_engine.classify_phases(df)
        n = len(df)

        print(f"\n  {ticker}")
        hdr = (f"  {'Hold':>6} {'Trades':>7} {'PnL':>10} {'WR%':>7} {'PF':>7} "
               f"{'Avg Win':>10} {'Avg Loss':>10} {'Days Short':>11} {'S7b Absorb':>11}")
        print(hdr)
        print(f"  {'-'*95}")

        for hold in hold_days:
            trades = []
            entry_price = None
            exit_bar = -1
            s7b_absorbed = 0
            days_short = 0

            for i in range(n):
                in_position = entry_price is not None and i <= exit_bar

                # Count S7b signals absorbed while already short
                if in_position and i > 0:
                    if phase_engine.is_weak_regime_rth(df, phases, i - 1):
                        s7b_absorbed += 1

                # S7a signal check
                sig = ""
                if i < n - 1:
                    sig = phase_engine.should_short_overnight(df, phases, i, ticker)

                if sig:
                    if not in_position:
                        # New entry
                        entry_price = df.iloc[i]["close"]
                        exit_bar = min(i + hold, n - 1)
                    else:
                        # Already short — extend hold
                        exit_bar = min(i + hold, n - 1)

                # Update position state after potential entry/extension
                in_position = entry_price is not None and i <= exit_bar

                if in_position:
                    days_short += 1
                    if i >= exit_bar:
                        exit_price = df.iloc[i]["close"]
                        pnl = entry_price - exit_price
                        trades.append(pnl)
                        entry_price = None
                        exit_bar = -1

            # Close any open position at end
            if entry_price is not None:
                exit_price = df.iloc[n - 1]["close"]
                pnl = entry_price - exit_price
                trades.append(pnl)

            if not trades:
                print(f"  {hold:>4}d  {'0':>7}")
                continue
            wins = [p for p in trades if p > 0]
            losses = [p for p in trades if p <= 0]
            total = sum(trades)
            gw = sum(wins) if wins else 0.0
            gl = abs(sum(losses)) if losses else 0.0001
            print(
                f"  {hold:>4}d  {len(trades):>7} ${total:>+8.2f} "
                f"{len(wins)/len(trades)*100:>6.1f}% {gw/gl:>6.02f} "
                f"${gw/len(wins) if wins else 0:>8.2f} "
                f"${-gl/len(losses) if losses else 0:>8.2f} "
                f"  {days_short:>8}   {s7b_absorbed:>8}"
            )


if __name__ == "__main__":
    main()
