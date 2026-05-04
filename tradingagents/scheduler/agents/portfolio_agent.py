"""PortfolioAgent -- autonomous portfolio construction agent.

Wakes when ResearchAgent publishes ANALYSIS_COMPLETE.
Runs `aeternus portfolio-plan` to build a trading plan from analyzed queue.
Publishes PLAN_READY when done.
"""
from __future__ import annotations
import datetime as dt
import subprocess
import sys
from ..base_agent import BaseAutonomousAgent, AgentRunResult
from ..agent_bus import AgentBus, AgentSignal, SignalType


class PortfolioAgent(BaseAutonomousAgent):
    name = "PortfolioAgent"

    def __init__(self, bus: AgentBus, config: dict | None = None):
        super().__init__(bus, config)
        self.capital_usd = self.config.get("capital_usd", 100000)
        self.max_positions = self.config.get("max_positions", 8)
        self.min_score = self.config.get("min_score", 55.0)
        self.execution_mode = self.config.get("execution_mode", "alpaca-paper")

    def run_cycle(self) -> AgentRunResult:
        started = dt.datetime.utcnow().isoformat()

        signals = self.bus.consume(
            self.name,
            signal_types=[SignalType.ANALYSIS_COMPLETE],
        )

        if not signals:
            completed = dt.datetime.utcnow().isoformat()
            return AgentRunResult(
                agent_name=self.name,
                success=True,
                started_at=started,
                completed_at=completed,
                summary="no analysis signals — idle cycle",
            )

        # Use trade_date from most recent signal
        trade_date = dt.date.today().isoformat()
        for sig in signals:
            if sig.payload.get("trade_date"):
                trade_date = sig.payload["trade_date"]
                break

        cmd = [
            sys.executable, "-m", "cli.main", "portfolio-plan",
            "--queue-date", trade_date,
            "--capital-usd", str(self.capital_usd),
            "--max-positions", str(self.max_positions),
            "--min-score", str(self.min_score),
            "--execution-mode", self.execution_mode,
            "--format", "json",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        success = result.returncode == 0
        summary = f"portfolio-plan exit={result.returncode}, date={trade_date}"

        if success:
            self.bus.publish(AgentSignal(
                signal_type=SignalType.PLAN_READY,
                from_agent=self.name,
                to_agent="ExecutionAgent",
                payload={
                    "trade_date": trade_date,
                    "execution_mode": self.execution_mode,
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
