"""ExecutionAgent -- autonomous paper order execution agent.

Wakes when PortfolioAgent publishes PLAN_READY.
Runs `aeternus execute-paper` to submit orders to Alpaca paper.
Publishes EXECUTION_COMPLETE when done.
"""
from __future__ import annotations
import datetime as dt
import subprocess
import sys
from ..base_agent import BaseAutonomousAgent, AgentRunResult
from ..agent_bus import AgentBus, AgentSignal, SignalType


class ExecutionAgent(BaseAutonomousAgent):
    name = "ExecutionAgent"

    def __init__(self, bus: AgentBus, config: dict | None = None):
        super().__init__(bus, config)
        self.execution_mode = self.config.get("execution_mode", "alpaca-paper")

    def run_cycle(self) -> AgentRunResult:
        started = dt.datetime.utcnow().isoformat()

        signals = self.bus.consume(
            self.name,
            signal_types=[SignalType.PLAN_READY],
        )

        if not signals:
            completed = dt.datetime.utcnow().isoformat()
            return AgentRunResult(
                agent_name=self.name,
                success=True,
                started_at=started,
                completed_at=completed,
                summary="no plan signals — idle cycle",
            )

        # Use execution_mode from signal if provided
        execution_mode = self.execution_mode
        for sig in signals:
            if sig.payload.get("execution_mode"):
                execution_mode = sig.payload["execution_mode"]
                break

        cmd = [
            sys.executable, "-m", "cli.main", "execute-paper",
            "--execution-mode", execution_mode,
            "--format", "json",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        success = result.returncode == 0
        summary = f"execute-paper exit={result.returncode}, mode={execution_mode}"

        if success:
            self.bus.publish(AgentSignal(
                signal_type=SignalType.EXECUTION_COMPLETE,
                from_agent=self.name,
                to_agent="DocumentationAgent",
                payload={
                    "execution_mode": execution_mode,
                    "signals_consumed": len(signals),
                },
            ))

        completed = dt.datetime.utcnow().isoformat()
        return AgentRunResult(
            agent_name=self.name,
            success=success,
            started_at=started,
            completed_at=completed,
            signals_published=1 if success else 0,
            summary=summary,
            error=result.stderr[:500] if not success else None,
        )
