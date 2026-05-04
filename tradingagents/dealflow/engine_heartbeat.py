"""Engine heartbeat persistence and schedule guard evaluation."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

from tradingagents.default_config import DEFAULT_CONFIG

from .control_io import read_json_locked, write_json_locked


DEFAULT_HEARTBEAT_PATH = Path("eval_results") / "control" / "engine_heartbeat.json"


def heartbeat_path(config: Optional[Dict[str, Any]] = None) -> Path:
    cfg = config or DEFAULT_CONFIG
    configured = str(cfg.get("operator_gateway_heartbeat_path", "")).strip()
    if configured:
        return Path(configured)
    return DEFAULT_HEARTBEAT_PATH


def load_engine_heartbeat(config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return dict(
        read_json_locked(
            heartbeat_path(config),
            default_factory=lambda: {
                "run_state": "UNKNOWN",
                "heartbeat_seq": 0,
                "updated_at_utc": "",
            },
        )
    )


def emit_engine_heartbeat(
    *,
    run_state: str,
    active_run_id: str = "",
    active_run_started_at_utc: str = "",
    next_run_at_utc_actual: str = "",
    queue_run_id_target: str = "",
    config: Optional[Dict[str, Any]] = None,
    now: Optional[dt.datetime] = None,
) -> Dict[str, Any]:
    cfg = config or DEFAULT_CONFIG
    timestamp = _as_utc(now).isoformat()
    current = load_engine_heartbeat(cfg)
    seq = int(current.get("heartbeat_seq", 0) or 0) + 1

    payload = {
        "engine_time_utc": timestamp,
        "run_state": str(run_state or "UNKNOWN").upper(),
        "active_run_id": str(active_run_id or ""),
        "active_run_started_at_utc": str(active_run_started_at_utc or ""),
        "next_run_at_utc_actual": str(next_run_at_utc_actual or ""),
        "queue_run_id_target": str(queue_run_id_target or ""),
        "heartbeat_seq": seq,
        "updated_at_utc": timestamp,
    }
    write_json_locked(heartbeat_path(cfg), payload)
    return payload


def evaluate_schedule_guard(
    *,
    heartbeat: Optional[Dict[str, Any]] = None,
    config: Optional[Dict[str, Any]] = None,
    now: Optional[dt.datetime] = None,
) -> Dict[str, Any]:
    cfg = config or DEFAULT_CONFIG
    hb = dict(heartbeat or load_engine_heartbeat(cfg))
    now_utc = _as_utc(now)

    ttl_seconds = float(cfg.get("operator_gateway_heartbeat_ttl_seconds", 25.0))
    max_clock_offset_seconds = float(cfg.get("operator_gateway_clock_offset_max_seconds", 5.0))
    maturity_seconds = float(cfg.get("operator_gateway_intent_maturity_seconds", 5.0))
    ingress_guard_seconds = float(cfg.get("operator_gateway_ingress_guard_seconds", 2.0))

    out: Dict[str, Any] = {
        "schedule_status": "UNKNOWN",
        "run_state": str(hb.get("run_state", "UNKNOWN") or "UNKNOWN").upper(),
        "active_run_id": str(hb.get("active_run_id") or ""),
        "next_run_at_utc_actual": str(hb.get("next_run_at_utc_actual") or ""),
        "queue_run_id_target": str(hb.get("queue_run_id_target") or ""),
        "heartbeat_seq": int(hb.get("heartbeat_seq", 0) or 0),
        "heartbeat_fresh": False,
        "heartbeat_age_seconds": None,
        "clock_offset_seconds": None,
        "commit_cutoff_at_utc": "",
        "seconds_to_next_run": None,
        "commit_window_open": False,
        "reason": "Heartbeat unavailable.",
    }

    updated_at = _parse_utc(str(hb.get("updated_at_utc") or ""))
    engine_time = _parse_utc(str(hb.get("engine_time_utc") or ""))
    next_run_at = _parse_utc(str(hb.get("next_run_at_utc_actual") or ""))

    if not updated_at or not engine_time:
        return out

    heartbeat_age = (now_utc - updated_at).total_seconds()
    out["heartbeat_age_seconds"] = float(round(heartbeat_age, 3))
    out["heartbeat_fresh"] = heartbeat_age <= ttl_seconds
    if not out["heartbeat_fresh"]:
        out["reason"] = f"Heartbeat stale ({heartbeat_age:.2f}s > {ttl_seconds:.2f}s)."
        return out

    clock_offset = (engine_time - now_utc).total_seconds()
    out["clock_offset_seconds"] = float(round(clock_offset, 3))
    if abs(clock_offset) > max_clock_offset_seconds:
        out["reason"] = (
            "Clock offset too large "
            f"({clock_offset:.2f}s > {max_clock_offset_seconds:.2f}s)."
        )
        return out

    run_state = out["run_state"]
    if run_state == "RUNNING":
        out["schedule_status"] = "RUNNING"
        out["reason"] = "Engine currently running."
        return out

    if not next_run_at:
        out["reason"] = "Missing next_run_at_utc_actual."
        return out

    commit_cutoff = next_run_at - dt.timedelta(
        seconds=(maturity_seconds + ingress_guard_seconds)
    )
    seconds_to_next = (next_run_at - now_utc).total_seconds()
    out["commit_cutoff_at_utc"] = commit_cutoff.isoformat()
    out["seconds_to_next_run"] = float(round(seconds_to_next, 3))
    out["commit_window_open"] = now_utc < commit_cutoff
    out["schedule_status"] = "READY"
    out["reason"] = "Schedule healthy."
    return out


def estimate_next_preopen_run_utc(
    *,
    config: Optional[Dict[str, Any]] = None,
    now: Optional[dt.datetime] = None,
) -> str:
    cfg = config or DEFAULT_CONFIG
    now_utc = _as_utc(now)
    tz_name = str(cfg.get("dealflow_scheduler_timezone", "America/New_York"))
    start_hhmm = str(cfg.get("dealflow_scheduler_preopen_start", "08:00"))
    start_hour, start_minute = _parse_hhmm(start_hhmm)

    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = dt.timezone.utc

    local_now = now_utc.astimezone(tz)
    candidate = local_now.replace(
        hour=start_hour,
        minute=start_minute,
        second=0,
        microsecond=0,
    )
    if local_now >= candidate:
        candidate = candidate + dt.timedelta(days=1)

    while candidate.weekday() >= 5:
        candidate = candidate + dt.timedelta(days=1)

    return candidate.astimezone(dt.timezone.utc).isoformat()


def _as_utc(value: Optional[dt.datetime]) -> dt.datetime:
    if value is None:
        return dt.datetime.now(dt.timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(dt.timezone.utc)


def _parse_utc(raw: str) -> Optional[dt.datetime]:
    value = str(raw or "").strip()
    if not value:
        return None
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def _parse_hhmm(value: str) -> tuple[int, int]:
    raw = str(value or "").strip()
    try:
        parsed = dt.datetime.strptime(raw, "%H:%M")
        return int(parsed.hour), int(parsed.minute)
    except ValueError:
        return 8, 0
