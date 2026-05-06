#!/usr/bin/env python3
"""Run PIT 13F delta backtest from normalized holdings rows."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tradingagents.backtesting.thirteenf.core import build_13f_backtest_events, score_manager_quality
from tradingagents.backtesting.thirteenf.ingest import load_manager_seed, read_normalized_holdings


def _load_prices(path: Path) -> pd.DataFrame:
    if path.suffix == ".parquet":
        frame = pd.read_parquet(path)
    else:
        frame = pd.read_csv(path)
    if "date" in frame.columns:
        frame["date"] = pd.to_datetime(frame["date"])
        frame = frame.set_index("date")
    return frame.sort_index()


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest normalized 13F delta events")
    parser.add_argument("--holdings", type=Path, required=True, help="Normalized 13F holdings CSV/parquet")
    parser.add_argument("--prices", type=Path, required=True, help="Wide close-price CSV/parquet with date index/column")
    parser.add_argument("--out-dir", type=Path, default=Path("eval_results/13f/backtest"))
    parser.add_argument("--benchmark", default="SPY")
    parser.add_argument("--actions", default="new", help="Comma-separated actions to backtest: new,add")
    parser.add_argument("--include-initial-observations", action="store_true", help="Include first observed manager/security rows")
    parser.add_argument("--manager-seed", type=Path, default=None, help="Optional manager seed JSON copied into manifest")
    args = parser.parse_args()

    holdings = read_normalized_holdings(args.holdings)
    prices = _load_prices(args.prices)
    actions = {part.strip() for part in str(args.actions).split(",") if part.strip()}
    events = build_13f_backtest_events(
        holdings,
        prices,
        benchmark=args.benchmark,
        actions=actions,
        exclude_initial_observations=not bool(args.include_initial_observations),
    )
    managers = score_manager_quality(events)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    events_path = args.out_dir / "13f_events.json"
    managers_path = args.out_dir / "manager_quality.json"
    manifest_path = args.out_dir / "manifest.json"
    events_path.write_text(json.dumps(events, indent=2, default=str))
    managers_path.write_text(json.dumps(managers, indent=2, default=str))
    manifest = {
        "holdings": str(args.holdings),
        "prices": str(args.prices),
        "benchmark": args.benchmark,
        "event_count": len(events),
        "manager_count": len(managers),
        "events_path": str(events_path),
        "manager_quality_path": str(managers_path),
        "manager_seed": load_manager_seed(args.manager_seed) if args.manager_seed else [],
        "pit_contract": "Entry is next trading day after public filing_date; exits wait for later public 13F exit/reduction.",
        "actions": sorted(actions),
        "include_initial_observations": bool(args.include_initial_observations),
        "horizons": [30, 60, 90, 120, 150, 180, "hold_until_exit"],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, default=str))
    print(json.dumps(manifest, indent=2, default=str))


if __name__ == "__main__":
    main()
