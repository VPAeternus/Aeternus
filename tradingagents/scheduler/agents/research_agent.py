"""ResearchAgent -- autonomous batch analysis agent.

Wakes when DealFlowScout publishes QUEUE_ITEM_ADDED signals.
Runs `aeternus analyze-batch` for each queued date.
Publishes ANALYSIS_COMPLETE when done.
"""
from __future__ import annotations
import datetime as dt
import subprocess
import sys
from ..base_agent import BaseAutonomousAgent, AgentRunResult
from ..agent_bus import AgentBus, AgentSignal, SignalType


class ResearchAgent(BaseAutonomousAgent):
    name = "ResearchAgent"

    def run_cycle(self) -> AgentRunResult:
        started = dt.datetime.utcnow().isoformat()
        trade_date = dt.date.today().isoformat()

        # Consume all pending QUEUE_ITEM_ADDED signals targeted at us
        signals = self.bus.consume(
            self.name,
            signal_types=[SignalType.QUEUE_ITEM_ADDED],
        )

        # If no signals, do nothing (idle cycle)
        if not signals:
            completed = dt.datetime.utcnow().isoformat()
            return AgentRunResult(
                agent_name=self.name,
                success=True,
                started_at=started,
                completed_at=completed,
                summary="no queue signals — idle cycle",
            )

        # Use the trade_date from the most recent signal if available
        for sig in signals:
            if sig.payload.get("trade_date"):
                trade_date = sig.payload["trade_date"]
                break

        cmd = [
            sys.executable, "-m", "cli.main", "analyze-batch",
            "--queue-date", trade_date,
            "--format", "json",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        success = result.returncode == 0
        summary = (
            f"analyze-batch exit={result.returncode}, "
            f"date={trade_date}, queue_signals={len(signals)}"
        )

        if success:
            self.bus.publish(AgentSignal(
                signal_type=SignalType.ANALYSIS_COMPLETE,
                from_agent=self.name,
                to_agent="PortfolioAgent",
                payload={"trade_date": trade_date, "signals_consumed": len(signals)},
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
