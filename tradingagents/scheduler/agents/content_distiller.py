"""ContentDistillerAgent -- transforms agent reasoning into subscriber content.

Consumes ANALYSIS_COMPLETE signals, reads the full decision rationale,
and produces authentic subscriber-ready content that publishes the process —
not a marketing version of it.

Content is queued for human review by default. Set AUTO_PUBLISH=true to
bypass the review gate (only appropriate after voice is established).
"""
from __future__ import annotations
import datetime as dt
import json
import os
from pathlib import Path
from ..base_agent import BaseAutonomousAgent, AgentRunResult
from ..agent_bus import AgentBus, AgentSignal, SignalType


DISTILL_SYSTEM_PROMPT = """You are the content voice for an autonomous AI investment system.
Your job is to translate internal trading decisions into transparent, authentic subscriber content.

RULES:
- Never hide uncertainty. If the bull case was 60/40 vs bear, say so explicitly.
- Show the trade-off, not just the conclusion. What is the strongest counterargument? Why did the final decision win?
- Include actual numbers: scores, conviction levels, key metrics that drove the decision.
- Do not use marketing language. No "exciting opportunity" or "strong conviction play."
- Do not predict the future. Say what the system decided and why, not what will happen.
- Acknowledge when a thesis is wrong quickly — it builds more trust than silence.
- Write as if a thoughtful analyst is explaining their process to a peer, not selling to a retail investor.

TONE: Authentic process documentation. Transparent about uncertainty. Confident in the methodology even when uncertain about the outcome.
"""

SHORT_POST_PROMPT = """Generate a short post (under 280 characters) summarizing this investment decision.

Must include: ticker, direction (long/reduce/hold), and the single most important factor that drove the decision.
Do NOT use hashtags or emojis. Plain text only.

Decision data:
{decision_json}
"""

THREAD_PROMPT = """Generate a 5-7 post thread explaining this investment decision to subscribers.

Post 1: The decision (ticker, direction, conviction level as a percentage)
Post 2: The bull case — what argues FOR this position
Post 3: The bear case — what argues AGAINST (include the strongest counterargument)
Post 4: What tipped the balance — the key factor that resolved the trade-off
Post 5: Key metrics (include actual numbers: scores, ratios, whatever drove the analysis)
Post 6 (if warranted): Risk acknowledgment — what would change this view
Post 7 (optional): One-line process note ("This is post #N in our live track record. Every decision is logged.")

Format each post as "Post N: [content]" on its own line.
Separator between posts: ---

Decision data:
{decision_json}
"""


class ContentDistillerAgent(BaseAutonomousAgent):
    name = "ContentDistiller"

    def __init__(self, bus: AgentBus, config: dict | None = None):
        super().__init__(bus, config)
        self.results_dir = Path(self.config.get("results_dir", "results"))
        self.auto_publish = os.environ.get("AUTO_PUBLISH", "false").lower() == "true"

    def _load_decision(self, ticker: str, trade_date: str) -> dict | None:
        """Load the decision summary for a ticker/date from results/."""
        base = self.results_dir / ticker / trade_date
        if not base.exists():
            return None
        for name in ["decision.json", "summary.json", "result.json", "final.json"]:
            f = base / name
            if f.exists():
                try:
                    return json.loads(f.read_text())
                except Exception:
                    pass
        # Try any .json file in the directory
        for f in base.glob("*.json"):
            try:
                data = json.loads(f.read_text())
                if isinstance(data, dict) and len(data) > 2:
                    return data
            except Exception:
                pass
        return None

    def _llm_distill(self, prompt: str) -> str | None:
        """Call the LLM to distill content. Returns generated text or None on failure."""
        try:
            from openai import OpenAI
            client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": DISTILL_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=1000,
                temperature=0.3,
            )
            return resp.choices[0].message.content
        except Exception as e:
            self.logger.warning("LLM distill failed: %s", e)
            return None

    def _distill_decision(self, ticker: str, trade_date: str, decision: dict) -> int:
        """Distill one decision into content. Returns number of items queued."""
        decision_json = json.dumps(decision, indent=2, default=str)[:3000]
        queued = 0

        # Short post
        short_prompt = SHORT_POST_PROMPT.format(decision_json=decision_json)
        short_content = self._llm_distill(short_prompt)
        if short_content:
            content_id = self.bus.queue_content(trade_date, ticker, "short_post", short_content)
            if self.auto_publish:
                self.bus.approve_content(content_id)
            queued += 1

        # Thread
        thread_prompt = THREAD_PROMPT.format(decision_json=decision_json)
        thread_content = self._llm_distill(thread_prompt)
        if thread_content:
            self.bus.queue_content(trade_date, ticker, "thread", thread_content)
            queued += 1

        return queued

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

        total_queued = 0
        processed_dates: list[str] = []

        for sig in signals:
            trade_date = sig.payload.get("trade_date", dt.date.today().isoformat())
            processed_dates.append(trade_date)

            if not self.results_dir.exists():
                continue

            tickers_processed: list[str] = []
            for ticker_dir in self.results_dir.iterdir():
                if not ticker_dir.is_dir():
                    continue
                ticker = ticker_dir.name
                decision = self._load_decision(ticker, trade_date)
                if not decision:
                    continue
                try:
                    n = self._distill_decision(ticker, trade_date, decision)
                    total_queued += n
                    tickers_processed.append(ticker)
                except Exception as exc:
                    self.logger.warning("Failed to distill %s/%s: %s", ticker, trade_date, exc)

            if tickers_processed:
                self.bus.publish(AgentSignal(
                    signal_type=SignalType.CONTENT_READY,
                    from_agent=self.name,
                    to_agent="DocumentationAgent",
                    payload={
                        "trade_date": trade_date,
                        "tickers": tickers_processed,
                        "content_queued": total_queued,
                        "auto_publish": self.auto_publish,
                    },
                ))

        completed = dt.datetime.utcnow().isoformat()
        return AgentRunResult(
            agent_name=self.name,
            success=True,
            started_at=started,
            completed_at=completed,
            signals_published=len(processed_dates),
            summary=f"distilled {len(processed_dates)} date(s), queued {total_queued} content items",
        )
