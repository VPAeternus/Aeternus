from __future__ import annotations

import argparse
import csv
from pathlib import Path

DEFAULT_SOURCE = Path("Growth/be_lte_nvda_sndk_venture_score_source.csv")
DEFAULT_OUTPUT = Path("Growth/be_lte_nvda_sndk_venture_buys.csv")
DEFAULT_ORDER = ["BE", "LTE", "NVDA", "SNDK"]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default=str(DEFAULT_SOURCE))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument(
        "--tickers",
        default=",".join(DEFAULT_ORDER),
        help="Comma-separated output tickers as they appear in the source CSV",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    source = Path(str(args.source))
    output = Path(str(args.output))
    order = [
        item.strip().upper() for item in str(args.tickers).split(",") if item.strip()
    ]

    with source.open(newline="") as handle:
        rows = list(csv.DictReader(handle))

    by_quarter: dict[str, dict[str, dict[str, str]]] = {}
    for row in rows:
        by_quarter.setdefault(str(row["quarter"]).strip(), {})[
            str(row["ticker"]).strip().upper()
        ] = row

    fieldnames = ["quarter", "winner_filing_date", "winner_tradable_date"]
    for ticker in order:
        fieldnames.extend([ticker.lower(), f"{ticker.lower()}_score"])

    out_rows = []
    for quarter in sorted(by_quarter):
        item = {
            "quarter": quarter,
            "winner_filing_date": "",
            "winner_tradable_date": "",
        }
        for ticker in order:
            row = by_quarter[quarter].get(ticker, {})
            active = str(row.get("active", "0")).strip() == "1"
            buy_col = ticker.lower()
            score_col = f"{ticker.lower()}_score"
            item[buy_col] = str(row.get("buy", "0")).strip() if active else "0"
            item[score_col] = (
                str(row.get("venture_score", "")).strip() if active else ""
            )
            if active and item[buy_col] == "1":
                item["winner_filing_date"] = str(row.get("filing_date", "")).strip()
                item["winner_tradable_date"] = quarter
        out_rows.append(item)

    with output.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(out_rows)

    print(f"Wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
