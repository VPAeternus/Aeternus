"""Agent Credibility Ledger.

Aggregates post-mortem attributions into per-agent, per-regime accuracy
scores and generates a credibility brief for injection into agent prompts.
Pure local Python — no external APIs, no LLM calls.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .post_mortem import PostMortemEngine


# Agents tracked in the ledger (must match post_mortem agent_accuracy keys)
_AGENTS = ("investment_judge", "risk_judge", "trader", "bull_side", "bear_side")

# Pillars tracked (must match post_mortem._PILLARS)
_PILLARS = ("fundamental", "coherence", "macro", "sentiment", "momentum")

# Minimum closed trades before producing a full brief
_MIN_TRADES = 5


class CredibilityLedger:
    """Aggregate post-mortem attributions into per-agent credibility scores."""

    def __init__(
        self,
        closed_trades_path: str = "eval_results/paper_execution/closed_trades.json",
        results_root: str = "results",
        track_record_path: str = "eval_results/track_record.json",
    ):
        self._engine = PostMortemEngine(
            results_root=results_root,
            closed_trades_path=closed_trades_path,
            track_record_path=track_record_path,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build(self) -> Dict[str, Any]:
        """Build the full credibility ledger from closed trades.

        Returns:
            {agents: {...}, pillars: {...}, patterns: [...], trade_count: N}
        """
        attributions = self._engine.analyze_all()
        # Only consider trades that had analysis reports
        with_reports = [a for a in attributions if a.get("report_found")]

        agent_scores = self._compute_agent_scores(with_reports)
        pillar_scores = self._compute_pillar_scores(with_reports)
        patterns = self._detect_patterns(agent_scores, pillar_scores)
        consensus_paradox = self._compute_consensus_paradox(with_reports)

        return {
            "agent_scores": agent_scores,
            "pillar_scores": pillar_scores,
            "patterns": patterns,
            "consensus_paradox": consensus_paradox,
            "trade_count": len(attributions),
            "trade_count_with_reports": len(with_reports),
        }

    def build_credibility_brief(self, regime: str = "NEUTRAL") -> str:
        """Build a formatted text block for prompt injection.

        Args:
            regime: Current market regime label (e.g. "BULL", "BEAR", "NEUTRAL").

        Returns:
            Multi-line string suitable for appending to portfolio context.
            Empty string if no attributions available.
        """
        ledger = self.build()
        trade_count = ledger["trade_count"]

        if trade_count == 0:
            return ""

        if trade_count < _MIN_TRADES:
            return f"=== AGENT CREDIBILITY ({trade_count} closed trades) ===\nInsufficient data ({trade_count} trades).\n=== END AGENT CREDIBILITY ==="

        agents = ledger["agent_scores"]
        pillars = ledger["pillar_scores"]
        patterns = ledger["patterns"]
        consensus = ledger.get("consensus_paradox", {})

        lines = [f"=== AGENT CREDIBILITY ({regime} regime, {trade_count} closed trades) ==="]
        lines.append("")
        lines.append("Agent Track Record:")

        for agent in _AGENTS:
            info = agents.get(agent)
            if not info:
                continue
            overall = info.get("overall", {})
            overall_acc = overall.get("accuracy", 0.5)
            overall_wins = overall.get("wins", 0)
            overall_total = overall.get("total", 0)

            # Trader HOLD special case: no directional decisions at all
            if agent == "trader" and overall_total == 0:
                lines.append("  Trader: mostly HOLD (no directional signal).")
                continue

            line = f"  {_agent_display_name(agent)}: {overall_acc:.0%} overall ({overall_wins}/{overall_total})."

            # Regime-specific
            regime_info = info.get("by_regime", {}).get(regime)
            if regime_info and regime_info.get("total", 0) > 0:
                r_acc = regime_info["accuracy"]
                r_wins = regime_info["wins"]
                r_total = regime_info["total"]
                line += f" In {regime}: {r_acc:.0%} ({r_wins}/{r_total})."

            lines.append(line)

        # Pillar reliability: prefer regime data, fall back to overall
        lines.append("")
        lines.append(f"Pillar Reliability in {regime}:")
        pillar_display: List[tuple] = []  # (sort_key, pillar, display_acc)
        for pillar in _PILLARS:
            p_info = pillars.get(pillar, {})
            regime_info = p_info.get("by_regime", {}).get(regime)
            if regime_info and regime_info.get("total", 0) > 0:
                pillar_display.append((regime_info["accuracy"], pillar, regime_info["accuracy"]))
            else:
                overall_p = p_info.get("overall", {})
                if overall_p.get("total", 0) > 0:
                    pillar_display.append((overall_p["accuracy"], pillar, overall_p["accuracy"]))

        if pillar_display:
            pillar_display.sort(key=lambda x: -x[0])
            for i, (_, pillar, acc) in enumerate(pillar_display):
                label = ""
                if len(pillar_display) >= 2:
                    if i == 0:
                        label = " (most reliable)"
                    elif i == len(pillar_display) - 1:
                        label = " (least reliable)"
                lines.append(f"  {pillar.title()}: {acc:.0%}{label}")
        else:
            lines.append(f"  No pillar data available.")

        # Consensus paradox (only show with ≥5 trades that have consensus data)
        consensus_total = sum(
            consensus.get(b, {}).get("total", 0)
            for b in ("unanimous", "strong", "split")
        )
        if consensus_total >= 5:
            lines.append("")
            lines.append("Consensus Analysis:")
            for bucket in ("unanimous", "strong", "split"):
                c = consensus.get(bucket, {})
                c_total = c.get("total", 0)
                if c_total > 0:
                    c_acc = c.get("accuracy", 0.5)
                    label = {
                        "unanimous": "Unanimous agreement",
                        "strong": "Strong consensus (1 dissenter)",
                        "split": "Split decisions (2+ dissenters)",
                    }[bucket]
                    lines.append(f"  {label}: {c_acc:.0%} win rate ({c_total} trades)")
            if consensus.get("paradox_detected"):
                lines.append(
                    "  WARNING: Dissent is signal — split-decision trades outperform consensus."
                )

        # Patterns
        if patterns:
            lines.append("")
            lines.append("PATTERNS:")
            for p in patterns:
                lines.append(f"  - {p}")

        lines.append("")
        lines.append("=== END AGENT CREDIBILITY ===")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Consensus Paradox
    # ------------------------------------------------------------------

    def _compute_consensus_paradox(
        self, attributions: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Compute win rate by agent agreement level.

        Buckets: unanimous (all agree), strong (1 dissenter), split (2+ dissenters).
        Returns paradox_detected=True if split accuracy > unanimous accuracy.
        """
        buckets: Dict[str, List[bool]] = {
            "unanimous": [],
            "strong": [],
            "split": [],
        }

        for attr in attributions:
            aa = attr.get("agent_accuracy", {})
            if not aa:
                continue

            # Count directional verdicts (CORRECT/INCORRECT only)
            directional = []
            for agent in _AGENTS:
                verdict = (aa.get(agent) or {}).get("verdict", "")
                if verdict in ("CORRECT", "INCORRECT"):
                    directional.append(verdict == "CORRECT")

            if len(directional) < 3:
                continue  # Need at least 3 directional agents

            # Agreement = count of majority direction
            correct_count = sum(directional)
            total = len(directional)
            majority = max(correct_count, total - correct_count)

            # Determine bucket
            dissenters = total - majority
            if dissenters == 0:
                bucket = "unanimous"
            elif dissenters == 1:
                bucket = "strong"
            else:
                bucket = "split"

            # Outcome is WIN if return > 0.5% (matching post_mortem threshold)
            ret = attr.get("return_pct", 0.0)
            is_win = ret > 0.5
            buckets[bucket].append(is_win)

        result: Dict[str, Any] = {}
        for bucket_name, outcomes in buckets.items():
            total = len(outcomes)
            wins = sum(outcomes)
            result[bucket_name] = {
                "wins": wins,
                "total": total,
                "accuracy": self._bayesian_accuracy(wins, total),
            }

        # Detect paradox: split outperforms unanimous
        unan_acc = result.get("unanimous", {}).get("accuracy", 0.5)
        split_acc = result.get("split", {}).get("accuracy", 0.5)
        unan_total = result.get("unanimous", {}).get("total", 0)
        split_total = result.get("split", {}).get("total", 0)
        result["paradox_detected"] = (
            split_acc > unan_acc
            and split_total >= 3
            and unan_total >= 3
        )

        return result

    # ------------------------------------------------------------------
    # Internal: Agent scoring
    # ------------------------------------------------------------------

    def _compute_agent_scores(
        self, attributions: List[Dict[str, Any]]
    ) -> Dict[str, Dict[str, Any]]:
        """Compute per-agent accuracy: overall, by regime, and by decision.

        Only directional verdicts count (CORRECT/INCORRECT).
        NEUTRAL verdicts (HOLD/UNKNOWN) are excluded.
        """
        result: Dict[str, Dict[str, Any]] = {}

        for agent in _AGENTS:
            wins_total: List[bool] = []
            by_regime: Dict[str, List[bool]] = {}
            by_decision: Dict[str, Dict[str, List[bool]]] = {}

            for attr in attributions:
                aa = attr.get("agent_accuracy", {}).get(agent)
                if not aa:
                    continue
                verdict = aa.get("verdict", "")
                if verdict not in ("CORRECT", "INCORRECT"):
                    continue

                is_win = verdict == "CORRECT"
                wins_total.append(is_win)

                regime = attr.get("weight_regime", "NEUTRAL")
                by_regime.setdefault(regime, []).append(is_win)

                decision = aa.get("decision", "UNKNOWN")
                if decision not in ("UNKNOWN", "HOLD"):
                    by_decision.setdefault(decision, {"overall": [], "by_regime": {}})
                    by_decision[decision]["overall"].append(is_win)
                    by_decision[decision]["by_regime"].setdefault(regime, []).append(is_win)

            result[agent] = {
                "overall": _summarize(wins_total, self._bayesian_accuracy),
                "by_regime": {
                    r: _summarize(outcomes, self._bayesian_accuracy)
                    for r, outcomes in by_regime.items()
                },
                "by_decision": {
                    d: {
                        "overall": _summarize(info["overall"], self._bayesian_accuracy),
                        "by_regime": {
                            r: _summarize(outcomes, self._bayesian_accuracy)
                            for r, outcomes in info["by_regime"].items()
                        },
                    }
                    for d, info in by_decision.items()
                },
            }

        return result

    # ------------------------------------------------------------------
    # Internal: Pillar scoring
    # ------------------------------------------------------------------

    def _compute_pillar_scores(
        self, attributions: List[Dict[str, Any]]
    ) -> Dict[str, Dict[str, Any]]:
        """Compute per-pillar accuracy: overall and by regime.

        Only RIGHT/WRONG verdicts count. NEUTRAL excluded.
        """
        result: Dict[str, Dict[str, Any]] = {}

        for pillar in _PILLARS:
            wins_total: List[bool] = []
            by_regime: Dict[str, List[bool]] = {}

            for attr in attributions:
                pa = attr.get("pillar_attribution", {}).get(pillar)
                if not pa:
                    continue
                verdict = pa.get("verdict", "")
                if verdict not in ("RIGHT", "WRONG"):
                    continue

                is_win = verdict == "RIGHT"
                wins_total.append(is_win)

                regime = attr.get("weight_regime", "NEUTRAL")
                by_regime.setdefault(regime, []).append(is_win)

            result[pillar] = {
                "overall": _summarize(wins_total, self._bayesian_accuracy),
                "by_regime": {
                    r: _summarize(outcomes, self._bayesian_accuracy)
                    for r, outcomes in by_regime.items()
                },
            }

        return result

    # ------------------------------------------------------------------
    # Internal: Pattern detection
    # ------------------------------------------------------------------

    def _detect_patterns(
        self,
        agent_scores: Dict[str, Dict[str, Any]],
        pillar_scores: Dict[str, Dict[str, Any]],
    ) -> List[str]:
        """Generate human-readable bias flags from scores."""
        patterns: List[str] = []

        # Investment judge: regime-specific underperformance
        ij_info = agent_scores.get("investment_judge", {})
        for regime, stats in ij_info.get("by_regime", {}).items():
            if stats.get("total", 0) >= 3 and stats.get("accuracy", 0.5) < 0.40:
                patterns.append(
                    f"Investment Judge shows bearish bias in {regime} regimes "
                    f"({stats['accuracy']:.0%} accuracy, {stats['total']} trades)"
                )

        # Risk judge: regime-specific underperformance
        rj_info = agent_scores.get("risk_judge", {})
        for regime, stats in rj_info.get("by_regime", {}).items():
            if stats.get("total", 0) >= 3 and stats.get("accuracy", 0.5) < 0.40:
                patterns.append(
                    f"Risk Judge underperforms in {regime} regimes "
                    f"({stats['accuracy']:.0%} accuracy, {stats['total']} trades)"
                )

        # Bear side consistently wrong in a regime
        bear_info = agent_scores.get("bear_side", {})
        for regime, stats in bear_info.get("by_regime", {}).items():
            if stats.get("total", 0) >= 3 and stats.get("accuracy", 0.5) < 0.35:
                wrong_count = stats["total"] - stats["wins"]
                patterns.append(
                    f"Bear side wrong {wrong_count}/{stats['total']} times in {regime}"
                    f" — discount heavily"
                )

        # Pillar unreliable overall
        for pillar in _PILLARS:
            overall = pillar_scores.get(pillar, {}).get("overall", {})
            if overall.get("total", 0) >= 5 and overall.get("accuracy", 0.5) < 0.40:
                patterns.append(
                    f"{pillar.title()} pillar unreliable overall "
                    f"({overall['accuracy']:.0%}, {overall['total']} trades)"
                )

        # Pillar highly reliable in a specific regime
        for pillar in _PILLARS:
            for regime, bucket in pillar_scores.get(pillar, {}).get("by_regime", {}).items():
                if bucket.get("total", 0) >= 3 and bucket.get("accuracy", 0.5) > 0.80:
                    patterns.append(
                        f"{pillar.title()} most reliable in {regime} "
                        f"({bucket['accuracy']:.0%})"
                    )

        return patterns

    # ------------------------------------------------------------------
    # Bayesian accuracy
    # ------------------------------------------------------------------

    @staticmethod
    def _bayesian_accuracy(wins: int, total: int) -> float:
        """Beta-Binomial posterior mean with Beta(2,2) prior.

        - 0 trades → 0.50 (neutral)
        - 1/1     → 0.60 (conservative up)
        - 0/1     → 0.40 (conservative down)
        """
        return (wins + 2) / (total + 4)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _agent_display_name(agent: str) -> str:
    """Convert agent key to display name."""
    names = {
        "investment_judge": "Investment Judge",
        "risk_judge": "Risk Judge",
        "trader": "Trader",
        "bull_side": "Bull side",
        "bear_side": "Bear side",
    }
    return names.get(agent, agent)


def _summarize(
    outcomes: List[bool],
    bayesian_fn,
) -> Dict[str, Any]:
    """Summarize a list of win/loss booleans into accuracy stats."""
    total = len(outcomes)
    wins = sum(outcomes)
    return {
        "wins": wins,
        "losses": total - wins,
        "total": total,
        "accuracy": bayesian_fn(wins, total),
    }
