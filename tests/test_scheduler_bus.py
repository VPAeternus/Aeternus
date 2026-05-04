"""Tests for the autonomous agent scheduler backbone.

Coverage:
- AgentBus schema init
- publish + consume roundtrip
- broadcast (to_agent=None) consumed by any agent
- targeted signal only consumed by correct agent
- signals not double-consumed by same agent
- consume with signal_type filter
- recent() returns signals within window
- BaseAutonomousAgent lifecycle signals (AGENT_STARTED, AGENT_COMPLETED, AGENT_FAILED)
- AeternusScheduler.trigger() runs agent and updates status
- AeternusScheduler.pause() + resume() blocks/unblocks execution
- AeternusScheduler.status() returns list of agent dicts
- RiskSentinelAgent skips outside market hours
- RiskSentinelAgent publishes RISK_FLAG when threshold met
"""
from __future__ import annotations
import datetime as dt
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tradingagents.scheduler.agent_bus import AgentBus, AgentSignal, SignalType
from tradingagents.scheduler.base_agent import BaseAutonomousAgent, AgentRunResult
from tradingagents.scheduler.supervisor import AeternusScheduler
from tradingagents.scheduler.agents.risk_sentinel import RiskSentinelAgent, RISK_THRESHOLD_SCORE


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_bus(tmp_path: Path) -> AgentBus:
    return AgentBus(db_path=tmp_path / "test_bus.db")


def _make_signal(signal_type=SignalType.QUEUE_ITEM_ADDED, from_agent="Scout",
                 to_agent=None, payload=None) -> AgentSignal:
    return AgentSignal(
        signal_type=signal_type,
        from_agent=from_agent,
        to_agent=to_agent,
        payload=payload or {},
    )


class _EchoAgent(BaseAutonomousAgent):
    """Minimal test agent that always succeeds."""
    name = "EchoAgent"

    def run_cycle(self) -> AgentRunResult:
        now = dt.datetime.utcnow().isoformat()
        return AgentRunResult(
            agent_name=self.name,
            success=True,
            started_at=now,
            completed_at=now,
            summary="echo ok",
        )


class _FailingAgent(BaseAutonomousAgent):
    """Test agent that always raises."""
    name = "FailingAgent"

    def run_cycle(self) -> AgentRunResult:
        raise RuntimeError("deliberate failure")


# ---------------------------------------------------------------------------
# 1. AgentBus schema init
# ---------------------------------------------------------------------------

def test_bus_schema_init(tmp_path):
    bus = _make_bus(tmp_path)
    db = tmp_path / "test_bus.db"
    assert db.exists()
    conn = sqlite3.connect(str(db))
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    conn.close()
    assert "agent_signals" in tables


# ---------------------------------------------------------------------------
# 2. publish + consume roundtrip
# ---------------------------------------------------------------------------

def test_publish_consume_roundtrip(tmp_path):
    bus = _make_bus(tmp_path)
    sig = _make_signal(to_agent="ResearchAgent", payload={"ticker": "AAPL"})
    bus.publish(sig)

    consumed = bus.consume("ResearchAgent")
    assert len(consumed) == 1
    assert consumed[0].signal_id == sig.signal_id
    assert consumed[0].payload["ticker"] == "AAPL"
    assert consumed[0].processed_at is not None


# ---------------------------------------------------------------------------
# 3. broadcast consumed by any agent
# ---------------------------------------------------------------------------

def test_broadcast_consumed_by_any_agent(tmp_path):
    bus = _make_bus(tmp_path)
    sig = _make_signal(signal_type=SignalType.RISK_FLAG, to_agent=None)
    bus.publish(sig)

    results_a = bus.consume("AgentA")
    results_b = bus.consume("AgentB")

    # Broadcast: first consumer gets it, second does not (mark-as-processed)
    total = len(results_a) + len(results_b)
    assert total == 1
    assert results_a[0].signal_id == sig.signal_id or results_b[0].signal_id == sig.signal_id


