#!/usr/bin/env python3
"""Track support line from latest active bullish FVG."""

from __future__ import annotations

import argparse
from dataclasses import dataclass

import pandas as pd

import data_cache


@dataclass
class SupportEvent:
    date: pd.Timestamp
    event: str
    price: float | None
    close: float
    note: str


def compute_bullish_fvg_support(df: pd.DataFrame) -> tuple[pd.DataFrame, list[SupportEvent]]:
    """Return daily support line from latest active bullish FVG.

    Bullish FVG: low[t] > high[t-2].
    Support price: low[t].
    New bullish FVG replaces old support only if it moves support up.
    Close below active support removes line.
    """
    df = df.sort_index().copy()
    support = None
    support_source_date = None
    values = []
    source_dates = []
    events: list[SupportEvent] = []

    for i in range(len(df)):
        row = df.iloc[i]
        date = df.index[i]

        if support is not None and row["close"] < support:
            events.append(
                SupportEvent(
                    date=date,
                    event="BROKEN",
                    price=None,
                    close=float(row["close"]),
                    note=f"close {row['close']:.2f} below support {support:.2f} from {support_source_date.date()}",
                )
            )
            support = None
            support_source_date = None

        if i >= 2:
            prev2 = df.iloc[i - 2]
            prev2_date = df.index[i - 2]
            if row["low"] > prev2["high"]:
                new_support = float(row["low"])
                if support is None or new_support > support:
                    support = new_support
                    support_source_date = date
                    events.append(
                        SupportEvent(
                            date=date,
                            event="NEW_BULLISH_FVG_SUPPORT",
                            price=support,
                            close=float(row["close"]),
                            note=f"low {row['low']:.2f} > high[{prev2_date.date()}] {prev2['high']:.2f}",
                        )
                    )

        values.append(support)
        source_dates.append(support_source_date.date().isoformat() if support_source_date is not None else None)

    out = df.copy()
    out["bullish_fvg_support"] = values
    out["support_source_date"] = source_dates
    return out, events


def main() -> None:
    parser = argparse.ArgumentParser(description="Track latest bullish FVG support line")
    parser.add_argument("ticker", help="Ticker symbol, e.g. MU")
    parser.add_argument("--start-date", default="2000-01-01")
    parser.add_argument("--from-date", default=None)
    parser.add_argument("--to-date", default=None)
    args = parser.parse_args()

    ticker = args.ticker.upper().strip()
    df = data_cache.get_cached_ticker_data(ticker, args.start_date)
    support_df, events = compute_bullish_fvg_support(df)

    view = support_df
    if args.from_date:
        view = view[view.index >= pd.to_datetime(args.from_date)]
    if args.to_date:
        view = view[view.index <= pd.to_datetime(args.to_date)]

    event_rows = []
    for event in events:
        if args.from_date and event.date < pd.to_datetime(args.from_date):
            continue
        if args.to_date and event.date > pd.to_datetime(args.to_date):
            continue
        event_rows.append(
            {
                "date": event.date.date().isoformat(),
                "event": event.event,
                "support": "" if event.price is None else f"{event.price:.2f}",
                "close": f"{event.close:.2f}",
                "note": event.note,
            }
        )

    print(f"{ticker} data last bar: {support_df.index[-1].date()}")
    print("\nSupport events:")
    if event_rows:
        print(pd.DataFrame(event_rows).to_string(index=False))
    else:
        print("none")

    print("\nDaily support line:")
    cols = ["close", "bullish_fvg_support", "support_source_date"]
    print(view[cols].to_string(formatters={"close": "{:.2f}".format, "bullish_fvg_support": lambda v: "" if pd.isna(v) else f"{v:.2f}"}))


if __name__ == "__main__":
    main()
