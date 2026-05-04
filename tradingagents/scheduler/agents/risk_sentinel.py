"""RiskSentinel -- intraday macro event monitor.

Watches for market-moving events (geopolitical posts, Fed deviations,
sector-defining announcements) during market hours only.
Does NOT re-run the full analysis pipeline -- fires RISK_FLAG for
PortfolioMonitor to act on existing positions.

Signal architecture principle: open/close for alpha, intraday for risk only.
"""
from __future__ import annotations
import datetime as dt
from typing import List
from ..base_agent import BaseAutonomousAgent, AgentRunResult
from ..agent_bus import AgentBus, AgentSignal, SignalType


# Keywords that suggest market-moving macro events
MACRO_KEYWORDS = [
    "trump", "tariff", "sanctions", "executive order", "emergency",
    "fed chair", "federal reserve", "rate hike", "rate cut", "fomc",
    "inflation", "cpi", "jobs report", "recession",
    "anthropic", "openai", "nvidia", "semiconductor", "chip ban",
    "bank failure", "contagion", "circuit breaker", "halt",
]

RISK_THRESHOLD_SCORE = 3  # Min keyword matches to flag as risk event


class RiskSentinelAgent(BaseAutonomousAgent):
    name = "RiskSentinel"

    def _is_market_hours(self) -> bool:
        """Only run during US market hours (9:30am-4pm ET weekdays)."""
        now_et = dt.datetime.utcnow() - dt.timedelta(hours=5)  # rough ET
        if now_et.weekday() >= 5:  # weekend
            return False
        return dt.time(9, 30) <= now_et.time() <= dt.time(16, 0)

    def _fetch_recent_headlines(self) -> List[str]:
        """Fetch recent news headlines via existing data vendor stack."""
        try:
            from tradingagents.dataflows.interface import get_interface
            iface = get_interface()
            # Lightweight: fetch market news (not per-ticker)
            news = iface.get_news("SPY", max_results=20)
            headlines = []
            for item in (news or []):
                if isinstance(item, dict):
                    headlines.append(
                        item.get("title", "") + " " + item.get("summary", "")
                    )
                elif isinstance(item, str):
                    headlines.append(item)
            return headlines
        except Exception as exc:
            self.logger.warning("RiskSentinel news fetch failed: %s", exc)
            return []

    def _score_headlines(self, headlines: List[str]) -> tuple:
        """Score headlines for macro risk keywords. Returns (score, matched_terms)."""
        text = " ".join(headlines).lower()
        matched = [kw for kw in MACRO_KEYWORDS if kw in text]
        return len(matched), matched

    def run_cycle(self) -> AgentRunResult:
        started = dt.datetime.utcnow().isoformat()

        if not self._is_market_hours():
            completed = dt.datetime.utcnow().isoformat()
            return AgentRunResult(
                agent_name=self.name, success=True,
                started_at=started, completed_at=completed,
                summary="Outside market hours -- skipped",
            )

        headlines = self._fetch_recent_headlines()
        score, matched = self._score_headlines(headlines)
        risk_flagged = score >= RISK_THRESHOLD_SCORE

        signals_published = 0
        if risk_flagged:
            self.bus.publish(AgentSignal(
                signal_type=SignalType.RISK_FLAG,
                from_agent=self.name,
                payload={
                    "score": score,
                    "matched_keywords": matched,
                    "headline_count": len(headlines),
                    "flagged_at": started,
                    "action": "review_open_positions",
                },
            ))
            signals_published = 1
            self.logger.warning(
                "RISK_FLAG raised: score=%d keywords=%s", score, matched
            )

        completed = dt.datetime.utcnow().isoformat()
        return AgentRunResult(
            agent_name=self.name, success=True,
            started_at=started, completed_at=completed,
            signals_published=signals_published,
            summary=(
                f"score={score} risk={'FLAGGED' if risk_flagged else 'clear'} "
                f"headlines={len(headlines)}"
            ),
        )
