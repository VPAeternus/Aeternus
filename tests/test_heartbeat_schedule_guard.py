import datetime as dt
from pathlib import Path

from tradingagents.dealflow.control_io import write_json_locked
from tradingagents.dealflow.engine_heartbeat import evaluate_schedule_guard


def _config(tmp_path: Path) -> dict:
    return {
        "operator_gateway_heartbeat_path": str(tmp_path / "control" / "engine_heartbeat.json"),
        "operator_gateway_heartbeat_ttl_seconds": 25.0,
        "operator_gateway_clock_offset_max_seconds": 5.0,
        "operator_gateway_intent_maturity_seconds": 5.0,
        "operator_gateway_ingress_guard_seconds": 2.0,
    }


def test_schedule_unknown_when_heartbeat_stale(tmp_path: Path):
    config = _config(tmp_path)
    now = dt.datetime(2026, 2, 8, 14, 0, tzinfo=dt.timezone.utc)
    heartbeat = {
        "engine_time_utc": (now - dt.timedelta(seconds=30)).isoformat(),
        "run_state": "IDLE",
        "active_run_id": "",
        "active_run_started_at_utc": "",
        "next_run_at_utc_actual": (now + dt.timedelta(minutes=2)).isoformat(),
        "queue_run_id_target": "run-1",
        "heartbeat_seq": 4,
        "updated_at_utc": (now - dt.timedelta(seconds=30)).isoformat(),
    }
    write_json_locked(Path(config["operator_gateway_heartbeat_path"]), heartbeat)
    guard = evaluate_schedule_guard(config=config, now=now)
    assert guard["schedule_status"] == "UNKNOWN"
    assert guard["heartbeat_fresh"] is False


def test_schedule_unknown_when_clock_drift_exceeds_limit(tmp_path: Path):
    config = _config(tmp_path)
    now = dt.datetime(2026, 2, 8, 14, 0, tzinfo=dt.timezone.utc)
    heartbeat = {
        "engine_time_utc": (now + dt.timedelta(seconds=8)).isoformat(),
        "run_state": "IDLE",
        "active_run_id": "",
        "active_run_started_at_utc": "",
        "next_run_at_utc_actual": (now + dt.timedelta(minutes=2)).isoformat(),
        "queue_run_id_target": "run-1",
        "heartbeat_seq": 4,
        "updated_at_utc": now.isoformat(),
    }
    write_json_locked(Path(config["operator_gateway_heartbeat_path"]), heartbeat)
    guard = evaluate_schedule_guard(config=config, now=now)
    assert guard["schedule_status"] == "UNKNOWN"
    assert abs(float(guard["clock_offset_seconds"])) > 5.0


def test_schedule_ready_and_commit_window_open(tmp_path: Path):
    config = _config(tmp_path)
    now = dt.datetime(2026, 2, 8, 14, 0, tzinfo=dt.timezone.utc)
    heartbeat = {
        "engine_time_utc": now.isoformat(),
        "run_state": "IDLE",
        "active_run_id": "",
        "active_run_started_at_utc": "",
        "next_run_at_utc_actual": (now + dt.timedelta(minutes=2)).isoformat(),
        "queue_run_id_target": "run-1",
        "heartbeat_seq": 4,
        "updated_at_utc": now.isoformat(),
    }
    write_json_locked(Path(config["operator_gateway_heartbeat_path"]), heartbeat)
    guard = evaluate_schedule_guard(config=config, now=now)
    assert guard["schedule_status"] == "READY"
    assert guard["commit_window_open"] is True
    assert guard["seconds_to_next_run"] is not None
