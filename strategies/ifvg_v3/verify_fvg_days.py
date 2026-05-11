#!/usr/bin/env python3
"""Verify recent FVG days for a ticker using IFVG V3 raw daily rules."""

from __future__ import annotations

import argparse

import data_cache


def fmt(v: float) -> str:
    return f"{float(v):.2f}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify recent FVG days")
    parser.add_argument("ticker", help="Ticker symbol, e.g. MU")
    parser.add_argument("--last", type=int, default=3, help="Number of FVG days to show")
    parser.add_argument("--start-date", default="2000-01-01")
    args = parser.parse_args()

    ticker = args.ticker.upper().strip()
    df = data_cache.get_cached_ticker_data(ticker, args.start_date)
    df = df.sort_index()

    fvg_days = []
    for i in range(2, len(df)):
        curr = df.iloc[i]
        prev2 = df.iloc[i - 2]
        date = df.index[i].date()
        prev2_date = df.index[i - 2].date()

        bullish = curr["low"] > prev2["high"]
        bearish = curr["high"] < prev2["low"]

        if bullish:
            fvg_days.append(
                {
                    "date": date,
                    "type": "BULLISH",
                    "rule": f"low[{date}] {fmt(curr['low'])} > high[{prev2_date}] {fmt(prev2['high'])}",
                    "zone_low": prev2["high"],
                    "zone_high": curr["low"],
                    "open": curr["open"],
                    "high": curr["high"],
                    "low": curr["low"],
                    "close": curr["close"],
                }
            )
        elif bearish:
            fvg_days.append(
                {
                    "date": date,
                    "type": "BEARISH",
                    "rule": f"high[{date}] {fmt(curr['high'])} < low[{prev2_date}] {fmt(prev2['low'])}",
                    "zone_low": curr["high"],
                    "zone_high": prev2["low"],
                    "open": curr["open"],
                    "high": curr["high"],
                    "low": curr["low"],
                    "close": curr["close"],
                }
            )

    print(f"{ticker} data last bar: {df.index[-1].date()}")
    print(f"Total FVG days: {len(fvg_days)}")
    print(f"Last {args.last} FVG days:")

    for row in fvg_days[-args.last :]:
        gap = row["zone_high"] - row["zone_low"]
        print()
        print(f"{row['date']} {row['type']}")
        print(f"  OHLC O={fmt(row['open'])} H={fmt(row['high'])} L={fmt(row['low'])} C={fmt(row['close'])}")
        print(f"  Zone {fmt(row['zone_low'])} -> {fmt(row['zone_high'])}; size {fmt(gap)}")
        print(f"  Rule {row['rule']}")


if __name__ == "__main__":
    main()
