import datetime as dt
from pathlib import Path
from unittest.mock import patch

from tradingagents.dealflow.scheduler import DealFlowScheduler


class _FakePipeline:
    def __init__(self, event_triggered: bool):
        self.event_triggered = event_triggered
        self.run_calls = []

    def evaluate_event_trigger(self, as_of_date: str):
        return {
            "triggered": self.event_triggered,
            "reasons": ["shock"] if self.event_triggered else [],
            "metrics": {"spy_move_pct": 2.2 if self.event_triggered else 0.4},
        }

    def run(self, as_of_date: str, trigger: str, top_k: int):
        self.run_calls.append((as_of_date, trigger, top_k))
        shortlist = {
            "run_id": f"{as_of_date}-090000-{trigger}",
            "date": as_of_date,
            "trigger": trigger,
            "candidates": [],
            "event_reasons": ["shock"] if self.event_triggered else [],
        }
        queue = {
            "run_id": shortlist["run_id"],
            "date": as_of_date,
            "items": [],
            "selected_queue_ids": [],
        }
        return shortlist, queue, [{"symbol": "AAPL"}], self.evaluate_event_trigger(as_of_date)


def test_scheduler_runs_daily_once_in_preopen_window(tmp_path):
    pipeline = _FakePipeline(event_triggered=False)
    scheduler = DealFlowScheduler(
        config={
            "dealflow_top_k": 20,
            "dealflow_scheduler_timezone": "America/New_York",
            "dealflow_scheduler_preopen_start": "08:00",
            "dealflow_scheduler_preopen_end": "09:25",
            "dealflow_event_cooldown_minutes": 90,
        },
        state_path=tmp_path / "scheduler_state.json",
        pipeline=pipeline,
    )

    now = dt.datetime(2026, 2, 6, 13, 30, tzinfo=dt.timezone.utc)  # 08:30 ET
    first = scheduler.run_once(now=now)
    second = scheduler.run_once(now=now + dt.timedelta(minutes=5))

    assert first["ran"] is True
    assert first["trigger"] == "daily"
    assert second["ran"] is False
    assert len(pipeline.run_calls) == 1


def test_scheduler_enforces_event_cooldown(tmp_path):
    pipeline = _FakePipeline(event_triggered=True)
    scheduler = DealFlowScheduler(
        config={
            "dealflow_top_k": 20,
            "dealflow_scheduler_timezone": "America/New_York",
            "dealflow_scheduler_preopen_start": "08:00",
            "dealflow_scheduler_preopen_end": "09:25",
            "dealflow_event_cooldown_minutes": 90,
        },
        state_path=tmp_path / "scheduler_state.json",
        pipeline=pipeline,
    )

    now = dt.datetime(2026, 2, 6, 16, 0, tzinfo=dt.timezone.utc)  # 11:00 ET
    first = scheduler.run_once(now=now)
    second = scheduler.run_once(now=now + dt.timedelta(minutes=30))
    third = scheduler.run_once(now=now + dt.timedelta(minutes=100))

    assert first["ran"] is True and first["trigger"] == "event"
    assert second["ran"] is False
    assert third["ran"] is True and third["trigger"] == "event"
    assert len(pipeline.run_calls) == 2


def test_scheduler_wires_x_budget_policy(tmp_path):
    pipeline = _FakePipeline(event_triggered=False)
    scheduler = DealFlowScheduler(
        config={
            "dealflow_top_k": 20,
            "dealflow_scheduler_timezone": "America/New_York",
            "dealflow_scheduler_preopen_start": "08:00",
            "dealflow_scheduler_preopen_end": "09:25",
            "dealflow_event_cooldown_minutes": 90,
            "dealflow_x_auto_tune_enabled": True,
        },
        state_path=tmp_path / "scheduler_state.json",
        pipeline=pipeline,
    )

    budget_payload = {
        "enabled": True,
        "applied": True,
        "action": "INCREASE",
        "horizon_used": "20d",
        "recommended": {
            "max_api_calls_per_run": 9,
            "daily_budget_usd": 16.0,
        },
    }

    with patch(
        "tradingagents.dealflow.scheduler.evaluate_x_budget_policy", return_value=budget_payload
    ), patch(
        "tradingagents.dealflow.scheduler.persist_x_budget_policy", return_value=Path("eval_results/deal_flow/2026-02-06/x_budget_policy.json")
    ):
        now = dt.datetime(2026, 2, 6, 13, 30, tzinfo=dt.timezone.utc)
        result = scheduler.run_once(now=now)

    assert result["ran"] is True
    assert result["x_budget_policy"]["action"] == "INCREASE"

    state = json_load(scheduler.state_path)
    assert state["last_x_budget_policy"]["action"] == "INCREASE"


def json_load(path: Path):
    import json

    return json.loads(path.read_text())
