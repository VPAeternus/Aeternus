#!/usr/bin/env python3
"""Create approved/review/rejected 13F manager stage from a scan output."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tradingagents.backtesting.thirteenf.manager_classifier import classify_managers
from tradingagents.backtesting.thirteenf.manager_scan import load_manager_quality_rules


def main() -> None:
    parser = argparse.ArgumentParser(description="Classify scanned 13F managers into approved/review/rejected")
    parser.add_argument("--scan-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--manager-quality-rules", type=Path, default=None)
    args = parser.parse_args()

    out_dir = args.out_dir or (args.scan_dir / "proper_manager_stage")
    out_dir.mkdir(parents=True, exist_ok=True)
    managers = json.loads((args.scan_dir / "manager_seed_pre_aum.json").read_text())
    aum = json.loads((args.scan_dir / "manager_aum_summary.json").read_text())
    rows = classify_managers(managers, aum, rules=load_manager_quality_rules(args.manager_quality_rules))

    approved = [r for r in rows if r["status"] == "approved"]
    review = [r for r in rows if r["status"] == "review"]
    rejected = [r for r in rows if r["status"] == "rejected"]

    (out_dir / "manager_classification.json").write_text(json.dumps(rows, indent=2))
    (out_dir / "approved_manager_seed.json").write_text(json.dumps([
        {
            "manager_id": r["manager_id"],
            "manager_name": r["manager_name"],
            "manager_cik": r["manager_cik"],
            "style": "proper_manager_scan",
            "proper_manager_score": r["proper_manager_score"],
        }
        for r in approved
    ], indent=2))
    _write_csv(out_dir / "review_queue.csv", review)
    _write_csv(out_dir / "rejected.csv", rejected)

    manifest = {
        "input_scan_dir": str(args.scan_dir),
        "approved_count": len(approved),
        "review_count": len(review),
        "rejected_count": len(rejected),
        "approved_seed_path": str(out_dir / "approved_manager_seed.json"),
        "review_queue_path": str(out_dir / "review_queue.csv"),
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest, indent=2))


def _write_csv(path: Path, rows: list[dict]) -> None:
    fields = ["manager_name", "manager_cik", "status", "proper_manager_score", "latest_13f_aum_usd", "latest_position_count", "top10_concentration", "reasons", "rejects"]
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: (";".join(row[k]) if isinstance(row.get(k), list) else row.get(k, "")) for k in fields})


if __name__ == "__main__":
    main()
