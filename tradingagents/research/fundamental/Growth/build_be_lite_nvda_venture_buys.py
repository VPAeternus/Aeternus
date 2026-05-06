from __future__ import annotations

import csv
from pathlib import Path

SOURCE = Path("Growth/be_lite_nvda_venture_score_source.csv")
OUTPUT = Path("Growth/be_lite_nvda_venture_buys.csv")
ORDER = ["BE", "LTE", "NVDA"]


def _clean_score(value: str) -> str:
    return str(value or "").strip()


def main() -> int:
    with SOURCE.open(newline="") as handle:
        rows = list(csv.DictReader(handle))

    by_quarter: dict[str, dict[str, dict[str, str]]] = {}
    for row in rows:
        quarter = str(row["quarter"]).strip()
        ticker = str(row["ticker"]).strip().upper()
        by_quarter.setdefault(quarter, {})[ticker] = row

    out_rows: list[dict[str, str]] = []
    for quarter in sorted(by_quarter):
        item = {"quarter": quarter}
        for ticker in ORDER:
            row = by_quarter[quarter].get(ticker, {})
            buy_col = ticker.lower()
            score_col = f"{ticker.lower()}_score"
            active = str(row.get("active", "0")).strip() == "1"
            item[buy_col] = str(row.get("buy", "0")).strip() if active else "0"
            item[score_col] = (
                _clean_score(row.get("venture_score", "")) if active else ""
            )
        out_rows.append(item)

    with OUTPUT.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "quarter",
                "be",
                "lte",
                "nvda",
                "be_score",
                "lte_score",
                "nvda_score",
            ],
        )
        writer.writeheader()
        writer.writerows(out_rows)

    print(f"Wrote {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
