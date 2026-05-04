"""InvestmentCommitteeAgent — closed-loop outcome attribution engine.

Reads calibration and live outcome reports, makes a single deep LLM call
to reason about what the data implies, writes 3 adjustment JSON files
with TTL expiry. Downstream consumers read these and apply additive deltas.
"""
from __future__ import annotations
import datetime as dt
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict

from ..base_agent import BaseAutonomousAgent, AgentRunResult
from ..agent_bus import AgentBus, AgentSignal, SignalType

logger = logging.getLogger(__name__)

IC_SYSTEM_PROMPT = """You are the Investment Committee for an autonomous AI hedge fund.
You are reviewing the system's own track record to adjust future behavior.

You will receive:
- Calibration data: predicted vs actual win rates by confidence level
- Accuracy by sector and regime
- Systematic biases detected
- Live outcome metrics: win rate, profit factor, avg return, breakdowns by lane/exit rule

Based on this data, produce adjustments in THREE categories:

1. signal_weight_deltas: Additive changes to deal flow scoring weights.
   Keys must be from: social_momentum, price_momentum, macro_regime_fit, news_catalyst,
   smart_money, liquidity_tradability, sector_rotation, breakout_discovery.
   Values are floats (e.g., +5.0, -3.0). Conservative adjustments preferred.

2. confidence_calibration: Per-confidence-level delta (keys "1" through "5").
   Values are floats applied to scorer confidence output (e.g., -0.5 means reduce confidence
   at that level by 0.5). Only adjust levels where calibration data shows clear over/under-confidence.

3. sector_overrides: Sector-level score multiplier deltas.
   Keys are sector names (e.g., "Technology", "Energy"). Values are floats in [-0.20, +0.20]
   applied as additive bonus/penalty to deal flow core_score.

RULES:
- Be conservative. Small adjustments (±2-5 for weights, ±0.3-0.5 for confidence) are preferred.
- Only adjust what the data clearly supports. If a sector has <5 trades, do not override it.
- If win rate is already good (>55%), focus on reducing overconfidence rather than adding risk.
- If a lane (MOMENTUM vs CORE) underperforms, shift weight toward the better lane's signals.
- Return ONLY valid JSON with exactly these 3 keys. No commentary.
"""

IC_USER_PROMPT = """## Calibration Report
{calibration_json}

## Live Outcome Report
{outcomes_json}

Based on this data, provide your adjustments as JSON with keys:
signal_weight_deltas, confidence_calibration, sector_overrides"""


