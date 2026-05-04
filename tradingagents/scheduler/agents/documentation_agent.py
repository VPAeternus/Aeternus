"""DocumentationAgent -- writes human-readable summaries after agent events."""
from __future__ import annotations
import datetime as dt
import json
from pathlib import Path
from ..base_agent import BaseAutonomousAgent, AgentRunResult
from ..agent_bus import AgentBus, AgentSignal, SignalType


class DocumentationAgent(BaseAutonomousAgent):
    name = "DocumentationAgent"

    def __init__(self, bus: AgentBus, config: dict | None = None):
        super().__init__(bus, config)
        self.log_dir = Path(self.config.get("log_dir", "logs/agent_docs"))

    def run_cycle(self) -> AgentRunResult:
        started = dt.datetime.utcnow().isoformat()
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # Consume all completions and risk flags addressed to us
        signals = self.bus.consume(
            self.name,
            signal_types=[
                SignalType.AGENT_COMPLETED,
                SignalType.AGENT_FAILED,
                SignalType.SIGNAL_FLIP,
                SignalType.POSITION_EXITED,
                SignalType.RISK_FLAG,
            ],
        )

        if not signals:
            completed = dt.datetime.utcnow().isoformat()
            return AgentRunResult(
                agent_name=self.name, success=True,
                started_at=started, completed_at=completed,
                summary="No events to document",
            )

        date_str = dt.date.today().isoformat()
        log_file = self.log_dir / f"agent_log_{date_str}.ndjson"

        with open(log_file, "a") as f:
            for sig in signals:
                entry = {
                    "timestamp": sig.created_at,
                    "event_type": sig.signal_type.value,
                    "from_agent": sig.from_agent,
                    "payload": sig.payload,
                }
                f.write(json.dumps(entry) + "\n")

        completed = dt.datetime.utcnow().isoformat()
        return AgentRunResult(
            agent_name=self.name, success=True,
            started_at=started, completed_at=completed,
            signals_published=0,
            summary=f"Documented {len(signals)} events -> {log_file}",
        )
