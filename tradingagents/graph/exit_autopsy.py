"""Exit Autopsy Ledger.

Reads closed_trades.json, aggregates win/loss by exit_rule, and builds a
formatted brief for display or prompt injection.
Pure local Python — no external APIs, no LLM calls.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List


class ExitAutopsyLedger:
    """Aggregate closed trade outcomes by exit rule."""

    def __init__(
        self,
        closed_trades_path: str = "eval_results/paper_execution/closed_trades.json",
    ):
        self._path = Path(closed_trades_path)

    def build(self) -> Dict[str, Any]:
        """Build autopsy data grouped by exit_rule.

        Returns:
            {by_exit_rule: {rule: {wins, losses, total, accuracy, avg_return}},
             trade_count: N}
        """
        trades = self._load_trades()
        by_rule: Dict[str, Dict[str, Any]] = {}

        for trade in trades:
            rule = str(trade.get("exit_rule") or "UNKNOWN").upper().strip()
            if not rule:
                rule = "UNKNOWN"

            if rule not in by_rule:
                by_rule[rule] = {
                    "wins": 0,
                    "losses": 0,
                    "total": 0,
                    "returns": [],
                }

            ret = float(trade.get("return_pct", 0) or 0)
            pnl = float(trade.get("pnl_usd", 0) or 0)
            is_win = ret > 0.5  # same threshold as post_mortem

            by_rule[rule]["total"] += 1
            if is_win:
                by_rule[rule]["wins"] += 1
            else:
                by_rule[rule]["losses"] += 1
            by_rule[rule]["returns"].append(ret)

        # Compute accuracy and avg_return per rule
        result: Dict[str, Any] = {}
        for rule, data in by_rule.items():
            returns = data.pop("returns")
            data["accuracy"] = self._bayesian_accuracy(data["wins"], data["total"])
            data["avg_return"] = sum(returns) / len(returns) if returns else 0.0
            result[rule] = data

        return {
            "by_exit_rule": result,
            "trade_count": len(trades),
        }

    def build_autopsy_brief(self) -> str:
        """Build a formatted text summary for display or prompt injection."""
        data = self.build()
        trade_count = data["trade_count"]

        if trade_count == 0:
            return ""

        by_rule = data["by_exit_rule"]
        lines = [f"=== EXIT AUTOPSY ({trade_count} closed trades) ==="]
        lines.append("")

        # Sort by total trades descending
        sorted_rules = sorted(by_rule.items(), key=lambda x: -x[1]["total"])

        for rule, stats in sorted_rules:
            acc = stats["accuracy"]
            avg_ret = stats["avg_return"]
            total = stats["total"]
            wins = stats["wins"]
            losses = stats["losses"]

            color_hint = "good" if acc >= 0.55 else "poor" if acc < 0.45 else "neutral"
            lines.append(
                f"  {rule}: {acc:.0%} accuracy ({wins}W/{losses}L, {total} trades), "
                f"avg return {avg_ret:+.2f}%"
            )

        # Flag best and worst rules (need ≥3 trades)
        qualified = [(r, s) for r, s in sorted_rules if s["total"] >= 3]
        if len(qualified) >= 2:
            best = max(qualified, key=lambda x: x[1]["accuracy"])
            worst = min(qualified, key=lambda x: x[1]["accuracy"])
            if best[1]["accuracy"] > worst[1]["accuracy"]:
                lines.append("")
                lines.append(f"Best exit rule: {best[0]} ({best[1]['accuracy']:.0%})")
                lines.append(f"Worst exit rule: {worst[0]} ({worst[1]['accuracy']:.0%})")

        lines.append("")
        lines.append("=== END EXIT AUTOPSY ===")
        return "\n".join(lines)

    @staticmethod
    def _bayesian_accuracy(wins: int, total: int) -> float:
        """Beta-Binomial posterior mean with Beta(2,2) prior."""
        return (wins + 2) / (total + 4)

    def _load_trades(self) -> List[Dict[str, Any]]:
        if not self._path.exists():
            return []
        try:
            data = json.loads(self._path.read_text())
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError):
            return []
