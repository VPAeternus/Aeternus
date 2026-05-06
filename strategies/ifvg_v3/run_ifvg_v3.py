#!/usr/bin/env python3
"""Run IFVG V3 short-only scanner/backtest from this folder."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from portfolio_v3 import V3PortfolioExecutor


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

    results_path = Path("portfolio_ticker_results.csv")
    signals_path = Path("live_signals.json")

    if results_path.exists():
        results = pd.read_csv(results_path)
        print("\nResult file:", results_path.resolve())
        print(results.to_string(index=False))

    if signals_path.exists():
        signals = json.loads(signals_path.read_text())
        print("\nLive signals:", len(signals))
        print("Signal file:", signals_path.resolve())


if __name__ == "__main__":
    main()
