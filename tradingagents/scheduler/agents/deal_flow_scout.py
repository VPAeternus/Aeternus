"""DealFlowScout -- autonomous deal flow sourcing agent.

Runs the existing `aeternus source` pipeline on a daily schedule (pre-market).
Publishes a scout handoff signal after ticker collection.
"""
from __future__ import annotations
import datetime as dt
import subprocess
import sys
from ..base_agent import BaseAutonomousAgent, AgentRunResult
from ..agent_bus import AgentBus, AgentSignal, SignalType


class DealFlowScoutAgent(BaseAutonomousAgent):
    name = "DealFlowScout"

    def __init__(self, bus: AgentBus, config: dict | None = None):
        super().__init__(bus, config)
        self.top_k = self.config.get("top_k", 30)
        self.trigger = self.config.get("trigger", "scheduled")

    def run_cycle(self) -> AgentRunResult:
        started = dt.datetime.utcnow().isoformat()
        trade_date = dt.date.today().isoformat()

        # Invoke the existing CLI source command as a subprocess.
        # This reuses all existing sourcing pipeline logic without circular imports.
        cmd = [
            sys.executable, "-m", "cli.main", "source",
            "--date", trade_date,
            "--trigger", self.trigger,
            "--top-k", str(self.top_k),
            "--format", "json",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

        success = result.returncode == 0
        summary = f"source pipeline exit={result.returncode}, date={trade_date}"

        if success:
            self.bus.publish(AgentSignal(
                signal_type=SignalType.SCOUT_HANDOFF_READY,
                from_agent=self.name,
                to_agent="ResearchAgent",
                payload={"trade_date": trade_date, "top_k": self.top_k},
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
