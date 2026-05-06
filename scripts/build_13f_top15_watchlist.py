#!/usr/bin/env python3
"""Build locked Top-15 adaptive 13F manager watchlist snapshot."""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

POLICY_PATH = ROOT / "tradingagents" / "backtesting" / "thirteenf" / "watchlist_policy.json"
PROPER_EVENTS = ROOT / "eval_results" / "13f" / "proper_manager_backtest_296" / "backtest" / "13f_events.json"
SITUATIONAL_EVENTS = ROOT / "eval_results" / "13f" / "backtest_situational_awareness" / "13f_events.json"
OUT = ROOT / "eval_results" / "13f" / "proper_manager_backtest_296" / "backtest" / "top15_watchlist_summary.json"


def main() -> None:
    policy = json.loads(POLICY_PATH.read_text())
    proper_events = json.loads(PROPER_EVENTS.read_text())
    special_events = json.loads(SITUATIONAL_EVENTS.read_text())
    by = defaultdict(list)
    for event in proper_events:
        by[event["manager_id"]].append(event)

    min_events = policy["eligibility"]["min_event_count"]
    min_180 = policy["eligibility"]["min_completed_180d_count"]
    ranked = []
    for manager_id, rows in by.items():
        vals = [r.get("excess_return_180d") for r in rows if r.get("excess_return_180d") is not None]
        if len(rows) >= min_events and len(vals) >= min_180:
            ranked.append((sum(vals) / len(vals), manager_id, rows))
    ranked.sort(reverse=True)
    selected_ids = {manager_id for _, manager_id, _ in ranked[: policy["manager_count"]]}
    special_ids = {item["manager_id"] for item in policy.get("special_watchlist", [])}
    selected_events = [e for e in proper_events + special_events if e["manager_id"] in selected_ids | special_ids]
    summary = summarize(selected_events, selected_ids, special_ids, policy)
    OUT.write_text(json.dumps(summary, indent=2))
    print(json.dumps({"out": str(OUT), "standard_manager_count": len(selected_ids), "special_manager_count": len(special_ids), "total_manager_count": summary["manager_count"], "event_count": summary["event_count"]}, indent=2))


def summarize(events: list[dict], selected_ids: set[str], special_ids: set[str], policy: dict) -> dict:
    by = defaultdict(list)
    for event in events:
        by[event["manager_id"]].append(event)
    managers = []
    for manager_id, rows in by.items():
        item = {"manager_id": manager_id, "manager_name": rows[0]["manager_name"], "event_count": len(rows), "special_watchlist": manager_id in special_ids}
        for h in [30, 60, 90, 120, 150, 180]:
            vals = [r.get(f"excess_return_{h}d") for r in rows if r.get(f"excess_return_{h}d") is not None]
            item[f"completed_{h}d_count"] = len(vals)
            item[f"avg_excess_return_{h}d"] = sum(vals) / len(vals) if vals else None
        hold = [r.get("hold_until_exit_excess_return") for r in rows if r.get("hold_until_exit_excess_return") is not None]
        item["hold_until_exit_count"] = len(hold)
        item["avg_hold_until_exit_excess_return"] = sum(hold) / len(hold) if hold else None
        managers.append(item)
    managers.sort(key=lambda m: (not m["special_watchlist"], -(m.get("avg_excess_return_180d") or -999)))
    return {
        "policy": policy,
        "manager_count": len({m["manager_id"] for m in managers}),
        "standard_manager_count": len(selected_ids),
        "special_manager_count": len(special_ids),
        "event_count": len(events),
        "managers": managers,
        "aggregate": aggregate(events),
    }


def aggregate(events: list[dict]) -> dict:
    out = {"horizons": {}}
    for h in [30, 60, 90, 120, 150, 180]:
        vals = [e.get(f"excess_return_{h}d") for e in events if e.get(f"excess_return_{h}d") is not None]
        raw = [e.get(f"forward_return_{h}d") for e in events if e.get(f"forward_return_{h}d") is not None]
        out["horizons"][f"{h}d"] = {"n": len(vals), "avg_raw_return": sum(raw) / len(raw) if raw else None, "avg_excess_return": sum(vals) / len(vals) if vals else None, "hit_rate": sum(v > 0 for v in vals) / len(vals) if vals else None}
    for key in ["hold_until_exit_return", "hold_until_exit_excess_return", "hold_until_exit_cagr", "hold_until_exit_max_drawdown"]:
        vals = [e.get(key) for e in events if e.get(key) is not None]
        out[key] = {"n": len(vals), "avg": sum(vals) / len(vals) if vals else None, "hit_rate_positive": sum(v > 0 for v in vals) / len(vals) if vals else None}
    days = [e.get("hold_duration_days") for e in events if e.get("hold_duration_days") is not None]
    out["hold_duration_days"] = {"n": len(days), "avg": sum(days) / len(days) if days else None}
    return out


if __name__ == "__main__":
    main()
