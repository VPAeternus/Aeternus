"""AeternusScheduler -- persistent supervisor for autonomous role-based agents."""
from __future__ import annotations
import datetime as dt
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger
    HAS_APSCHEDULER = True
except ImportError:
    HAS_APSCHEDULER = False

from .agent_bus import AgentBus
from .base_agent import BaseAutonomousAgent, AgentRunResult

logger = logging.getLogger("aeternus.scheduler")


@dataclass
class AgentStatus:
    name: str
    enabled: bool
    last_run_at: Optional[str]
    last_success: Optional[bool]
    last_summary: Optional[str]
    next_run_at: Optional[str]


class AeternusScheduler:
    """Manages persistent autonomous agents with scheduled activations.

    Usage:
        scheduler = AeternusScheduler(bus=bus)
        scheduler.register(DealFlowScoutAgent(bus), cron="0 6 * * 1-5")  # 6am weekdays
        scheduler.register(RiskSentinelAgent(bus), interval_seconds=300)  # every 5 min
        scheduler.start()
    """

    def __init__(self, bus: AgentBus):
        self.bus = bus
        self._agents: Dict[str, BaseAutonomousAgent] = {}
        self._status: Dict[str, dict] = {}
        self._paused: set = set()
        self._scheduler = None
        if HAS_APSCHEDULER:
            self._scheduler = BackgroundScheduler(
                job_defaults={
                    "coalesce": True,
                    "max_instances": 1,
                    "misfire_grace_time": 300,
                }
            )

    def register(
        self,
        agent: BaseAutonomousAgent,
        *,
        cron: Optional[str] = None,
        interval_seconds: Optional[int] = None,
    ) -> None:
        """Register an agent with a schedule. cron takes precedence over interval."""
        if not HAS_APSCHEDULER:
            logger.warning(
                "APScheduler not installed -- agent %s registered but won't schedule",
                agent.name,
            )
        self._agents[agent.name] = agent
        self._status[agent.name] = {
            "last_run_at": None,
            "last_success": None,
            "last_summary": None,
        }

        if self._scheduler and (cron or interval_seconds):
            trigger = (
                CronTrigger.from_crontab(cron)
                if cron
                else IntervalTrigger(seconds=interval_seconds)
            )
            self._scheduler.add_job(
                self._run_agent,
                trigger=trigger,
                args=[agent.name],
                id=agent.name,
                replace_existing=True,
            )
            logger.info(
                "Registered agent %s (schedule: %s)",
                agent.name,
                cron or f"{interval_seconds}s",
            )

    def _run_agent(self, agent_name: str) -> None:
        if agent_name in self._paused:
            logger.info("Agent %s is paused -- skipping cycle", agent_name)
            return
        agent = self._agents.get(agent_name)
        if not agent:
            return
        logger.info("Running agent %s", agent_name)
        result = agent.execute()
        self._status[agent_name] = {
            "last_run_at": result.started_at,
            "last_success": result.success,
            "last_summary": result.summary or result.error,
        }

    def trigger(self, agent_name: str) -> AgentRunResult:
        """Manually trigger an agent immediately (for CLI/gateway use)."""
        agent = self._agents.get(agent_name)
        if not agent:
            raise ValueError(f"Unknown agent: {agent_name}")
        result = agent.execute()
        self._status[agent_name] = {
            "last_run_at": result.started_at,
            "last_success": result.success,
            "last_summary": result.summary or result.error,
        }
        return result

    def pause(self, agent_name: str) -> None:
        self._paused.add(agent_name)
        logger.info("Agent %s paused", agent_name)

    def resume(self, agent_name: str) -> None:
        self._paused.discard(agent_name)
        logger.info("Agent %s resumed", agent_name)

    def status(self) -> List[dict]:
        results = []
        for name in self._agents:
            s = self._status.get(name, {})
            next_run = None
            if self._scheduler:
                job = self._scheduler.get_job(name)
                if job and job.next_run_time:
                    next_run = job.next_run_time.isoformat()
            results.append({
                "name": name,
                "enabled": name not in self._paused,
                "last_run_at": s.get("last_run_at"),
                "last_success": s.get("last_success"),
                "last_summary": s.get("last_summary"),
                "next_run_at": next_run,
            })
        return results

    def start(self) -> None:
        if self._scheduler:
            self._scheduler.start()
            logger.info(
                "AeternusScheduler started with %d agents", len(self._agents)
            )

    def stop(self) -> None:
        if self._scheduler and self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("AeternusScheduler stopped")
