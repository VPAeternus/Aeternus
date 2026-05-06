#!/usr/bin/env python3
"""Discover recent 13F filers, fetch history, and prepare broad manager scan inputs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tradingagents.backtesting.thirteenf.history import build_13f_deltas, fetch_historical_13f_holdings
from tradingagents.backtesting.thirteenf.ingest import read_normalized_holdings
from tradingagents.backtesting.thirteenf.manager_scan import discover_recent_13f_managers, filter_proper_managers, load_manager_quality_rules, manager_aum_summary

DEFAULT_CUSIP_MAP = ROOT / "tradingagents" / "backtesting" / "thirteenf" / "cusip_ticker_seed.json"


def _load_map(path: Path) -> dict[str, str]:
    return {str(k).upper(): str(v).upper() for k, v in json.loads(path.read_text()).items()}


def main() -> None:
    parser = argparse.ArgumentParser(description="Broad 13F manager scan")
    parser.add_argument("--out-dir", type=Path, default=Path("eval_results/13f/manager_scan"))
    parser.add_argument("--cache-dir", type=Path, default=Path("eval_results/13f/cache/sec"))
    parser.add_argument("--quarters", type=int, default=2, help="Recent SEC full-index quarters to scan")
    parser.add_argument("--max-managers", type=int, default=100, help="Safety cap for first broad fetch")
    parser.add_argument("--proper-managers-only", action="store_true", help="Exclude banks/foreign institutions/bulk admin filers by name heuristic")
    parser.add_argument("--manager-quality-rules", type=Path, default=None, help="JSON allow/deny CIK/name rules")
    parser.add_argument("--min-manager-aum-usd", type=float, default=0.0, help="Minimum latest 13F AUM after a probe fetch")
    parser.add_argument("--min-position-count", type=int, default=0, help="Minimum latest 13F position count")
    parser.add_argument("--max-position-count", type=int, default=0, help="Maximum latest 13F position count; excludes bulk/passive warehouses")
    parser.add_argument("--min-top10-concentration", type=float, default=0.0, help="Minimum top-10 concentration; excludes quasi-indexers")
    parser.add_argument("--max-top10-concentration", type=float, default=1.0, help="Maximum top-10 concentration; excludes shell/one-bet filers")
    parser.add_argument("--aum-probe-filings", type=int, default=1, help="Latest filings per manager for AUM filter probe")
    parser.add_argument("--start-report-date", default="2018-01-01")
    parser.add_argument("--min-value-usd", type=float, default=10000000.0)
    parser.add_argument("--cusip-map", type=Path, default=DEFAULT_CUSIP_MAP)
    parser.add_argument("--discover-only", action="store_true")
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    managers = discover_recent_13f_managers(quarters=args.quarters, cache_dir=args.cache_dir)
    discovered_count = len(managers)
    if args.proper_managers_only:
        managers = filter_proper_managers(managers, rules=load_manager_quality_rules(args.manager_quality_rules))
    managers = managers[: args.max_managers]

    pre_aum_seed_path = args.out_dir / "manager_seed_pre_aum.json"
    pre_aum_seed_path.write_text(json.dumps(managers, indent=2))

    aum_summary_path = args.out_dir / "manager_aum_summary.json"
    needs_aum_probe = any([
        args.min_manager_aum_usd > 0,
        args.min_position_count > 0,
        args.max_position_count > 0,
        args.min_top10_concentration > 0,
        args.max_top10_concentration < 1.0,
    ])
    if needs_aum_probe and managers:
        probe_raw_path = args.out_dir / "aum_probe_holdings_raw.csv"
        fetch_historical_13f_holdings(
            manager_seed_path=pre_aum_seed_path,
            out_path=probe_raw_path,
            cusip_ticker_map=_load_map(args.cusip_map),
            max_filings_per_manager=args.aum_probe_filings,
            cache_dir=args.cache_dir,
        )
        aum = manager_aum_summary(read_normalized_holdings(probe_raw_path))
        aum_summary_path.write_text(json.dumps(aum, indent=2))
        filtered = []
        for manager in managers:
            stats = aum.get(str(manager.get("manager_id", "")), {})
            manager_aum = float(stats.get("latest_13f_aum_usd", 0.0) or 0.0)
            position_count = int(stats.get("latest_position_count", 0) or 0)
            top10 = float(stats.get("top10_concentration", 0.0) or 0.0)
            if manager_aum < args.min_manager_aum_usd:
                continue
            if args.min_position_count > 0 and position_count < args.min_position_count:
                continue
            if args.max_position_count > 0 and position_count > args.max_position_count:
                continue
            if top10 < args.min_top10_concentration:
                continue
            if top10 > args.max_top10_concentration:
                continue
            filtered.append(manager)
        managers = filtered

    seed_path = args.out_dir / "manager_seed.json"
    seed_path.write_text(json.dumps(managers, indent=2))

    manifest = {
        "discovered_count": discovered_count,
        "manager_count": len(managers),
        "manager_seed_path": str(seed_path),
        "cache_dir": str(args.cache_dir),
        "quarters": args.quarters,
        "max_managers": args.max_managers,
        "discover_only": bool(args.discover_only),
        "proper_managers_only": bool(args.proper_managers_only),
        "manager_quality_rules": str(args.manager_quality_rules) if args.manager_quality_rules else "default",
        "min_manager_aum_usd": float(args.min_manager_aum_usd),
        "min_position_count": int(args.min_position_count),
        "max_position_count": int(args.max_position_count),
        "min_top10_concentration": float(args.min_top10_concentration),
        "max_top10_concentration": float(args.max_top10_concentration),
        "aum_summary_path": str(aum_summary_path) if aum_summary_path.exists() else "",
    }
    if args.discover_only:
        (args.out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
        print(json.dumps(manifest, indent=2))
        return

    holdings_path = args.out_dir / "holdings_raw.csv"
    delta_path = args.out_dir / "holdings_delta.csv"
    fetch_manifest = fetch_historical_13f_holdings(
        manager_seed_path=seed_path,
        out_path=holdings_path,
        cusip_ticker_map=_load_map(args.cusip_map),
        start_report_date=args.start_report_date,
        cache_dir=args.cache_dir,
    )
    delta_manifest = build_13f_deltas(
        holdings_path=holdings_path,
        out_path=delta_path,
        min_value_usd=args.min_value_usd,
        resolved_only=True,
    )
    manifest.update({"fetch": fetch_manifest, "delta": delta_manifest})
    (args.out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
