#!/usr/bin/env python3
"""
S7a Overnight Bear Regime — Standalone CLI

Signal: SHORT at Close[i], COVER at Open[i+1]

Gate:
  1. SMA stack: Close > SMA3 AND Close < SMA20 AND Close < SMA50 AND Close < SMA200
  2. VIX in [20-30] or [40+]

Tickers: QQQ, SPY (indices only)

Usage:
  python scripts/s7a_overnight.py --ticker QQQ --start 1999-01-01
"""

import sys
import os
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tradingagents.phase_engine import data_engine, phase_engine, config as cfg


def backtest_s7a(ticker: str, start: str = "1999-01-01"):
    """
    Run S7a overnight backtest for a single ticker.

    Returns:
        overnight_trades: list of trade dicts (date, entry, exit, pnl)
        stats: dict with summary metrics
    """
    df = data_engine.load(ticker, start=start)
    phases = phase_engine.classify_phases(df)
    n = len(df)

    overnight_trades = []

    for i in range(n - 1):
        # S7a signal check
        if phase_engine.is_weak_regime_overnight(df, phases, i):
            entry = df.iloc[i]["close"]
            exit_p = df.iloc[i + 1]["open"]
            pnl = entry - exit_p  # short P&L

            overnight_trades.append({
                "date": str(df.iloc[i]["date"]),
                "entry": round(entry, 4),
                "exit": round(exit_p, 4),
                "pnl": round(pnl, 4),
            })

    return overnight_trades, compute_stats(overnight_trades)


def compute_stats(trades: list) -> dict:
    """Compute full stats from a trade list."""
    if not trades:
        return {
            "trades": 0,
            "pnl": 0.0,
            "wr_pct": 0.0,
            "pf": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
        }

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
        "pf": round(gross_wins / gross_losses, 2) if gross_losses > 0 else 0.0,
        "avg_win": round(gross_wins / len(wins), 2) if wins else 0.0,
        "avg_loss": round(-gross_losses / len(losses), 2) if losses else 0.0,
    }


def print_table(rows: list):
    """Print formatted stats table."""
    print("\n" + "-" * 90)
    print(
        f"{'Strategy':<18} {'Ticker':<8} {'Trades':>7} {'PnL':>10} {'WR%':>7} {'PF':>7} {'Avg Win':>10} {'Avg Loss':>10}"
    )
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


def main():
    parser = argparse.ArgumentParser(
        description="S7a Overnight Bear Regime backtest (SHORT at Close, COVER at Open)"
    )
    parser.add_argument(
        "--ticker",
        type=str,
        default="QQQ",
        help="Ticker symbol (default: QQQ)",
    )
    parser.add_argument(
        "--start",
        type=str,
        default="1999-01-01",
        help="Start date (default: 1999-01-01)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run backtest for all S7 tickers (QQQ, SPY)",
    )

    args = parser.parse_args()

    print("=" * 80)
    print("S7a Overnight Bear Regime — Standalone Backtest")
    print("  Signal: SHORT at Close[i], COVER at Open[i+1]")
    print("  Gate:   SMA stack (C>SMA3, C<SMA20, C<SMA50, C<SMA200)) + VIX [20-30] or [40+]")
    print("=" * 80)

    tickers = [args.ticker.upper()] if not args.all else cfg.S7_TICKERS

    rows = []
    for ticker in tickers:
        print(f"\nLoading {ticker}...")
        overnight, stats = backtest_s7a(ticker, args.start)
        rows.append(("S7a Overnight", ticker, stats))

    print_table(rows)

    # ── Hold period analysis ───────────────────────────────────────────────────
    print("\n\nS7a Overnight — Hold Period Analysis")
    print("  SHORT at Close[i], COVER at Close[i+N]")
    print("=" * 95)

    hold_days = [1, 2, 3, 4, 5]
    for ticker in tickers:
        df = data_engine.load(ticker, start=args.start)
        phases = phase_engine.classify_phases(df)
        n = len(df)

        print(f"\n  {ticker}")
        hdr = (f"  {'Hold':>6} {'Trades':>7} {'PnL':>10} {'WR%':>7} {'PF':>7} "
               f"{'Avg Win':>10} {'Avg Loss':>10} {'Avg PnL':>10}")
        print(hdr)
        print(f"  {'-'*85}")

        for hold in hold_days:
            trades_pnl = []
            for i in range(n - hold):
                if phase_engine.is_weak_regime_overnight(df, phases, i):
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
                f"{len(wins)/len(trades_pnl)*100:>6.1f}% "
                f"${gw/len(wins) if wins else 0:>8.2f} "
                f"${-gl/len(losses) if losses else 0:>8.2f} "
                f"${total/len(trades_pnl):>8.2f}"
            )


if __name__ == "__main__":
    main()
