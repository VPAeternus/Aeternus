"""Tests for ContentDistillerAgent and content_queue AgentBus methods.

Coverage:
1. CONTENT_READY signal type exists in enum
2. queue_content() inserts a row, get_pending_content() returns it
3. approve_content() sets status='approved'
4. reject_content() sets status='rejected'
5. mark_published() sets status='published' and sets published_at
6. ContentDistillerAgent idle cycle (no signals -> success, summary contains "idle")
7. ContentDistillerAgent with ANALYSIS_COMPLETE but no results dir -> completes without error
8. ContentDistillerAgent with ANALYSIS_COMPLETE + mock decision file -> queues content
"""
from __future__ import annotations
import json
import datetime as dt
from pathlib import Path

import pytest

from tradingagents.scheduler.agent_bus import AgentBus, AgentSignal, SignalType
from tradingagents.scheduler.agents.content_distiller import ContentDistillerAgent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_bus(tmp_path: Path) -> AgentBus:
    return AgentBus(db_path=tmp_path / "test_bus.db")


def _publish_analysis_complete(bus: AgentBus, trade_date: str) -> None:
    bus.publish(AgentSignal(
        signal_type=SignalType.ANALYSIS_COMPLETE,
        from_agent="ResearchAgent",
        to_agent=None,  # broadcast
        payload={"trade_date": trade_date, "signals_consumed": 1},
    ))


# ---------------------------------------------------------------------------
# 1. CONTENT_READY signal type exists in enum
# ---------------------------------------------------------------------------

def test_content_ready_signal_type_exists():
    assert SignalType.CONTENT_READY == "CONTENT_READY"
    assert SignalType.CONTENT_READY in list(SignalType)


# ---------------------------------------------------------------------------
# 2. queue_content() + get_pending_content() roundtrip
# ---------------------------------------------------------------------------

def test_queue_content_and_get_pending(tmp_path):
    bus = _make_bus(tmp_path)
    row_id = bus.queue_content(
        trade_date="2026-02-24",
        ticker="AAPL",
        content_type="short_post",
        content="AAPL: initiating long. Piotroski F-Score of 8 and accelerating revenue growth tipped the balance.",
    )
    assert isinstance(row_id, int)
    assert row_id > 0

    items = bus.get_pending_content(limit=10)
    assert len(items) == 1
    item = items[0]
    assert item["id"] == row_id
    assert item["ticker"] == "AAPL"
    assert item["trade_date"] == "2026-02-24"
    assert item["content_type"] == "short_post"
    assert item["status"] == "pending"
    assert item["platform"] == "all"
    assert item["published_at"] is None


def test_queue_content_custom_platform(tmp_path):
    bus = _make_bus(tmp_path)
    bus.queue_content("2026-02-24", "MSFT", "thread", "Thread content here.", platform="twitter")
    items = bus.get_pending_content()
    assert items[0]["platform"] == "twitter"


# ---------------------------------------------------------------------------
# 3. approve_content() sets status='approved'
# ---------------------------------------------------------------------------

def test_approve_content(tmp_path):
    bus = _make_bus(tmp_path)
    row_id = bus.queue_content("2026-02-24", "NVDA", "short_post", "NVDA short post.")
    bus.approve_content(row_id)

    # Should no longer appear as pending
    pending = bus.get_pending_content(status="pending")
    assert len(pending) == 0

    approved = bus.get_pending_content(status="approved")
    assert len(approved) == 1
    assert approved[0]["status"] == "approved"


# ---------------------------------------------------------------------------
# 4. reject_content() sets status='rejected'
# ---------------------------------------------------------------------------

def test_reject_content(tmp_path):
    bus = _make_bus(tmp_path)
    row_id = bus.queue_content("2026-02-24", "TSLA", "thread", "TSLA thread content.")
    bus.reject_content(row_id)

    pending = bus.get_pending_content(status="pending")
    assert len(pending) == 0

    rejected = bus.get_pending_content(status="rejected")
    assert len(rejected) == 1
    assert rejected[0]["status"] == "rejected"


# ---------------------------------------------------------------------------
# 5. mark_published() sets status='published' and sets published_at
# ---------------------------------------------------------------------------

def test_mark_published(tmp_path):
    bus = _make_bus(tmp_path)
    row_id = bus.queue_content("2026-02-24", "META", "short_post", "META short post.")
    bus.approve_content(row_id)
    bus.mark_published(row_id)

    published = bus.get_pending_content(status="published")
    assert len(published) == 1
    item = published[0]
    assert item["status"] == "published"
    assert item["published_at"] is not None
    # published_at should be a valid ISO timestamp
    dt.datetime.fromisoformat(item["published_at"])


# ---------------------------------------------------------------------------
# 6. ContentDistillerAgent idle cycle (no signals)
# ---------------------------------------------------------------------------

def test_content_distiller_idle_cycle(tmp_path):
    bus = _make_bus(tmp_path)
    agent = ContentDistillerAgent(bus)
    result = agent.run_cycle()

    assert result.success is True
    assert "idle" in result.summary.lower()
    assert result.signals_published == 0


# ---------------------------------------------------------------------------
# 7. ANALYSIS_COMPLETE with no results dir -> completes without error
# ---------------------------------------------------------------------------