# ---------------------------------------------------------------------------
# 4. targeted signal only consumed by correct agent
# ---------------------------------------------------------------------------

def test_targeted_signal_not_consumed_by_wrong_agent(tmp_path):
    bus = _make_bus(tmp_path)
    sig = _make_signal(to_agent="TargetAgent")
    bus.publish(sig)

    wrong = bus.consume("WrongAgent")
    assert wrong == []

    correct = bus.consume("TargetAgent")
    assert len(correct) == 1


# ---------------------------------------------------------------------------
# 5. signals not double-consumed by same agent
# ---------------------------------------------------------------------------

def test_no_double_consume(tmp_path):
    bus = _make_bus(tmp_path)
    sig = _make_signal(to_agent="AgentX")
    bus.publish(sig)

    first = bus.consume("AgentX")
    second = bus.consume("AgentX")

    assert len(first) == 1
    assert second == []


# ---------------------------------------------------------------------------
# 6. consume with signal_type filter
# ---------------------------------------------------------------------------

def test_consume_signal_type_filter(tmp_path):
    bus = _make_bus(tmp_path)
    bus.publish(_make_signal(signal_type=SignalType.QUEUE_ITEM_ADDED, to_agent="AgentY"))
    bus.publish(_make_signal(signal_type=SignalType.RISK_FLAG, to_agent="AgentY"))

    # Only consume RISK_FLAG
    results = bus.consume("AgentY", signal_types=[SignalType.RISK_FLAG])
    assert len(results) == 1
    assert results[0].signal_type == SignalType.RISK_FLAG

    # The QUEUE_ITEM_ADDED is still pending
    remaining = bus.consume("AgentY")
    assert len(remaining) == 1
    assert remaining[0].signal_type == SignalType.QUEUE_ITEM_ADDED


# ---------------------------------------------------------------------------
# 7. recent() returns signals within window
# ---------------------------------------------------------------------------

def test_recent_returns_signals_within_window(tmp_path):
    bus = _make_bus(tmp_path)
    sig = _make_signal()
    bus.publish(sig)

    recent = bus.recent(hours=1)
    assert any(s.signal_id == sig.signal_id for s in recent)


def test_recent_excludes_old_signals(tmp_path):
    bus = _make_bus(tmp_path)
    # Manually insert an old signal
    old_ts = (dt.datetime.utcnow() - dt.timedelta(hours=48)).isoformat()
    import uuid
    conn = sqlite3.connect(str(tmp_path / "test_bus.db"))
    conn.execute(
        "INSERT INTO agent_signals (signal_id, signal_type, from_agent, payload, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), "RISK_FLAG", "old_agent", "{}", old_ts),
    )
    conn.commit()
    conn.close()

    recent = bus.recent(hours=1)
    assert all(s.created_at > old_ts for s in recent)


# ---------------------------------------------------------------------------
# 8. BaseAutonomousAgent lifecycle signals
# ---------------------------------------------------------------------------

def test_lifecycle_signals_on_success(tmp_path):
    bus = _make_bus(tmp_path)
    agent = _EchoAgent(bus)
    result = agent.execute()

    assert result.success is True
    signals = bus.recent(hours=1)
    types = {s.signal_type for s in signals if s.from_agent == "EchoAgent"}
    assert SignalType.AGENT_STARTED in types
    assert SignalType.AGENT_COMPLETED in types
    assert SignalType.AGENT_FAILED not in types


def test_lifecycle_signals_on_failure(tmp_path):
    bus = _make_bus(tmp_path)
    agent = _FailingAgent(bus)
    result = agent.execute()

    assert result.success is False
    assert "deliberate failure" in result.error

    signals = bus.recent(hours=1)
    types = {s.signal_type for s in signals if s.from_agent == "FailingAgent"}
    assert SignalType.AGENT_STARTED in types
    assert SignalType.AGENT_FAILED in types
    assert SignalType.AGENT_COMPLETED not in types


