from __future__ import annotations

import argparse
import csv
import io
import contextlib
import time
from pathlib import Path

import pandas as pd
import yfinance as yf


ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = Path.home() / ".cache" / "autoresearch_fundamentals"
DEFAULT_INPUT = ROOT / "Growth" / "earnings_8k_sec_parser" / "yahoo_fetch_candidates_2024Q3.csv"
DEFAULT_REPORT = ROOT / "Growth" / "earnings_8k_sec_parser" / "yahoo_price_fetch_report_2024Q3.csv"


def read_tickers(path: Path) -> list[str]:
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    tickers = sorted({str(row.get("ticker", "")).upper().strip() for row in rows if row.get("ticker")})
    return [ticker for ticker in tickers if ticker]


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def ticker_has_cached_price(ticker: str) -> bool:
    if (CACHE_DIR / f"prices_single_name_{ticker}.parquet").exists():
        return True
    for path in CACHE_DIR.glob("prices_*.parquet"):
        if "single_name" in path.name:
            continue
        try:
            frame = pd.read_parquet(path, columns=[(ticker, "Close")])
            if frame is not None and not frame.empty:
                return True
        except Exception:
            continue
    return False


def batch_path(prefix: str, batch_num: int) -> Path:
    return CACHE_DIR / f"prices_{prefix}_batch_{batch_num:04d}.parquet"


def download_batch(batch: list[str], output: Path, period: str, attempts: int) -> tuple[str, int, int]:
    for attempt in range(1, attempts + 1):
        try:
            sink = io.StringIO()
            with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
                frame = yf.download(
                    batch if len(batch) > 1 else batch[0],
                    period=period,
                    interval="1d",
                    auto_adjust=False,
                    progress=False,
                    group_by="ticker",
                    threads=True,
                )
            if frame is None or frame.empty:
                time.sleep(1.0)
                continue
            frame.to_parquet(output)
            tickers_ok = 0
            if isinstance(frame.columns, pd.MultiIndex):
                tickers_ok = len(set(frame.columns.get_level_values(0)))
            else:
                tickers_ok = 1
            return "fetched", len(frame), tickers_ok
        except Exception:
            if attempt == attempts:
                return "failed", 0, 0
            time.sleep(2.0)
    return "empty", 0, 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch raw Yahoo OHLCV for filtered candidate tickers")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--prefix", default="akg_2024Q3")
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--period", default="max")
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tickers = read_tickers(args.input)
    if args.limit is not None:
        tickers = tickers[: args.limit]

    rows: list[dict[str, object]] = []
    batches = [tickers[i : i + args.batch_size] for i in range(0, len(tickers), args.batch_size)]
    for batch_num, batch in enumerate(batches, start=1):
        out = batch_path(args.prefix, batch_num)
        if out.exists() and not args.force:
            rows.append({
                "batch": batch_num,
                "status": "already_cached_batch",
                "tickers_requested": len(batch),
                "rows": "",
                "tickers_returned": "",
                "output_path": str(out),
                "tickers": ";".join(batch),
            })
            continue
        uncached = [ticker for ticker in batch if args.force or not ticker_has_cached_price(ticker)]
        if not uncached:
            rows.append({
                "batch": batch_num,
                "status": "already_cached_tickers",
                "tickers_requested": len(batch),
                "rows": "",
                "tickers_returned": "",
                "output_path": "",
                "tickers": ";".join(batch),
            })
            continue
        status, n_rows, tickers_returned = download_batch(uncached, out, args.period, args.attempts)
        print(f"{batch_num}/{len(batches)} {status} requested={len(uncached)} returned={tickers_returned} rows={n_rows}", flush=True)
        rows.append({
            "batch": batch_num,
            "status": status,
            "tickers_requested": len(uncached),
            "rows": n_rows,
            "tickers_returned": tickers_returned,
            "output_path": str(out),
            "tickers": ";".join(uncached),
        })
        time.sleep(0.5)
    write_csv(args.report, rows)
    counts: dict[str, int] = {}
    for row in rows:
        counts[str(row["status"])] = counts.get(str(row["status"]), 0) + 1
    print(f"batches={len(rows)} tickers={len(tickers)} wrote={args.report}")
    for status, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        print(f"{status}: {count}")


if __name__ == "__main__":
    main()
