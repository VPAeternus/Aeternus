#!/usr/bin/env python3
"""Build 13F watchlist basket from ranked managers plus special managers."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    parser = argparse.ArgumentParser(description="Build 13F top manager watchlist basket")
    parser.add_argument("--proper-events", type=Path, default=Path("eval_results/13f/proper_manager_backtest_296/backtest/13f_events.json"))
    parser.add_argument("--situational-events", type=Path, default=Path("eval_results/13f/backtest_situational_awareness/13f_events.json"))
    parser.add_argument("--top-summary", type=Path, default=Path("eval_results/13f/proper_manager_backtest_296/backtest/top10_by_180d_summary.json"))
    parser.add_argument("--out", type=Path, default=Path("eval_results/13f/proper_manager_backtest_296/backtest/top11_watchlist_summary.json"))
    args = parser.parse_args()

    proper_events = json.loads(args.proper_events.read_text())
    special_events = json.loads(args.situational_events.read_text())
    top = json.loads(args.top_summary.read_text())
    top_ids = [m["manager_id"] for m in top["top10_managers"]]
    ids = set(top_ids) | {"situational_awareness"}
    selected = [e for e in proper_events + special_events if e["manager_id"] in ids]
    summary = summarize(selected, ids)
    summary["basket_name"] = "top11_watchlist"
    summary["construction"] = "Original statistically filtered top 10 by 180d excess plus Situational Awareness as limited-history special watchlist manager."
    summary["special_sample_warning"] = "Situational Awareness ranks #1 by 180d excess but has only 8 completed 180d events, below original >=15 threshold."
    args.out.write_text(json.dumps(summary, indent=2))
    print(json.dumps({"out": str(args.out), "manager_count": summary["manager_count"], "event_count": summary["event_count"], "excess_180d": summary["aggregate"]["horizons"]["180d"]["avg_excess_return"]}, indent=2))


def summarize(events: list[dict], ids: set[str]) -> dict:
    by = defaultdict(list)
    for event in events:
        by[event["manager_id"]].append(event)
    managers = []
    for mid, rows in sorted(by.items(), key=lambda kv: _manager_sort_key(kv[1])):
        item = {"manager_id": mid, "manager_name": rows[0]["manager_name"], "event_count": len(rows)}
        for h in [30, 60, 90, 120, 150, 180]:
            vals = [r.get(f"excess_return_{h}d") for r in rows if r.get(f"excess_return_{h}d") is not None]
            item[f"completed_{h}d_count"] = len(vals)
            item[f"avg_excess_return_{h}d"] = sum(vals) / len(vals) if vals else None
        hold = [r.get("hold_until_exit_excess_return") for r in rows if r.get("hold_until_exit_excess_return") is not None]
        item["hold_until_exit_count"] = len(hold)
        item["avg_hold_until_exit_excess_return"] = sum(hold) / len(hold) if hold else None
        item["limited_history"] = bool(mid == "situational_awareness")
        managers.append(item)
    return {
        "manager_count": len(ids),
        "event_count": len(events),
        "managers": managers,
        "aggregate": aggregate(events),
    }


def aggregate(events: list[dict]) -> dict:
    out = {"horizons": {}}
    for h in [30, 60, 90, 120, 150, 180]:
        vals = [e.get(f"excess_return_{h}d") for e in events if e.get(f"excess_return_{h}d") is not None]
        raw = [e.get(f"forward_return_{h}d") for e in events if e.get(f"forward_return_{h}d") is not None]
        out["horizons"][f"{h}d"] = {
            "n": len(vals),
            "avg_raw_return": sum(raw) / len(raw) if raw else None,
            "avg_excess_return": sum(vals) / len(vals) if vals else None,
            "hit_rate": sum(v > 0 for v in vals) / len(vals) if vals else None,
        }
    for key in ["hold_until_exit_return", "hold_until_exit_excess_return", "hold_until_exit_cagr", "hold_until_exit_max_drawdown"]:
        vals = [e.get(key) for e in events if e.get(key) is not None]
        out[key] = {"n": len(vals), "avg": sum(vals) / len(vals) if vals else None, "hit_rate_positive": sum(v > 0 for v in vals) / len(vals) if vals else None}
    days = [e.get("hold_duration_days") for e in events if e.get("hold_duration_days") is not None]
    out["hold_duration_days"] = {"n": len(days), "avg": sum(days) / len(days) if days else None}
    return out


def _manager_sort_key(rows: list[dict]) -> tuple[int, float]:
    vals = [r.get("excess_return_180d") for r in rows if r.get("excess_return_180d") is not None]
    return (0 if rows[0]["manager_id"] == "situational_awareness" else 1, -(sum(vals) / len(vals) if vals else -999))


if __name__ == "__main__":
    main()