# ---------------------------------------------------------------------------
# 9. AeternusScheduler.trigger() runs agent and updates status
# ---------------------------------------------------------------------------

def test_scheduler_trigger_runs_agent(tmp_path):
    bus = _make_bus(tmp_path)
    scheduler = AeternusScheduler(bus)
    agent = _EchoAgent(bus)
    scheduler.register(agent)  # no schedule — manual trigger only

    result = scheduler.trigger("EchoAgent")
    assert result.success is True

    statuses = scheduler.status()
    echo_status = next(s for s in statuses if s["name"] == "EchoAgent")
    assert echo_status["last_success"] is True
    assert echo_status["last_run_at"] is not None


def test_scheduler_trigger_unknown_agent_raises(tmp_path):
    bus = _make_bus(tmp_path)
    scheduler = AeternusScheduler(bus)
    with pytest.raises(ValueError, match="Unknown agent"):
        scheduler.trigger("NonExistentAgent")


# ---------------------------------------------------------------------------
# 10. AeternusScheduler.pause() + resume()
# ---------------------------------------------------------------------------

def test_scheduler_pause_blocks_execution(tmp_path):
    bus = _make_bus(tmp_path)
    scheduler = AeternusScheduler(bus)
    agent = _EchoAgent(bus)
    scheduler.register(agent)

    scheduler.pause("EchoAgent")
    # _run_agent is the internal method used by APScheduler; call it directly
    scheduler._run_agent("EchoAgent")

    # Status should show last_run_at as None since cycle was skipped
    statuses = scheduler.status()
    echo_status = next(s for s in statuses if s["name"] == "EchoAgent")
    assert echo_status["last_run_at"] is None


def test_scheduler_resume_unblocks_execution(tmp_path):
    bus = _make_bus(tmp_path)
    scheduler = AeternusScheduler(bus)
    agent = _EchoAgent(bus)
    scheduler.register(agent)

    scheduler.pause("EchoAgent")
    scheduler.resume("EchoAgent")
    scheduler._run_agent("EchoAgent")

    statuses = scheduler.status()
    echo_status = next(s for s in statuses if s["name"] == "EchoAgent")
    assert echo_status["last_run_at"] is not None


# ---------------------------------------------------------------------------
# 11. AeternusScheduler.status() returns list of agent dicts
# ---------------------------------------------------------------------------

def test_scheduler_status_returns_agent_list(tmp_path):
    bus = _make_bus(tmp_path)
    scheduler = AeternusScheduler(bus)
    scheduler.register(_EchoAgent(bus))
    scheduler.register(_FailingAgent(bus))

    statuses = scheduler.status()
    assert len(statuses) == 2
    names = {s["name"] for s in statuses}
    assert "EchoAgent" in names
    assert "FailingAgent" in names
    for s in statuses:
        assert "enabled" in s
        assert "last_run_at" in s
        assert "last_success" in s
        assert "next_run_at" in s


# ---------------------------------------------------------------------------
# 12. RiskSentinelAgent skips outside market hours
# ---------------------------------------------------------------------------

def test_risk_sentinel_skips_outside_market_hours(tmp_path):
    bus = _make_bus(tmp_path)
    agent = RiskSentinelAgent(bus)

    # Force non-market time: Saturday midnight UTC (well outside ET hours)
    saturday_midnight_utc = dt.datetime(2026, 2, 21, 0, 0, 0)  # Saturday
    with patch("tradingagents.scheduler.agents.risk_sentinel.dt") as mock_dt:
        mock_dt.datetime.utcnow.return_value = saturday_midnight_utc
        mock_dt.timedelta = dt.timedelta
        mock_dt.time = dt.time
        mock_dt.date = dt.date

        result = agent.run_cycle()

    assert result.success is True
    assert "skipped" in result.summary.lower()
    assert result.signals_published == 0


# ---------------------------------------------------------------------------
# 13. RiskSentinelAgent publishes RISK_FLAG when threshold met
# ---------------------------------------------------------------------------

