from __future__ import annotations

import argparse
import csv
import re
import sys
from datetime import date
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config.cache_paths import sec_cache_root

from Growth.venture_mechanical_scorer import (
    _load_packets,
    _next_trading_day,
    _output_ticker,
    _score_packet,
)

DEFAULT_OUTPUT_TEMPLATE = "Growth/venture_scan_{label}_min{min_score}.csv"
QUARTER_RE = re.compile(r"^(?P<year>\d{4})Q(?P<quarter>[1-4])$")
FIELDNAMES = [
    "scan_quarter",
    "ticker",
    "filing_date",
    "tradable_date",
    "form",
    "venture_score",
    "archetype_path",
    "wave_exposure",
    "asymmetric_upside",
    "fundable_scaling",
    "filing_delta",
    "wave_torque_operating_leverage",
    "incumbent_saturation_penalty",
    "false_promise_penalty",
]


def _packet_dir() -> Path:
    return sec_cache_root("filing_packets")


def parse_quarter_bounds(quarter_label: str) -> tuple[date, date]:
    match = QUARTER_RE.fullmatch(quarter_label.strip().upper())
    if not match:
        raise ValueError(
            f"Quarter must look like YYYYQ1-YYYYQ4, got: {quarter_label}"
        )

    year = int(match.group("year"))
    quarter = int(match.group("quarter"))
    start_month = 1 + (quarter - 1) * 3
    start = date(year, start_month, 1)
    if quarter == 4:
        end = date(year, 12, 31)
    else:
        next_quarter_start = date(year, start_month + 3, 1)
        end = next_quarter_start.fromordinal(next_quarter_start.toordinal() - 1)
    return start, end


def _discover_cached_tickers() -> list[str]:
    return sorted(
        {
            path.name.split("_", 1)[0].upper()
            for path in _packet_dir().glob("*.json")
            if "_" in path.name
        }
    )


def _scan_row(
    *,
    label: str,
    ticker: str,
    packet,
    score: dict[str, int | str],
) -> dict[str, str]:
    row = {
        "scan_quarter": label,
        "ticker": _output_ticker(ticker),
        "filing_date": packet.filed,
        "tradable_date": _next_trading_day(packet.filed),
        "form": packet.form,
    }
    for key in FIELDNAMES:
        if key not in row:
            row[key] = str(score.get(key, ""))
    return row


def scan_date_range(
    start_date: str,
    end_date: str,
    *,
    min_score: int,
    tickers: list[str] | None = None,
    extraction_mode: str = "packet",
    label: str | None = None,
) -> list[dict[str, str]]:
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    active_tickers = [ticker.upper() for ticker in tickers] if tickers else None
    if active_tickers is None:
        active_tickers = _discover_cached_tickers()

    packets_by_ticker = _load_packets(
        active_tickers,
        extraction_mode=extraction_mode,
        min_filed=start_date,
    )
    rows: list[dict[str, str]] = []
    output_label = label or f"{start_date}_{end_date}"

    for ticker in active_tickers:
        prior = None
        for packet in packets_by_ticker.get(ticker, []):
            filed = date.fromisoformat(packet.filed)
            try:
                score = _score_packet(packet, prior)
            except ValueError:
                prior = packet
                continue
            prior = packet
            if filed < start or filed > end:
                continue
            if int(score["venture_score"]) < min_score:
                continue
            rows.append(
                _scan_row(
                    label=output_label,
                    ticker=ticker,
                    packet=packet,
                    score=score,
                )
            )

    rows.sort(
        key=lambda row: (
            row["scan_quarter"],
            -int(row["venture_score"]),
            row["filing_date"],
            row["ticker"],
        )
    )
    return rows


def scan_quarter(
    quarter_label: str,
    *,
    min_score: int,
    tickers: list[str] | None = None,
    extraction_mode: str = "packet",
) -> list[dict[str, str]]:
    quarter_start, quarter_end = parse_quarter_bounds(quarter_label)
    active_tickers = [ticker.upper() for ticker in tickers] if tickers else None
    if active_tickers is None:
        active_tickers = _discover_cached_tickers()

    packets_by_ticker = _load_packets(
        active_tickers,
        extraction_mode=extraction_mode,
        min_filed=quarter_start.isoformat(),
    )
    rows: list[dict[str, str]] = []

    for ticker in active_tickers:
        prior = None
        for packet in packets_by_ticker.get(ticker, []):
            filed = date.fromisoformat(packet.filed)
            try:
                score = _score_packet(packet, prior)
            except ValueError:
                prior = packet
                continue
            prior = packet
            if filed < quarter_start or filed > quarter_end:
                continue
            if int(score["venture_score"]) < min_score:
                continue

            rows.append(
                _scan_row(
                    label=quarter_label.upper(),
                    ticker=ticker,
                    packet=packet,
                    score=score,
                )
            )

    rows.sort(
        key=lambda row: (
            -int(row["venture_score"]),
            row["filing_date"],
            row["ticker"],
        )
    )
    return rows


def write_scan_csv(rows: list[dict[str, str]], output: Path) -> None:
    with output.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--quarter",
        default="",
        help="Calendar filing quarter to scan, e.g. 2026Q1",
    )
    parser.add_argument("--start-date", default="", help="Inclusive filing start date")
    parser.add_argument("--end-date", default="", help="Inclusive filing end date")
    parser.add_argument(
        "--min-score",
        type=int,
        required=True,
        help="Minimum venture score required for CSV inclusion",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Optional output path. Defaults to Growth/venture_scan_<quarter>_min<score>.csv",
    )
    parser.add_argument(
        "--tickers",
        default="",
        help="Optional comma-separated ticker filter. Default scans all cached packet tickers.",
    )
    parser.add_argument(
        "--extraction-mode",
        choices=["packet", "edgartools"],
        default="packet",
        help="Use cached packet sections or refresh extraction via edgartools helpers.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    quarter_label = str(args.quarter).strip().upper()
    tickers = [
        item.strip().upper() for item in str(args.tickers).split(",") if item.strip()
    ]
    start_date = str(args.start_date).strip()
    end_date = str(args.end_date).strip()
    if start_date or end_date:
        if not start_date or not end_date:
            raise SystemExit("--start-date and --end-date must be provided together")
        label = f"{start_date}_{end_date}"
        rows = scan_date_range(
            start_date,
            end_date,
            min_score=int(args.min_score),
            tickers=tickers or None,
            extraction_mode=str(args.extraction_mode),
            label=label,
        )
    else:
        if not quarter_label:
            raise SystemExit("--quarter or --start-date/--end-date is required")
        label = quarter_label.lower()
        rows = scan_quarter(
            quarter_label,
            min_score=int(args.min_score),
            tickers=tickers or None,
            extraction_mode=str(args.extraction_mode),
        )
    output = Path(
        str(args.output).strip()
        or DEFAULT_OUTPUT_TEMPLATE.format(
            label=label, min_score=int(args.min_score)
        )
    )
    write_scan_csv(rows, output)
    print(f"Wrote {output} ({len(rows)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
