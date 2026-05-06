from __future__ import annotations

import argparse
from pathlib import Path

from autoresearch.filing_comparability import (
    ComparabilityError,
    ensure_comparable_packets,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Auto-repair packet coverage, then fail if filing comparison is still not apples-to-apples."
    )
    parser.add_argument("packet_paths", nargs="+", help="Packet JSON paths to compare")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        coverages = ensure_comparable_packets(Path(path) for path in args.packet_paths)
    except ComparabilityError as exc:
        print(str(exc))
        return 1

    print("Comparable packet coverage confirmed.")
    for item in coverages:
        repaired = " repaired" if item.repaired else ""
        print(
            f"- {item.ticker} {item.filed} {item.form}: {', '.join(item.present_sections)}{repaired}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
