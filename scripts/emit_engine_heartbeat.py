#!/usr/bin/env python3
"""Emit engine heartbeat artifacts for local/dev gateway validation."""

from __future__ import annotations

import argparse
import datetime as dt
import time

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.dealflow.engine_heartbeat import emit_engine_heartbeat, estimate_next_preopen_run_utc


def main() -> None:
    parser = argparse.ArgumentParser(description="Emit engine heartbeat JSON artifacts.")
    parser.add_argument("--interval-seconds", type=int, default=10, help="Emit interval.")
    parser.add_argument("--run-state", default="IDLE", help="RUNNING|IDLE|UNKNOWN")
    parser.add_argument("--active-run-id", default="", help="Current run ID when RUNNING.")
    parser.add_argument("--queue-run-id-target", default="", help="Current queue run target for triage.")
    parser.add_argument("--next-run-at-utc", default="", help="Explicit next run UTC ISO timestamp.")
    parser.add_argument("--once", action="store_true", help="Emit one heartbeat then exit.")
    args = parser.parse_args()

    interval = max(1, int(args.interval_seconds))
    while True:
        now = dt.datetime.now(dt.timezone.utc)
        next_run_at = str(args.next_run_at_utc or "").strip() or estimate_next_preopen_run_utc(
            config=DEFAULT_CONFIG,
            now=now,
        )
        payload = emit_engine_heartbeat(
            run_state=str(args.run_state or "IDLE").upper(),
            active_run_id=str(args.active_run_id or ""),
            active_run_started_at_utc=now.isoformat() if str(args.run_state or "").upper() == "RUNNING" else "",
            next_run_at_utc_actual=next_run_at,
            queue_run_id_target=str(args.queue_run_id_target or ""),
            config=DEFAULT_CONFIG,
            now=now,
        )
        print(f"[heartbeat] seq={payload.get('heartbeat_seq')} run_state={payload.get('run_state')} next={payload.get('next_run_at_utc_actual')}")
        if args.once:
            return
        time.sleep(interval)


if __name__ == "__main__":
    main()
