#!/usr/bin/env python3
"""Run IFVG V3 short-only scanner/backtest from this folder."""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

import pandas as pd

from portfolio_v3 import V3PortfolioExecutor


RESULTS_HISTORY_FILE = Path("ifvg_v3_results_history.csv")
TRADES_HISTORY_FILE = Path("ifvg_v3_all_trades_history.csv")


def _append_results_history(results: pd.DataFrame, args: argparse.Namespace) -> Path:
    run_at = dt.datetime.now().isoformat(timespec="seconds")
    history_rows = results.copy()
    history_rows.insert(0, "run_at", run_at)
    history_rows["start_date"] = args.start_date
    history_rows["target_pct"] = args.target_pct
    history_rows["sma50_filter"] = "BELOW"
    history_rows["sma10_exit"] = "CLOSE"
    history_rows["vix_filter"] = not args.no_vix

    if RESULTS_HISTORY_FILE.exists():
        existing = pd.read_csv(RESULTS_HISTORY_FILE)
        combined = pd.concat([existing, history_rows], ignore_index=True)
    else:
        combined = history_rows

    combined.to_csv(RESULTS_HISTORY_FILE, index=False)
    return RESULTS_HISTORY_FILE


def _append_trades_history(trades: list, args: argparse.Namespace) -> Path:
    run_at = dt.datetime.now().isoformat(timespec="seconds")
    cols = [
        "run_at",
        "ticker",
        "type",
        "status",
        "reason",
        "entry_date",
        "entry_price",
        "exit_date",
        "exit_price",
        "stop_loss",
        "take_profit",
        "quantity",
        "pnl",
        "start_date",
        "target_pct",
        "sma50_filter",
        "sma10_exit",
        "vix_filter",
    ]

    if trades:
        trade_rows = pd.DataFrame([t.__dict__ for t in trades])
        trade_rows.insert(0, "run_at", run_at)
        trade_rows["start_date"] = args.start_date
        trade_rows["target_pct"] = args.target_pct
        trade_rows["sma50_filter"] = "BELOW"
        trade_rows["sma10_exit"] = "CLOSE"
        trade_rows["vix_filter"] = not args.no_vix
        trade_rows = trade_rows[cols]
    else:
        trade_rows = pd.DataFrame(columns=cols)

    if TRADES_HISTORY_FILE.exists():
        existing = pd.read_csv(TRADES_HISTORY_FILE)
        combined = pd.concat([existing, trade_rows], ignore_index=True)
    else:
        combined = trade_rows

    combined.to_csv(TRADES_HISTORY_FILE, index=False)
    return TRADES_HISTORY_FILE


def main() -> None:
    parser = argparse.ArgumentParser(description="Run IFVG V3 equity scanner")
    parser.add_argument("tickers", nargs="+", help="Ticker symbols, e.g. MU NVDA AMD")
    parser.add_argument("--start-date", default="2000-01-01")
    parser.add_argument("--target-pct", type=float, default=0.05)
    parser.add_argument("--no-vix", action="store_true", help="Disable VIX entry filter")
    args = parser.parse_args()

    tickers = [t.upper().strip() for t in args.tickers]
    executor = V3PortfolioExecutor(
        tickers=tickers,
        start_date=args.start_date,
        target_pct=args.target_pct,
        sma50_filter="BELOW",
        sma10_exit="CLOSE",
        vix_filter=not args.no_vix,
    )
    executor.run_portfolio()
    executor.generate_report()
    trades_history_path = _append_trades_history(executor.portfolio_trades, args)

    results_path = Path("portfolio_ticker_results.csv")
    signals_path = Path("live_signals.json")

    if results_path.exists():
        results = pd.read_csv(results_path)
        history_path = _append_results_history(results, args)
        print("\nResult file:", results_path.resolve())
        print(results.to_string(index=False))
        print("History file:", history_path.resolve())
        print("All-trades file:", trades_history_path.resolve())

    if signals_path.exists():
        signals = json.loads(signals_path.read_text())
        print("\nLive signals:", len(signals))
        print("Signal file:", signals_path.resolve())


if __name__ == "__main__":
    main()
