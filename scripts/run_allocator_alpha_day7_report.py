#!/usr/bin/env python3
"""Build Day-7 alpha protocol report card from allocator SQLite ledger."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tradingagents.capital_allocator.reporting import build_allocator_report_card
from tradingagents.capital_allocator.repository import SQLiteAllocatorRepository


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build allocator Day-7 report card.")
    parser.add_argument(
        "--db-path",
        default="eval_results/control/capital_allocator.db",
        help="Allocator SQLite database path.",
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=7,
        help="Lookback window in days (default: 7).",
    )
    parser.add_argument(
        "--output",
        default="eval_results/control/capital_allocator_alpha_day7_report.json",
        help="Report output path.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON to stdout.")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    db_path = Path(args.db_path)
    repo = SQLiteAllocatorRepository(db_path)
    repo.initialize()
    report = build_allocator_report_card(
        repo=repo,
        lookback_days=max(1, int(args.lookback_days)),
    )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True))

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return

    print(
        "[alpha-day7] "
        f"total={report['total_intents']} "
        f"validated_rate={report['validation_rate_pct']:.2f}% "
        f"veto_rate={report['veto_rate_pct']:.2f}% "
        f"pending_funding={report['pending_funding_count']} "
        f"output={output_path}"
    )


if __name__ == "__main__":
    main()
