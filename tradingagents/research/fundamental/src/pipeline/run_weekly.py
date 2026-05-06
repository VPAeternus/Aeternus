from __future__ import annotations

import argparse
from pathlib import Path

from src.reporting.weekly_report import write_weekly_reports
from src.storage import read_table


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run weekly live fundamental reports")
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--lake-root", type=Path, default=Path("outputs/live/parquet"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    candidates = read_table(args.lake_root, "candidate_scores").fillna("").to_dict("records")
    monitoring = read_table(args.lake_root, "candidate_monitoring").fillna("").to_dict("records")
    paths = write_weekly_reports(candidates, monitoring, as_of=args.as_of)
    print("wrote " + " ".join(str(path) for path in paths))


if __name__ == "__main__":
    main()
