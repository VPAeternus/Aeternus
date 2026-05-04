"""PortfolioMonitor -- daily position health check against regime-exit signals."""
from __future__ import annotations
import datetime as dt
import subprocess
import sys
from ..base_agent import BaseAutonomousAgent, AgentRunResult
from ..agent_bus import AgentBus, AgentSignal, SignalType


class PortfolioMonitorAgent(BaseAutonomousAgent):
    name = "PortfolioMonitor"

    def run_cycle(self) -> AgentRunResult:
        started = dt.datetime.utcnow().isoformat()

        # Check for inbound RISK_FLAG signals
        risk_flags = self.bus.consume(self.name, signal_types=[SignalType.RISK_FLAG])
        risk_active = len(risk_flags) > 0

        # Run manage-exits to check regime-exit signals on open positions
        cmd = [
            sys.executable, "-m", "cli.main", "manage-exits",
            "--format", "json", "--dry-run",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

        summary = f"manage-exits exit={result.returncode}"
        if risk_active:
            summary += (
                f" | RISK_FLAG active "
                f"(keywords: {[s.payload.get('matched_keywords') for s in risk_flags]})"
            )

        if result.returncode == 0:
            self.bus.publish(AgentSignal(
                signal_type=SignalType.SIGNAL_FLIP,
                from_agent=self.name,
                to_agent="DocumentationAgent",
                payload={"summary": summary, "risk_flags": len(risk_flags)},
            ))

        completed = dt.datetime.utcnow().isoformat()
        return AgentRunResult(
            agent_name=self.name,
            success=result.returncode == 0,
            started_at=started,
            completed_at=completed,
            signals_published=1,
            summary=summary,
            error=result.stderr[:500] if result.returncode != 0 else None,
        )
