#!/usr/bin/env python3
"""Seed allocator market snapshot cache with deterministic mixed-liquidity symbols."""

from __future__ import annotations

import argparse
import datetime as dt
import json

from tradingagents.capital_allocator.market_snapshot_seed import seed_market_snapshot_cache
from tradingagents.default_config import DEFAULT_CONFIG


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed allocator market snapshot cache.")
    parser.add_argument(
        "--db-path",
        default=str(DEFAULT_CONFIG.get("operator_gateway_allocator_db_path", "eval_results/control/capital_allocator.db")),
        help="Allocator SQLite DB path.",
    )
    parser.add_argument(
        "--as-of-utc",
        default="",
        help="Snapshot timestamp (ISO-8601 UTC). Defaults to now.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON summary.",
    )
    return parser.parse_args()


def _parse_as_of_utc(raw: str) -> dt.datetime | None:
    value = str(raw or "").strip()
    if not value:
        return None
    parsed = dt.datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def main() -> None:
    args = _parse_args()
    summary = seed_market_snapshot_cache(
        db_path=args.db_path,
        as_of_utc=_parse_as_of_utc(args.as_of_utc),
    )
    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
        return
    print(
        "[snapshot-seed] "
        f"db={summary['db_path']} "
        f"count={summary['seeded_count']} "
        f"mix={summary['liquidity_mix']}"
    )


if __name__ == "__main__":
    main()

