"""ResearchAgent -- scout handoff boundary agent.

Wakes when DealFlowScout publishes a handoff signal and stops there. Scout
tickers must enter the fundamental framework before any scoring or analysis
completion signal is emitted.
"""
from __future__ import annotations
import datetime as dt
from ..base_agent import BaseAutonomousAgent, AgentRunResult
from ..agent_bus import AgentBus, SignalType


class ResearchAgent(BaseAutonomousAgent):
    name = "ResearchAgent"

    def run_cycle(self) -> AgentRunResult:
        started = dt.datetime.utcnow().isoformat()
        trade_date = dt.date.today().isoformat()

        signals = self.bus.consume(
            self.name,
            signal_types=[SignalType.SCOUT_HANDOFF_READY],
        )

        if not signals:
            completed = dt.datetime.utcnow().isoformat()
            return AgentRunResult(
                agent_name=self.name,
                success=True,
                started_at=started,
                completed_at=completed,
                summary="no scout handoff signals — idle cycle",
            )

        # Use the trade_date from the most recent signal if available
        for sig in signals:
            if sig.payload.get("trade_date"):
                trade_date = sig.payload["trade_date"]
                break

        success = True
        summary = (
            "scout handoff acknowledged; run fundamental framework before "
            f"downstream analysis signals, date={trade_date}, signals={len(signals)}"
        )

        completed = dt.datetime.utcnow().isoformat()
        return AgentRunResult(
            agent_name=self.name,
            success=success,
            started_at=started,
            completed_at=completed,
            signals_published=0,
            summary=summary,
            error=None,
        )
