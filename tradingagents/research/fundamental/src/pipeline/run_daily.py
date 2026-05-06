from __future__ import annotations

import argparse
from pathlib import Path

from src.features.monitoring import compute_active_monitoring_score
from src.features.signal_freshness import compute_signal_freshness
from src.ingest.prices import compute_return_checkpoints, fetch_yahoo_ohlcv
from src.reporting.daily_report import write_daily_reports
from src.storage import add_run_lineage, make_pipeline_run_id, read_rows, read_table, write_table


def _price_rows_for(price_rows: list[dict], ticker: str) -> list[dict]:
    return [row for row in price_rows if str(row.get("ticker", "")).upper() == ticker.upper()]


def update_monitoring_rows(rows: list[dict], *, as_of: str, price_rows: list[dict] | None = None) -> list[dict]:
    out: list[dict] = []
    for row in rows:
        prices = _price_rows_for(price_rows or [], str(row.get("ticker", "")))
        if prices and row.get("tradable_date"):
            row = {
                **row,
                **compute_return_checkpoints(
                    prices,
                    tradable_date=str(row["tradable_date"]),
                    actual_entry_price=float(row["actual_entry_price"]) if row.get("actual_entry_price") not in {"", None} else None,
                ),
            }
        freshness = compute_signal_freshness(str(row["tradable_date"]), as_of) if row.get("tradable_date") else {}
        scores = compute_active_monitoring_score(row)
        out.append({**row, **freshness, **scores})
    return out


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run daily candidate/position monitoring pipeline")
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--lake-root", type=Path, default=Path("outputs/live/parquet"))
    parser.add_argument("--input", type=Path, default=None, help="Optional CSV/Parquet override for candidate rows")
    parser.add_argument("--fetch-prices", action="store_true")
    parser.add_argument("--price-start", default=None)
    parser.add_argument("--pipeline-run-id", default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.input:
        rows = read_rows(args.input)
    else:
        rows = read_table(args.lake_root, "candidate_scores").fillna("").to_dict("records")
    price_rows = read_table(args.lake_root, "price_history").fillna("").to_dict("records")
    if args.fetch_prices:
        tickers = sorted({str(row.get("ticker", "")).upper() for row in rows if row.get("ticker")})
        fetched = fetch_yahoo_ohlcv(tickers, start=args.price_start or args.as_of, end=None)
        if fetched:
            write_table(args.lake_root, "price_history", add_run_lineage(fetched, pipeline_run_id=args.pipeline_run_id or make_pipeline_run_id("prices"), as_of_date=args.as_of))
            price_rows.extend(fetched)
    monitored = update_monitoring_rows(rows, as_of=args.as_of, price_rows=price_rows)
    run_id = args.pipeline_run_id or make_pipeline_run_id("daily")
    lineage = add_run_lineage(monitored, pipeline_run_id=run_id, as_of_date=args.as_of)
    write_table(args.lake_root, "candidate_monitoring", lineage)
    write_daily_reports(lineage, as_of=args.as_of)
    print(f"wrote candidate_monitoring rows={len(lineage)} run_id={run_id}")


if __name__ == "__main__":
    main()