def test_risk_sentinel_publishes_flag_when_threshold_met(tmp_path):
    bus = _make_bus(tmp_path)
    agent = RiskSentinelAgent(bus)

    # Force market hours: Tuesday 14:00 UTC = 09:00 ET (within market hours)
    tuesday_market = dt.datetime(2026, 2, 24, 14, 30, 0)  # Tuesday 9:30 ET

    # Build headlines that contain enough keywords to exceed the threshold
    heavy_headlines = [
        "trump executive order on tariff raises concerns",
        "federal reserve rate hike signals recession fears",
        "nvidia semiconductor chip ban fomc reaction",
    ]

    with patch("tradingagents.scheduler.agents.risk_sentinel.dt") as mock_dt:
        mock_dt.datetime.utcnow.return_value = tuesday_market
        mock_dt.timedelta = dt.timedelta
        mock_dt.time = dt.time
        mock_dt.date = dt.date

        with patch.object(agent, "_fetch_recent_headlines", return_value=heavy_headlines):
            result = agent.run_cycle()

    assert result.success is True
    assert "FLAGGED" in result.summary
    assert result.signals_published == 1

    # Verify the signal was actually published to the bus
    signals = bus.recent(hours=1)
    risk_signals = [s for s in signals if s.signal_type == SignalType.RISK_FLAG]
    assert len(risk_signals) == 1
    assert risk_signals[0].payload["score"] >= RISK_THRESHOLD_SCORE


def test_risk_sentinel_no_flag_below_threshold(tmp_path):
    bus = _make_bus(tmp_path)
    agent = RiskSentinelAgent(bus)

    tuesday_market = dt.datetime(2026, 2, 24, 14, 30, 0)

    # Single benign headline — keyword score will be < RISK_THRESHOLD_SCORE
    benign_headlines = ["Markets open flat, earnings season continues"]

    with patch("tradingagents.scheduler.agents.risk_sentinel.dt") as mock_dt:
        mock_dt.datetime.utcnow.return_value = tuesday_market
        mock_dt.timedelta = dt.timedelta
        mock_dt.time = dt.time
        mock_dt.date = dt.date

        with patch.object(agent, "_fetch_recent_headlines", return_value=benign_headlines):
            result = agent.run_cycle()

    assert result.success is True
    assert "clear" in result.summary
    assert result.signals_published == 0

    signals = bus.recent(hours=1)
    risk_signals = [s for s in signals if s.signal_type == SignalType.RISK_FLAG]
    assert len(risk_signals) == 0


# ---------------------------------------------------------------------------
# 14. New SignalType enum values
# ---------------------------------------------------------------------------

def test_plan_ready_signal_type_exists():
    assert SignalType.PLAN_READY == "PLAN_READY"


def test_execution_complete_signal_type_exists():
    assert SignalType.EXECUTION_COMPLETE == "EXECUTION_COMPLETE"


# ---------------------------------------------------------------------------
# 15. PortfolioAgent idle cycle (no signals → success)
# ---------------------------------------------------------------------------

def test_portfolio_agent_idle_cycle(tmp_path):
    from tradingagents.scheduler.agents.portfolio_agent import PortfolioAgent

    bus = _make_bus(tmp_path)
    agent = PortfolioAgent(bus)
    result = agent.run_cycle()

    assert result.success is True
    assert "idle" in result.summary.lower()
    assert result.signals_published == 0


# ---------------------------------------------------------------------------
# 16. ExecutionAgent idle cycle (no signals → success)
# ---------------------------------------------------------------------------

def test_execution_agent_idle_cycle(tmp_path):
    from tradingagents.scheduler.agents.execution_agent import ExecutionAgent

    bus = _make_bus(tmp_path)
    agent = ExecutionAgent(bus)
    result = agent.run_cycle()

    assert result.success is True
    assert "idle" in result.summary.lower()
    assert result.signals_published == 0