class InvestmentCommitteeAgent(BaseAutonomousAgent):
    name = "InvestmentCommittee"

    def __init__(self, bus: AgentBus, config: dict | None = None):
        super().__init__(bus, config)
        self.output_dir = Path(self.config.get("output_dir", "eval_results/control"))
        self.min_closed_trades = int(self.config.get("min_closed_trades", 10))

    def run_cycle(self) -> AgentRunResult:
        started = dt.datetime.utcnow().isoformat()

        # 1. Load data
        from tradingagents.graph.calibration import build_calibration_report
        from tradingagents.evidence.live_outcomes import build_live_outcome_report

        calibration = build_calibration_report()
        outcomes = build_live_outcome_report()

        # 2. Guard: need minimum closed trades
        closed = calibration.get("closed_decisions", 0)
        if closed < self.min_closed_trades:
            completed = dt.datetime.utcnow().isoformat()
            return AgentRunResult(
                agent_name=self.name,
                success=True,
                started_at=started,
                completed_at=completed,
                summary=f"insufficient data ({closed} closed trades, need {self.min_closed_trades})",
            )

        # 3. Single deep LLM call
        adjustments = self._reason_adjustments(calibration, outcomes)

        # 4. Write 3 adjustment files with TTL
        self._write_adjustment("ic_signal_weights.json", adjustments.get("signal_weight_deltas", {}))
        self._write_adjustment("ic_confidence_calibration.json", adjustments.get("confidence_calibration", {}))
        self._write_adjustment("ic_sector_overrides.json", adjustments.get("sector_overrides", {}))

        # 5. Publish IC_REVIEW_COMPLETE signal
        self.bus.publish(AgentSignal(
            signal_type=SignalType.IC_REVIEW_COMPLETE,
            from_agent=self.name,
            payload={"adjustments_written": True, "closed_trades": closed},
        ))

        completed = dt.datetime.utcnow().isoformat()
        return AgentRunResult(
            agent_name=self.name,
            success=True,
            started_at=started,
            completed_at=completed,
            signals_published=1,
            summary=f"IC review complete, {closed} trades analyzed",
        )

    def _reason_adjustments(self, calibration: dict, outcomes: dict) -> dict:
        """Call LLM to reason about adjustments. Returns dict with 3 keys."""
        # Build condensed versions (strip trades list to save tokens)
        cal_condensed = {k: v for k, v in calibration.items() if k != "last_updated"}
        out_condensed = {k: v for k, v in outcomes.items() if k != "trades"}

        prompt = IC_USER_PROMPT.format(
            calibration_json=json.dumps(cal_condensed, indent=2, default=str),
            outcomes_json=json.dumps(out_condensed, indent=2, default=str),
        )

        try:
            from openai import OpenAI
            client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
            resp = client.chat.completions.create(
                model=self.config.get("llm_model", "gpt-4o"),
                messages=[
                    {"role": "system", "content": IC_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=1500,
                temperature=0.2,
                response_format={"type": "json_object"},
            )
            raw = resp.choices[0].message.content
            parsed = json.loads(raw)
            # Validate and clamp
            return self._validate_adjustments(parsed)
        except Exception as e:
            self.logger.warning("IC LLM call failed: %s", e)
            return {"signal_weight_deltas": {}, "confidence_calibration": {}, "sector_overrides": {}}

    def _validate_adjustments(self, raw: dict) -> dict:
        """Validate and clamp adjustment values."""
        result = {
            "signal_weight_deltas": {},
            "confidence_calibration": {},
            "sector_overrides": {},
        }

        # Signal weight deltas: clamp so final weight stays in [0, 40]
        from tradingagents.dealflow.scoring import CORE_SCORE_WEIGHTS
        valid_families = set(CORE_SCORE_WEIGHTS.keys())
        for family, delta in (raw.get("signal_weight_deltas") or {}).items():
            if family not in valid_families:
                continue
            try:
                delta = float(delta)
                current = CORE_SCORE_WEIGHTS[family]
                # Clamp so final stays in [0, 40]
                delta = max(-current, min(40.0 - current, delta))
                result["signal_weight_deltas"][family] = round(delta, 2)
            except (TypeError, ValueError):
                continue

        # Confidence calibration: keys "1"-"5", clamp to keep final in [1, 5]
        for level, delta in (raw.get("confidence_calibration") or {}).items():
            if str(level) not in {"1", "2", "3", "4", "5"}:
                continue
            try:
                delta = float(delta)
                delta = max(-4.0, min(4.0, delta))
                result["confidence_calibration"][str(level)] = round(delta, 2)
            except (TypeError, ValueError):
                continue

        # Sector overrides: clamp to [-0.20, +0.20]
        for sector, delta in (raw.get("sector_overrides") or {}).items():
            try:
                delta = float(delta)
                delta = max(-0.20, min(0.20, delta))
                result["sector_overrides"][sector] = round(delta, 4)
            except (TypeError, ValueError):
                continue

        return result

    def _write_adjustment(self, filename: str, adjustments: dict) -> None:
        """Write adjustment file with TTL expiry."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        now = dt.datetime.now(dt.timezone.utc)
        expires = now + dt.timedelta(days=7)
        payload = {
            "generated_at": now.isoformat(),
            "expires_at": expires.isoformat(),
            "generated_by": "InvestmentCommittee",
            "closed_trades_analyzed": 0,  # filled by caller context
            "adjustments": adjustments,
        }
        path = self.output_dir / filename
        path.write_text(json.dumps(payload, indent=2))


def load_ic_adjustments(filename: str, output_dir: str = "eval_results/control") -> Dict[str, Any]:
    """Load IC adjustment file. Returns empty dict if missing or expired."""
    path = Path(output_dir) / filename
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            return {}
        expires_at = data.get("expires_at")
        if not expires_at:
            return {}
        # Parse expiry and check
        expiry = dt.datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        now = dt.datetime.now(dt.timezone.utc)
        if now > expiry:
            return {}
        return data
    except Exception:
        return {}
