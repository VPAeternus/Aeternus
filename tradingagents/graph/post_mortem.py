# tradingagents/graph/post_mortem.py
"""Post-Mortem Attribution Engine.

Analyzes closed trades to attribute outcomes to scoring pillars, agent
decisions, and regime weight choices.  Pure local Python — no external APIs.
"""

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .regime_weights import REGIME_WEIGHTS, get_weights


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PILLARS = ("fundamental", "coherence", "macro", "sentiment", "momentum")


def _rating_from_score(score: float) -> str:
    if score >= 80:
        return "Strong Buy"
    if score >= 60:
        return "Buy"
    if score >= 40:
        return "Hold"
    if score >= 20:
        return "Sell"
    return "Strong Sell"


def _extract_decision(text: str) -> str:
    """Extract BUY/SELL/HOLD from free-form agent text via regex."""
    if not text:
        return "UNKNOWN"
    # Look for recommendation/decision keywords followed by BUY/SELL/HOLD
    m = re.search(
        r"(?:recommendation|decision|verdict|action)[:\s]*\*{0,2}\s*(STRONG\s+)?(BUY|SELL|HOLD)",
        text,
        re.IGNORECASE,
    )
    if m:
        return m.group(2).upper()
    # Fallback: first standalone BUY/SELL/HOLD
    m = re.search(r"\b(BUY|SELL|HOLD)\b", text, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    return "UNKNOWN"


def _outcome_label(return_pct: float) -> str:
    if return_pct > 0.5:
        return "WIN"
    if return_pct < -0.5:
        return "LOSS"
    return "FLAT"


def _pillar_signal(score: int) -> str:
    if score >= 60:
        return "BULLISH"
    if score < 40:
        return "BEARISH"
    return "NEUTRAL"


def _pillar_verdict(signal: str, return_pct: float) -> str:
    if signal == "NEUTRAL" or abs(return_pct) < 0.5:
        return "NEUTRAL"
    positive = return_pct > 0
    if signal == "BULLISH" and positive:
        return "RIGHT"
    if signal == "BEARISH" and not positive:
        return "RIGHT"
    return "WRONG"


def _decision_verdict(decision: str, return_pct: float) -> str:
    if decision in ("UNKNOWN", "HOLD"):
        return "NEUTRAL"
    positive = return_pct > 0
    if decision == "BUY" and positive:
        return "CORRECT"
    if decision == "SELL" and not positive:
        return "CORRECT"
    if decision == "BUY" and not positive:
        return "INCORRECT"
    if decision == "SELL" and positive:
        return "INCORRECT"
    return "NEUTRAL"


# ---------------------------------------------------------------------------
# PostMortemEngine
# ---------------------------------------------------------------------------


class PostMortemEngine:
    """Analyse closed trades and attribute outcomes to pillars, agents, and regimes."""

    def __init__(
        self,
        results_root: str = "results",
        closed_trades_path: str = "eval_results/paper_execution/closed_trades.json",
        track_record_path: str = "eval_results/track_record.json",
    ):
        self.results_root = Path(results_root)
        self.closed_trades_path = Path(closed_trades_path)
        self.track_record_path = Path(track_record_path)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze_all(self) -> List[Dict[str, Any]]:
        """Load closed trades, deduplicate, attribute each, return list."""
        trades = self._load_closed_trades()
        if not trades:
            return []

        trades = self._deduplicate(trades)
        attributions: List[Dict[str, Any]] = []
        for trade in trades:
            report = self._load_analysis_report(trade)
            attr = self.analyze_trade(trade, report)
            attributions.append(attr)
        return attributions

    def analyze_trade(
        self,
        trade: Dict[str, Any],
        report: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Produce attribution dict for a single closed trade."""
        ticker = trade.get("symbol", "")
        return_pct = trade.get("return_pct", 0.0)
        pnl_usd = trade.get("pnl_usd", 0.0)
        outcome = _outcome_label(return_pct)

        # Extract score data from report
        score_data = (report or {}).get("aeternus_score", {}) if report else {}
        breakdown = score_data.get("breakdown", {})
        entry_score = score_data.get("aeternus_score", 0.0)
        entry_rating = score_data.get("rating", "")
        weight_regime = score_data.get("weight_regime", "NEUTRAL")

        report_found = report is not None and bool(score_data)

        # Pillar attribution
        pillar_attribution = self.compute_pillar_attribution(breakdown, return_pct) if report_found else {}

        pillar_summary = {"right_count": 0, "wrong_count": 0, "neutral_count": 0}
        for pa in pillar_attribution.values():
            v = pa.get("verdict", "NEUTRAL")
            if v == "RIGHT":
                pillar_summary["right_count"] += 1
            elif v == "WRONG":
                pillar_summary["wrong_count"] += 1
            else:
                pillar_summary["neutral_count"] += 1

        # Agent accuracy
        agent_accuracy = {}
        if report_found:
            invest_debate = (report or {}).get("investment_debate_state", {})
            risk_debate = (report or {}).get("risk_debate_state", {})
            trader_text = (report or {}).get("trader_investment_plan", "")
            agent_accuracy = self.compute_agent_accuracy(
                invest_debate, risk_debate, trader_text, return_pct
            )

        # Counterfactual
        counterfactual = self.compute_counterfactual(breakdown, weight_regime) if report_found else {}

        # Narrative
        attr: Dict[str, Any] = {
            "ticker": ticker,
            "close_id": trade.get("close_id", ""),
            "close_date": trade.get("close_date", ""),
            "weight_regime": weight_regime,
            "return_pct": round(return_pct, 2),
            "pnl_usd": round(pnl_usd, 2),
            "outcome": outcome,
            "entry_score": entry_score,
            "entry_rating": entry_rating,
            "breakdown": breakdown,
            "pillar_attribution": pillar_attribution,
            "pillar_summary": pillar_summary,
            "agent_accuracy": agent_accuracy,
            "counterfactual": counterfactual,
            "narrative": "",
            "report_found": report_found,
        }
        attr["narrative"] = self.generate_narrative(attr)
        return attr

    # ------------------------------------------------------------------
    # Pillar Attribution
    # ------------------------------------------------------------------

    def compute_pillar_attribution(
        self,
        breakdown: Dict[str, int],
        return_pct: float,
    ) -> Dict[str, Dict[str, Any]]:
        result: Dict[str, Dict[str, Any]] = {}
        for pillar in _PILLARS:
            score = breakdown.get(pillar)
            if score is None:
                continue
            signal = _pillar_signal(score)
            verdict = _pillar_verdict(signal, return_pct)
            result[pillar] = {
                "score": score,
                "signal": signal,
                "verdict": verdict,
                "magnitude": abs(score - 50),
            }
        return result

    # ------------------------------------------------------------------
    # Agent Accuracy
    # ------------------------------------------------------------------

    def compute_agent_accuracy(
        self,
        invest_debate: Dict[str, Any],
        risk_debate: Dict[str, Any],
        trader_text: str,
        return_pct: float,
    ) -> Dict[str, Dict[str, str]]:
        result: Dict[str, Dict[str, str]] = {}

        # Investment judge
        inv_judge_text = invest_debate.get("judge_decision", "")
        inv_decision = _extract_decision(inv_judge_text)
        result["investment_judge"] = {
            "decision": inv_decision,
            "verdict": _decision_verdict(inv_decision, return_pct),
        }

        # Risk judge
        risk_judge_text = risk_debate.get("judge_decision", "")
        risk_decision = _extract_decision(risk_judge_text)
        result["risk_judge"] = {
            "decision": risk_decision,
            "verdict": _decision_verdict(risk_decision, return_pct),
        }

        # Trader
        trader_decision = _extract_decision(trader_text)
        result["trader"] = {
            "decision": trader_decision,
            "verdict": _decision_verdict(trader_decision, return_pct),
        }

        # Bull / bear sides
        positive = return_pct > 0
        result["bull_side"] = {
            "verdict": "CORRECT" if positive else "INCORRECT",
        }
        result["bear_side"] = {
            "verdict": "INCORRECT" if positive else "CORRECT",
        }

        return result

    # ------------------------------------------------------------------
    # Counterfactual Scoring
    # ------------------------------------------------------------------

    def compute_counterfactual(
        self,
        breakdown: Dict[str, int],
        actual_regime: str,
    ) -> Dict[str, Any]:
        if not breakdown:
            return {}

        result: Dict[str, Any] = {}
        for regime_name, weights in REGIME_WEIGHTS.items():
            score = sum(
                breakdown.get(p, 50) * weights.get(p, 0.0) for p in _PILLARS
            )
            score = round(score, 2)
            actual_score = None
            if regime_name == actual_regime:
                actual_score = score

            result[regime_name] = {
                "score": score,
                "rating": _rating_from_score(score),
                "delta": 0.0,  # filled below
                "is_actual": regime_name == actual_regime,
            }

        # Compute actual score for delta calculation
        actual = result.get(actual_regime, {}).get("score")
        if actual is None:
            # Regime not in table — compute from weights
            w = get_weights(actual_regime)
            actual = round(
                sum(breakdown.get(p, 50) * w.get(p, 0.0) for p in _PILLARS), 2
            )

        for regime_name in result:
            result[regime_name]["delta"] = round(
                result[regime_name]["score"] - actual, 2
            )

        # Best regime for outcome and most protective
        scores = {r: v["score"] for r, v in result.items()}
        result["best_regime_for_outcome"] = max(scores, key=scores.get)  # type: ignore[arg-type]
        result["most_protective_regime"] = min(scores, key=scores.get)  # type: ignore[arg-type]

        return result

    # ------------------------------------------------------------------
    # Regime Accuracy Table
    # ------------------------------------------------------------------

    def build_regime_accuracy_table(
        self,
        attributions: List[Dict[str, Any]],
    ) -> Dict[str, Dict[str, Any]]:
        """Build regime x pillar accuracy matrix from all attributions.

        Returns:
            {regime: {pillar: {"right": N, "wrong": N, "neutral": N, "accuracy": float}, ...}}
        """
        table: Dict[str, Dict[str, Dict[str, int]]] = {}
        for attr in attributions:
            if not attr.get("report_found"):
                continue
            regime = attr.get("weight_regime", "NEUTRAL")
            if regime not in table:
                table[regime] = {p: {"right": 0, "wrong": 0, "neutral": 0} for p in _PILLARS}
            for pillar in _PILLARS:
                pa = attr.get("pillar_attribution", {}).get(pillar)
                if not pa:
                    continue
                verdict = pa.get("verdict", "NEUTRAL")
                if verdict == "RIGHT":
                    table[regime][pillar]["right"] += 1
                elif verdict == "WRONG":
                    table[regime][pillar]["wrong"] += 1
                else:
                    table[regime][pillar]["neutral"] += 1

        # Compute accuracy percentage
        result: Dict[str, Dict[str, Any]] = {}
        for regime, pillars in table.items():
            result[regime] = {}
            for pillar, counts in pillars.items():
                total = counts["right"] + counts["wrong"]
                accuracy = (counts["right"] / total * 100) if total > 0 else 0.0
                result[regime][pillar] = {
                    "right": counts["right"],
                    "wrong": counts["wrong"],
                    "neutral": counts["neutral"],
                    "accuracy": round(accuracy, 1),
                }
        return result

    # ------------------------------------------------------------------
    # Narrative
    # ------------------------------------------------------------------

    def generate_narrative(self, attr: Dict[str, Any]) -> str:
        """Generate human-readable post-mortem via string interpolation."""
        ticker = attr.get("ticker", "???")
        outcome = attr.get("outcome", "FLAT")
        return_pct = attr.get("return_pct", 0.0)
        pnl_usd = attr.get("pnl_usd", 0.0)
        entry_score = attr.get("entry_score", 0.0)
        entry_rating = attr.get("entry_rating", "N/A")
        regime = attr.get("weight_regime", "NEUTRAL")
        close_date = attr.get("close_date", "N/A")

        lines = [
            f"=== POST-MORTEM: {ticker} ({close_date}) ===",
            f"Outcome: {outcome} | Return: {return_pct:+.2f}% | PnL: ${pnl_usd:+,.2f}",
            f"Entry Score: {entry_score} ({entry_rating}) | Regime: {regime}",
        ]

        if not attr.get("report_found"):
            lines.append("No analysis report found — likely a Phase Engine trade.")
            return "\n".join(lines)

        # Pillar verdicts
        pa = attr.get("pillar_attribution", {})
        ps = attr.get("pillar_summary", {})
        lines.append("")
        lines.append(
            f"Pillar Verdicts: {ps.get('right_count', 0)}R / "
            f"{ps.get('wrong_count', 0)}W / {ps.get('neutral_count', 0)}N"
        )
        for pillar in _PILLARS:
            p = pa.get(pillar)
            if p:
                lines.append(
                    f"  {pillar:>12}: {p['score']:3d} ({p['signal']:>7}) -> {p['verdict']}"
                )

        # Agent verdicts
        aa = attr.get("agent_accuracy", {})
        if aa:
            lines.append("")
            lines.append("Agent Verdicts:")
            for agent_name in ("investment_judge", "risk_judge", "trader", "bull_side", "bear_side"):
                a = aa.get(agent_name)
                if a:
                    decision = a.get("decision", "")
                    verdict = a.get("verdict", "")
                    if decision:
                        lines.append(f"  {agent_name:>18}: {decision} -> {verdict}")
                    else:
                        lines.append(f"  {agent_name:>18}: {verdict}")

        # Counterfactual
        cf = attr.get("counterfactual", {})
        if cf:
            best = cf.get("best_regime_for_outcome", "")
            protective = cf.get("most_protective_regime", "")
            actual_entry = cf.get(regime, {})
            best_entry = cf.get(best, {})
            if best and best != regime and isinstance(best_entry, dict):
                lines.append("")
                lines.append(
                    f"Counterfactual: Under {best} regime, score would have been "
                    f"{best_entry.get('score', '?')} ({best_entry.get('rating', '?')}) "
                    f"vs actual {actual_entry.get('score', '?')} "
                    f"(delta {best_entry.get('delta', 0):+.2f})"
                )
            if protective and protective != regime:
                prot_entry = cf.get(protective, {})
                if isinstance(prot_entry, dict):
                    lines.append(
                        f"Most protective regime: {protective} "
                        f"(score {prot_entry.get('score', '?')})"
                    )

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal loaders
    # ------------------------------------------------------------------

    def _load_closed_trades(self) -> List[Dict[str, Any]]:
        if not self.closed_trades_path.exists():
            return []
        try:
            with open(self.closed_trades_path) as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
        except (json.JSONDecodeError, OSError):
            pass
        return []

    def _deduplicate(self, trades: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Deduplicate by (symbol, avg_entry_price, close_price), keep most recent."""
        seen: Dict[Tuple[str, float, float], Dict[str, Any]] = {}
        for t in trades:
            key = (
                t.get("symbol", ""),
                t.get("avg_entry_price", 0.0),
                t.get("close_price", 0.0),
            )
            existing = seen.get(key)
            if existing is None or t.get("closed_at", "") > existing.get("closed_at", ""):
                seen[key] = t
        return list(seen.values())

    def _load_analysis_report(self, trade: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Try to load analysis report for a trade via rating_id or scan."""
        ticker = trade.get("symbol", "")
        rating_ids = trade.get("rating_ids", [])

        # Try PHASE format: PHASE:YYYY-MM-DD:TICKER
        for rid in rating_ids:
            if rid.startswith("PHASE:"):
                parts = rid.split(":")
                if len(parts) >= 3:
                    date_str = parts[1]
                    report = self._read_report(ticker, date_str)
                    if report is not None:
                        return report

        # Try UUID — look up in track_record.json
        for rid in rating_ids:
            if not rid.startswith("PHASE:"):
                date_str = self._lookup_date_from_track_record(rid)
                if date_str:
                    report = self._read_report(ticker, date_str)
                    if report is not None:
                        return report

        # Fallback: scan results/{ticker}/*/ for most recent
        return self._scan_most_recent_report(ticker)

    def _read_report(self, ticker: str, date_str: str) -> Optional[Dict[str, Any]]:
        path = self.results_root / ticker / date_str / "analysis_report.json"
        if not path.exists():
            return None
        try:
            with open(path) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None

    def _lookup_date_from_track_record(self, rating_id: str) -> Optional[str]:
        if not self.track_record_path.exists():
            return None
        try:
            with open(self.track_record_path) as f:
                data = json.load(f)
            for t in data.get("trades", []):
                if t.get("rating_id") == rating_id:
                    return t.get("date")
        except (json.JSONDecodeError, OSError):
            pass
        return None

    def _scan_most_recent_report(self, ticker: str) -> Optional[Dict[str, Any]]:
        ticker_dir = self.results_root / ticker
        if not ticker_dir.is_dir():
            return None
        dates = sorted(
            [d.name for d in ticker_dir.iterdir() if d.is_dir()],
            reverse=True,
        )
        for date_str in dates:
            report = self._read_report(ticker, date_str)
            if report is not None:
                return report
        return None