def test_content_distiller_no_results_dir(tmp_path):
    bus = _make_bus(tmp_path)
    _publish_analysis_complete(bus, "2026-02-24")

    # results_dir points to a nonexistent directory
    agent = ContentDistillerAgent(bus, config={"results_dir": str(tmp_path / "results")})
    result = agent.run_cycle()

    assert result.success is True
    # No content should have been queued
    assert bus.get_pending_content() == []


# ---------------------------------------------------------------------------
# 8. ANALYSIS_COMPLETE + mock decision file -> queues content
# ---------------------------------------------------------------------------

def test_content_distiller_with_decision_file(tmp_path, monkeypatch):
    bus = _make_bus(tmp_path)
    trade_date = "2026-02-24"
    ticker = "AAPL"

    # Create a fake decision file
    decision_dir = tmp_path / "results" / ticker / trade_date
    decision_dir.mkdir(parents=True)
    decision = {
        "ticker": ticker,
        "action": "BUY",
        "conviction": 0.72,
        "aeternus_score": 78.5,
        "bull_case": "Strong F-Score, revenue acceleration",
        "bear_case": "Valuation stretched at 28x forward earnings",
        "decision_date": trade_date,
    }
    (decision_dir / "decision.json").write_text(json.dumps(decision))

    # Publish the signal
    _publish_analysis_complete(bus, trade_date)

    # Mock _llm_distill to avoid real API calls
    agent = ContentDistillerAgent(bus, config={"results_dir": str(tmp_path / "results")})
    monkeypatch.setattr(agent, "_llm_distill", lambda prompt: "Test content output")

    result = agent.run_cycle()

    assert result.success is True
    assert "distilled" in result.summary

    # Two content items should be queued (short_post + thread)
    items = bus.get_pending_content()
    assert len(items) == 2
    types = {item["content_type"] for item in items}
    assert "short_post" in types
    assert "thread" in types
    for item in items:
        assert item["ticker"] == ticker
        assert item["trade_date"] == trade_date
        assert item["content"] == "Test content output"
        assert item["status"] == "pending"


def test_content_distiller_auto_publish(tmp_path, monkeypatch):
    """With AUTO_PUBLISH=true, short_post is immediately approved."""
    bus = _make_bus(tmp_path)
    trade_date = "2026-02-24"
    ticker = "GOOG"

    decision_dir = tmp_path / "results" / ticker / trade_date
    decision_dir.mkdir(parents=True)
    (decision_dir / "decision.json").write_text(json.dumps({
        "ticker": ticker, "action": "BUY", "conviction": 0.6,
    }))

    _publish_analysis_complete(bus, trade_date)

    monkeypatch.setenv("AUTO_PUBLISH", "true")
    agent = ContentDistillerAgent(bus, config={"results_dir": str(tmp_path / "results")})
    monkeypatch.setattr(agent, "_llm_distill", lambda prompt: "Auto-publish content")

    result = agent.run_cycle()
    assert result.success is True

    # short_post should be approved; thread stays pending
    approved = bus.get_pending_content(status="approved")
    assert len(approved) == 1
    assert approved[0]["content_type"] == "short_post"

    pending = bus.get_pending_content(status="pending")
    assert len(pending) == 1
    assert pending[0]["content_type"] == "thread"


def test_content_distiller_publishes_content_ready_signal(tmp_path, monkeypatch):
    """CONTENT_READY signal is published when tickers are processed."""
    bus = _make_bus(tmp_path)
    trade_date = "2026-02-24"
    ticker = "AMZN"

    decision_dir = tmp_path / "results" / ticker / trade_date
    decision_dir.mkdir(parents=True)
    (decision_dir / "decision.json").write_text(json.dumps({
        "ticker": ticker, "action": "HOLD", "conviction": 0.5,
    }))

    _publish_analysis_complete(bus, trade_date)

    agent = ContentDistillerAgent(bus, config={"results_dir": str(tmp_path / "results")})
    monkeypatch.setattr(agent, "_llm_distill", lambda prompt: "Signal test content")

    agent.run_cycle()

    # Check CONTENT_READY was published
    signals = bus.recent(hours=1)
    content_ready = [s for s in signals if s.signal_type == SignalType.CONTENT_READY]
    assert len(content_ready) == 1
    payload = content_ready[0].payload
    assert payload["trade_date"] == trade_date
    assert ticker in payload["tickers"]
    assert payload["content_queued"] == 2


def test_content_distiller_llm_failure_graceful(tmp_path, monkeypatch):
    """If LLM fails for a ticker, agent still completes successfully."""
    bus = _make_bus(tmp_path)
    trade_date = "2026-02-24"
    ticker = "NFLX"

    decision_dir = tmp_path / "results" / ticker / trade_date
    decision_dir.mkdir(parents=True)
    (decision_dir / "decision.json").write_text(json.dumps({
        "ticker": ticker, "action": "SELL", "conviction": 0.4,
    }))

    _publish_analysis_complete(bus, trade_date)

    agent = ContentDistillerAgent(bus, config={"results_dir": str(tmp_path / "results")})
    # LLM returns None (simulates failure)
    monkeypatch.setattr(agent, "_llm_distill", lambda prompt: None)

    result = agent.run_cycle()
    assert result.success is True
    # No content queued since LLM returned None
    assert bus.get_pending_content() == []


def test_content_queue_table_exists_in_schema(tmp_path):
    """Verify content_queue table is created during schema init."""
    import sqlite3
    bus = _make_bus(tmp_path)
    conn = sqlite3.connect(str(tmp_path / "test_bus.db"))
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    conn.close()
    assert "content_queue" in tables
