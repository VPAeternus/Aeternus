from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import pandas as pd
import yfinance as yf

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from autoresearch.fetch_filing_text import extract_sections
from Growth.venture_mechanical_scorer import (
    FilingPacket,
    _next_trading_day,
    _output_ticker,
    _score_packet,
)

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
    "entry_open",
    "return_20d_pct",
    "return_30d_pct",
    "return_60d_pct",
    "return_90d_pct",
]
HORIZONS = [20, 30, 60, 90]


def fetch_live_packets(ticker: str, start_date: str) -> list[FilingPacket]:
    from edgar import Company, set_identity

    set_identity("AeternusAgentsAG research@aeternus.ai")
    company = Company(ticker)
    packets: list[FilingPacket] = []

    for form in ("10-K", "10-Q"):
        for filing in company.get_filings(form=form):
            filed = str(getattr(filing, "filing_date", "") or "")
            if filed < start_date:
                continue
            accn = str(getattr(filing, "accession_no", "") or "")
            sections = {
                key: value
                for key, value in extract_sections(filing, form).items()
                if value and not key.startswith("_")
            }
            packets.append(
                FilingPacket(
                    ticker=ticker.upper(),
                    filed=filed,
                    form=form,
                    accn=accn,
                    sections=sections,
                    source_mode="live_edgartools",
                )
            )

    return sorted(packets, key=lambda packet: packet.filed)


def add_returns(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    if not rows:
        return rows

    ticker = "LITE" if rows[0]["ticker"] == "LTE" else rows[0]["ticker"]
    start = min(row["tradable_date"] for row in rows)
    end = (pd.Timestamp.now("UTC") + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    history = yf.Ticker(ticker).history(
        start=start,
        end=end,
        interval="1d",
        auto_adjust=False,
    )
    dates = history.index.strftime("%Y-%m-%d")

    for row in rows:
        entry_mask = dates == row["tradable_date"]
        if not entry_mask.any():
            continue
        entry_open = float(history.loc[entry_mask, "Open"].iloc[0])
        row["entry_open"] = f"{entry_open:.6f}"
        for horizon in HORIZONS:
            target = (
                pd.to_datetime(row["tradable_date"]) + pd.Timedelta(days=horizon)
            ).strftime("%Y-%m-%d")
            exits = history[history.index.strftime("%Y-%m-%d") >= target]
            if exits.empty:
                row[f"return_{horizon}d_pct"] = ""
                continue
            exit_close = float(exits.iloc[0]["Close"])
            row[f"return_{horizon}d_pct"] = f"{((exit_close / entry_open) - 1) * 100:.4f}"
    return rows


def score_packets(ticker: str, packets: list[FilingPacket]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    prior: FilingPacket | None = None

    for packet in packets:
        try:
            score = _score_packet(packet, prior)
        except ValueError:
            prior = packet
            continue
        prior = packet
        row = {
            "scan_quarter": "live_sec",
            "ticker": _output_ticker(ticker),
            "filing_date": packet.filed,
            "tradable_date": _next_trading_day(packet.filed),
            "form": packet.form,
        }
        for field in FIELDNAMES:
            if field not in row:
                row[field] = str(score.get(field, ""))
        rows.append(row)

    return add_returns(rows)


def compare_to_csv(
    live_rows: list[dict[str, str]],
    baseline_csv: Path,
    ticker: str,
) -> list[dict[str, str]]:
    if not baseline_csv.exists():
        return []

    baseline_rows = [
        row
        for row in csv.DictReader(baseline_csv.open())
        if row["ticker"] == _output_ticker(ticker)
    ]
    baseline_by_key = {
        (row["ticker"], row["filing_date"], row["form"]): row for row in baseline_rows
    }
    comparisons: list[dict[str, str]] = []

    for live in live_rows:
        key = (live["ticker"], live["filing_date"], live["form"])
        base = baseline_by_key.get(key)
        item = {
            "ticker": live["ticker"],
            "filing_date": live["filing_date"],
            "form": live["form"],
            "baseline_found": "1" if base else "0",
        }
        for field in FIELDNAMES:
            if field in {"scan_quarter", "ticker", "filing_date", "tradable_date", "form"}:
                continue
            item[f"live_{field}"] = live.get(field, "")
            item[f"baseline_{field}"] = base.get(field, "") if base else ""
            item[f"match_{field}"] = (
                "1" if base and live.get(field, "") == base.get(field, "") else "0"
            )
        comparisons.append(item)

    return comparisons


def write_csv(rows: list[dict[str, str]], output: Path, fieldnames: list[str]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--start-date", required=True)
    parser.add_argument(
        "--output",
        default="Growth/live_sec_be_scores.csv",
    )
    parser.add_argument(
        "--compare-output",
        default="Growth/live_sec_be_compare.csv",
    )
    parser.add_argument(
        "--baseline",
        default="Growth/venture_scan_2021-06_2023-06_event_returns.csv",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ticker = str(args.ticker).upper()
    packets = fetch_live_packets(ticker, str(args.start_date))
    rows = score_packets(ticker, packets)
    write_csv(rows, Path(str(args.output)), FIELDNAMES)

    comparisons = compare_to_csv(rows, Path(str(args.baseline)), ticker)
    if comparisons:
        compare_fields = list(comparisons[0].keys())
        write_csv(comparisons, Path(str(args.compare_output)), compare_fields)

    matched = sum(1 for row in comparisons if row.get("baseline_found") == "1")
    score_matches = sum(
        1 for row in comparisons if row.get("match_venture_score") == "1"
    )
    print(f"live_packets={len(packets)}")
    print(f"live_scored_rows={len(rows)}")
    print(f"baseline_matches={matched}")
    print(f"venture_score_matches={score_matches}")
    print(f"wrote={args.output}")
    if comparisons:
        print(f"compare={args.compare_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
