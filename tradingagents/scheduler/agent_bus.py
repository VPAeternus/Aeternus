"""Inter-agent signal bus backed by the existing allocator SQLite database."""

from __future__ import annotations
import datetime as dt
import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


class SignalType(str, Enum):
    QUEUE_ITEM_ADDED = "QUEUE_ITEM_ADDED"       # DealFlowScout -> ResearchAgent
    ANALYSIS_COMPLETE = "ANALYSIS_COMPLETE"     # ResearchAgent -> PortfolioMonitor
    RISK_FLAG = "RISK_FLAG"                     # RiskSentinel -> all agents
    SIGNAL_FLIP = "SIGNAL_FLIP"                 # PortfolioMonitor -> DocumentationAgent
    POSITION_EXITED = "POSITION_EXITED"         # ExecutionAgent -> DocumentationAgent
    CONTENT_READY = "CONTENT_READY"             # ContentDistiller -> DocumentationAgent
    PLAN_READY = "PLAN_READY"                   # PortfolioAgent -> ExecutionAgent
    EXECUTION_COMPLETE = "EXECUTION_COMPLETE"   # ExecutionAgent -> DocumentationAgent
    AGENT_STARTED = "AGENT_STARTED"             # Supervisor lifecycle
    AGENT_COMPLETED = "AGENT_COMPLETED"         # Supervisor lifecycle
    AGENT_FAILED = "AGENT_FAILED"               # Supervisor lifecycle
    IC_REVIEW_COMPLETE = "IC_REVIEW_COMPLETE"   # InvestmentCommittee -> broadcast


@dataclass
class AgentSignal:
    signal_type: SignalType
    from_agent: str
    payload: Dict[str, Any] = field(default_factory=dict)
    to_agent: Optional[str] = None   # None = broadcast
    signal_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = field(default_factory=lambda: dt.datetime.utcnow().isoformat())
    processed_at: Optional[str] = None


class AgentBus:
    """Lightweight SQLite-backed signal queue for inter-agent communication.

    Agents publish signals via `publish()`. They consume unprocessed signals
    addressed to them (or broadcast) via `consume()`. Each signal is processed
    at most once per consumer via atomic mark-as-processed.
    """

    TABLE_DDL = """
    CREATE TABLE IF NOT EXISTS agent_signals (
        signal_id TEXT PRIMARY KEY,
        signal_type TEXT NOT NULL,
        from_agent TEXT NOT NULL,
        to_agent TEXT,
        payload TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        processed_at TEXT,
        processed_by TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_agent_signals_to_agent ON agent_signals(to_agent, processed_at);
    CREATE INDEX IF NOT EXISTS idx_agent_signals_created ON agent_signals(created_at DESC);
    CREATE TABLE IF NOT EXISTS content_queue (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        trade_date TEXT NOT NULL,
        ticker TEXT NOT NULL,
        content_type TEXT NOT NULL,
        platform TEXT NOT NULL DEFAULT 'all',
        content TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        created_at TEXT NOT NULL,
        published_at TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_content_queue_status ON content_queue(status);
    """

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self._init_schema()

    def _conn(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_schema(self) -> None:
        with self._conn() as conn:
            conn.executescript(self.TABLE_DDL)

    def publish(self, signal: AgentSignal) -> None:
        """Publish a signal to the bus."""
        with self._conn() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO agent_signals
                   (signal_id, signal_type, from_agent, to_agent, payload, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (signal.signal_id, signal.signal_type.value, signal.from_agent,
                 signal.to_agent, json.dumps(signal.payload), signal.created_at),
            )

    def consume(self, agent_name: str, signal_types: Optional[List[SignalType]] = None,
                limit: int = 50) -> List[AgentSignal]:
        """Return unprocessed signals for agent_name (targeted or broadcast).
        Marks them as processed atomically."""
        now = dt.datetime.utcnow().isoformat()
        type_filter = ""
        params: list = [agent_name, agent_name]
        if signal_types:
            placeholders = ",".join("?" * len(signal_types))
            type_filter = f"AND signal_type IN ({placeholders})"
            params.extend(t.value for t in signal_types)
        params.append(limit)

        with self._conn() as conn:
            rows = conn.execute(
                f"""SELECT * FROM agent_signals
                    WHERE processed_at IS NULL
                    AND (to_agent = ? OR to_agent IS NULL)
                    AND (processed_by IS NULL OR processed_by != ?)
                    {type_filter}
                    ORDER BY created_at ASC
                    LIMIT ?""",
                params,
            ).fetchall()

            signals = []
            for row in rows:
                conn.execute(
                    """UPDATE agent_signals SET processed_at=?, processed_by=?
                       WHERE signal_id=? AND processed_at IS NULL""",
                    (now, agent_name, row["signal_id"]),
                )
                signals.append(AgentSignal(
                    signal_id=row["signal_id"],
                    signal_type=SignalType(row["signal_type"]),
                    from_agent=row["from_agent"],
                    to_agent=row["to_agent"],
                    payload=json.loads(row["payload"]),
                    created_at=row["created_at"],
                    processed_at=now,
                ))
            return signals

    def queue_content(self, trade_date: str, ticker: str, content_type: str,
                      content: str, platform: str = "all") -> int:
        """Queue a piece of content for review/publishing. Returns row id."""
        now = dt.datetime.utcnow().isoformat()
        with self._conn() as conn:
            cur = conn.execute(
                """INSERT INTO content_queue
                   (trade_date, ticker, content_type, platform, content, status, created_at)
                   VALUES (?, ?, ?, ?, ?, 'pending', ?)""",
                (trade_date, ticker, content_type, platform, content, now),
            )
            return cur.lastrowid

    def get_pending_content(self, limit: int = 20, status: str = "pending") -> List[dict]:
        """Return content items filtered by status."""
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT id, trade_date, ticker, content_type, platform, content,
                          status, created_at, published_at
                   FROM content_queue WHERE status = ?
                   ORDER BY created_at ASC LIMIT ?""",
                (status, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def approve_content(self, content_id: int) -> None:
        """Mark content as approved (ready to publish)."""
        with self._conn() as conn:
            conn.execute(
                "UPDATE content_queue SET status='approved' WHERE id=?",
                (content_id,),
            )

    def reject_content(self, content_id: int) -> None:
        """Mark content as rejected."""
        with self._conn() as conn:
            conn.execute(
                "UPDATE content_queue SET status='rejected' WHERE id=?",
                (content_id,),
            )

    def mark_published(self, content_id: int) -> None:
        """Mark content as published."""
        now = dt.datetime.utcnow().isoformat()
        with self._conn() as conn:
            conn.execute(
                "UPDATE content_queue SET status='published', published_at=? WHERE id=?",
                (now, content_id),
            )

    def recent(self, hours: float = 24, limit: int = 200) -> List[AgentSignal]:
        """Fetch recent signals for monitoring/display (read-only)."""
        since = (dt.datetime.utcnow() - dt.timedelta(hours=hours)).isoformat()
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT * FROM agent_signals WHERE created_at >= ?
                   ORDER BY created_at DESC LIMIT ?""",
                (since, limit),
            ).fetchall()
        return [AgentSignal(
            signal_id=r["signal_id"],
            signal_type=SignalType(r["signal_type"]),
            from_agent=r["from_agent"],
            to_agent=r["to_agent"],
            payload=json.loads(r["payload"]),
            created_at=r["created_at"],
            processed_at=r["processed_at"],
        ) for r in rows]
