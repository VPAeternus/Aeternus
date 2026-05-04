"""Base class for autonomous scheduled agents."""
from __future__ import annotations
import datetime as dt
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional
from .agent_bus import AgentBus, AgentSignal, SignalType


@dataclass
class AgentRunResult:
    agent_name: str
    success: bool
    started_at: str
    completed_at: str
    signals_published: int = 0
    summary: str = ""
    error: Optional[str] = None


class BaseAutonomousAgent(ABC):
    """Base for all persistent role-based agents.

    Subclasses implement `run_cycle()` which is called on each scheduled
    activation. The base class handles lifecycle signals, error catching,
    and run result logging.
    """

    name: str  # Must be set by subclass (e.g. "DealFlowScout")

    def __init__(self, bus: AgentBus, config: dict | None = None):
        self.bus = bus
        self.config = config or {}
        self.logger = logging.getLogger(f"aeternus.agent.{self.name}")

    @abstractmethod
    def run_cycle(self) -> AgentRunResult:
        """Execute one scheduled cycle. Publish signals, return result."""
        ...

    def execute(self) -> AgentRunResult:
        """Called by supervisor. Wraps run_cycle with lifecycle signals."""
        started = dt.datetime.utcnow().isoformat()
        self.bus.publish(AgentSignal(
            signal_type=SignalType.AGENT_STARTED,
            from_agent=self.name,
            payload={"started_at": started},
        ))
        try:
            result = self.run_cycle()
            self.bus.publish(AgentSignal(
                signal_type=SignalType.AGENT_COMPLETED,
                from_agent=self.name,
                payload={"summary": result.summary, "signals": result.signals_published},
            ))
            return result
        except Exception as exc:
            self.logger.exception("Agent %s cycle failed", self.name)
            completed = dt.datetime.utcnow().isoformat()
            self.bus.publish(AgentSignal(
                signal_type=SignalType.AGENT_FAILED,
                from_agent=self.name,
                payload={"error": str(exc)},
            ))
            return AgentRunResult(
                agent_name=self.name,
                success=False,
                started_at=started,
                completed_at=completed,
                error=str(exc),
            )
