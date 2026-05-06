#!/usr/bin/env python3
"""Fetch historical 13F holdings and build QoQ deltas."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tradingagents.backtesting.thirteenf.history import build_13f_deltas, fetch_historical_13f_holdings

DEFAULT_CUSIP_MAP = ROOT / "tradingagents" / "backtesting" / "thirteenf" / "cusip_ticker_seed.json"


def _load_map(path: Path | None) -> dict[str, str]:
    if not path:
        return {}
    payload = json.loads(path.read_text())
    return {str(k).upper(): str(v).upper() for k, v in dict(payload).items()}


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch historical 13F holdings and build deltas")
    parser.add_argument("--manager-seed", type=Path, default=None)
    parser.add_argument("--cusip-map", type=Path, default=DEFAULT_CUSIP_MAP, help="JSON map of CUSIP to ticker")
    parser.add_argument("--out-dir", type=Path, default=Path("eval_results/13f/history"))
    parser.add_argument("--start-report-date", default="")
    parser.add_argument("--end-report-date", default="")
    parser.add_argument("--max-filings-per-manager", type=int, default=0)
    parser.add_argument("--min-value-usd", type=float, default=0.0)
    parser.add_argument("--include-unresolved", action="store_true")
    parser.add_argument("--cache-dir", type=Path, default=Path("eval_results/13f/cache/sec"), help="SEC raw filing cache directory")
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    holdings_path = args.out_dir / "holdings_raw.csv"
    delta_path = args.out_dir / "holdings_delta.csv"
    fetch_manifest = fetch_historical_13f_holdings(
        manager_seed_path=args.manager_seed,
        out_path=holdings_path,
        cusip_ticker_map=_load_map(args.cusip_map),
        start_report_date=args.start_report_date,
        end_report_date=args.end_report_date,
        max_filings_per_manager=args.max_filings_per_manager,
        cache_dir=args.cache_dir,
    )
    delta_manifest = build_13f_deltas(
        holdings_path=holdings_path,
        out_path=delta_path,
        min_value_usd=args.min_value_usd,
        resolved_only=not bool(args.include_unresolved),
    )
    manifest = {"fetch": fetch_manifest, "delta": delta_manifest}
    (args.out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
