#!/usr/bin/env python3
"""Inject manual allocator regime override for Alpha test shock drills."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tradingagents.capital_allocator.contracts import RegimeShock
from tradingagents.capital_allocator.regime_override import write_regime_override


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inject allocator regime override.")
    parser.add_argument(
        "--override-path",
        default="eval_results/control/allocator_regime_override.json",
        help="Override artifact path.",
    )
    parser.add_argument(
        "--regime",
        default=RegimeShock.CRISIS.value,
        choices=[value.value for value in RegimeShock],
        help="Target regime override value.",
    )
    parser.add_argument("--reason", default="alpha_protocol_day3_shock", help="Reason for override.")
    parser.add_argument("--source", default="operator", help="Override source label.")
    parser.add_argument("--json", action="store_true", help="Emit JSON payload.")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    payload = write_regime_override(
        path=Path(args.override_path),
        regime=RegimeShock(str(args.regime).upper()),
        reason=args.reason,
        source=args.source,
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    print(
        "[regime-override] "
        f"path={args.override_path} "
        f"regime={payload['regime']} "
        f"source={payload['source']}"
    )


if __name__ == "__main__":
    main()

