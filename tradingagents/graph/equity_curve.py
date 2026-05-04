"""Equity curve engine — NAV tracking and portfolio statistics.

Builds a daily NAV series from closed trades and open positions,
computes Sharpe, Sortino, max drawdown, Calmar, profit factor.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


def _load_json(path: str, default: Any = None) -> Any:
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return default if default is not None else {}


class EquityCurveEngine:
    """Build NAV series and compute portfolio statistics from trade history."""

    def __init__(
        self,
        initial_capital: float = 200_000.0,
        closed_trades_path: str = "eval_results/paper_execution/closed_trades.json",
        positions_path: str = "eval_results/paper_execution/positions.json",
    ):
        self.initial_capital = initial_capital
        self.closed_trades_path = closed_trades_path
        self.positions_path = positions_path

    def build(self, include_open_mtm: bool = True) -> Dict[str, Any]:
        """Build NAV series and compute stats.

        Returns dict with: initial_capital, current_nav, realized_pnl,
        unrealized_pnl, nav_series, stats, monthly_returns.
        """
        closed_trades = _load_json(self.closed_trades_path, [])
        if not isinstance(closed_trades, list):
            closed_trades = []

        # Sort by close_date
        trades_with_date = []
        for t in closed_trades:
            if not isinstance(t, dict):
                continue
            close_date = t.get("close_date", "")
            if not close_date:
                continue
            trades_with_date.append(t)

        trades_with_date.sort(key=lambda t: t.get("close_date", ""))

        # Build daily NAV series from cumulative realized PnL
        realized_pnl = 0.0
        nav_series: List[Dict[str, Any]] = []
        winning_pnl = 0.0
        losing_pnl = 0.0
        wins = 0
        losses = 0
        win_returns: List[float] = []
        loss_returns: List[float] = []
        daily_pnl_by_date: Dict[str, float] = defaultdict(float)

        for trade in trades_with_date:
            pnl = float(trade.get("pnl_usd", 0.0) or 0.0)
            ret_pct = float(trade.get("return_pct", 0.0) or 0.0)
            close_date = trade["close_date"]

            realized_pnl += pnl
            daily_pnl_by_date[close_date] += pnl

            if pnl > 0:
                winning_pnl += pnl
                wins += 1
                win_returns.append(ret_pct)
            elif pnl < 0:
                losing_pnl += abs(pnl)
                losses += 1
                loss_returns.append(ret_pct)

        # Build NAV series from date-sorted PnL
        cumulative = self.initial_capital
        for date_str in sorted(daily_pnl_by_date.keys()):
            cumulative += daily_pnl_by_date[date_str]
            nav_series.append({"date": date_str, "nav": round(cumulative, 2)})

        # Unrealized PnL from open positions
        unrealized_pnl = 0.0
        if include_open_mtm:
            positions_data = _load_json(self.positions_path, {})
            open_positions = (
                positions_data.get("open_positions", {})
                if isinstance(positions_data, dict)
                else {}
            )
            for symbol, pos in open_positions.items():
                if not isinstance(pos, dict):
                    continue
                net_qty = float(pos.get("net_quantity", 0) or 0)
                avg_price = float(pos.get("avg_price", 0) or 0)
                mark_price = float(pos.get("last_mark_price", 0) or 0)
                if avg_price > 0 and mark_price > 0 and net_qty != 0:
                    side = 1.0 if net_qty > 0 else -1.0
                    unrealized_pnl += abs(net_qty) * (mark_price - avg_price) * side

        current_nav = self.initial_capital + realized_pnl + unrealized_pnl
        trade_count = wins + losses

        # Compute stats
        stats = self._compute_stats(
            nav_series=nav_series,
            wins=wins,
            losses=losses,
            win_returns=win_returns,
            loss_returns=loss_returns,
            winning_pnl=winning_pnl,
            losing_pnl=losing_pnl,
            trade_count=trade_count,
            current_nav=current_nav,
        )

        # Monthly returns
        monthly_returns = self._compute_monthly_returns(nav_series)

        return {
            "initial_capital": self.initial_capital,
            "current_nav": round(current_nav, 2),
            "realized_pnl": round(realized_pnl, 2),
            "unrealized_pnl": round(unrealized_pnl, 2),
            "nav_series": nav_series,
            "stats": stats,
            "monthly_returns": monthly_returns,
        }

    def _compute_stats(
        self,
        nav_series: List[Dict[str, Any]],
        wins: int,
        losses: int,
        win_returns: List[float],
        loss_returns: List[float],
        winning_pnl: float,
        losing_pnl: float,
        trade_count: int,
        current_nav: float,
    ) -> Dict[str, Any]:
        """Compute portfolio statistics from NAV series."""
        win_rate = wins / trade_count if trade_count > 0 else 0.0
        avg_win_pct = sum(win_returns) / len(win_returns) if win_returns else 0.0
        avg_loss_pct = sum(loss_returns) / len(loss_returns) if loss_returns else 0.0
        profit_factor = (
            min(winning_pnl / losing_pnl, 99.9)
            if losing_pnl > 0
            else (99.9 if winning_pnl > 0 else 0.0)
        )

        total_return_pct = (
            (current_nav - self.initial_capital) / self.initial_capital * 100.0
        )

        # Daily returns from NAV series for Sharpe/Sortino/MaxDD
        if len(nav_series) < 2:
            return {
                "total_return_pct": round(total_return_pct, 2),
                "sharpe_ratio": "N/A",
                "sortino_ratio": "N/A",
                "max_drawdown_pct": 0.0,
                "max_drawdown_date": "",
                "calmar_ratio": "N/A",
                "win_rate": round(win_rate, 4),
                "avg_win_pct": round(avg_win_pct, 2),
                "avg_loss_pct": round(avg_loss_pct, 2),
                "profit_factor": round(profit_factor, 2),
                "trade_count": trade_count,
            }

        navs = [self.initial_capital] + [pt["nav"] for pt in nav_series]
        daily_returns = [(navs[i] - navs[i - 1]) / navs[i - 1] for i in range(1, len(navs)) if navs[i - 1] != 0]

        if not daily_returns:
            return {
                "total_return_pct": round(total_return_pct, 2),
                "sharpe_ratio": "N/A",
                "sortino_ratio": "N/A",
                "max_drawdown_pct": 0.0,
                "max_drawdown_date": "",
                "calmar_ratio": "N/A",
                "win_rate": round(win_rate, 4),
                "avg_win_pct": round(avg_win_pct, 2),
                "avg_loss_pct": round(avg_loss_pct, 2),
                "profit_factor": round(profit_factor, 2),
                "trade_count": trade_count,
            }

        mean_ret = sum(daily_returns) / len(daily_returns)
        std_ret = (sum((r - mean_ret) ** 2 for r in daily_returns) / len(daily_returns)) ** 0.5

        # Sharpe
        sharpe = (mean_ret / std_ret * math.sqrt(252)) if std_ret > 0 else "N/A"

        # Sortino (downside deviation)
        neg_returns = [r for r in daily_returns if r < 0]
        if neg_returns:
            downside_std = (sum(r ** 2 for r in neg_returns) / len(neg_returns)) ** 0.5
            sortino = (mean_ret / downside_std * math.sqrt(252)) if downside_std > 0 else "N/A"
        else:
            sortino = "N/A"

        # Max drawdown
        running_max = navs[0]
        max_dd = 0.0
        max_dd_date = ""
        for i, nav_val in enumerate(navs):
            running_max = max(running_max, nav_val)
            dd = (1 - nav_val / running_max) * 100.0 if running_max > 0 else 0.0
            if dd > max_dd:
                max_dd = dd
                if i > 0 and i - 1 < len(nav_series):
                    max_dd_date = nav_series[i - 1]["date"]

        # Calmar = annualized return / max drawdown
        days = len(daily_returns)
        ann_return = ((navs[-1] / navs[0]) ** (252 / days) - 1) * 100.0 if days > 0 and navs[0] > 0 else 0.0
        calmar = round(ann_return / max_dd, 2) if max_dd > 0 else "N/A"

        return {
            "total_return_pct": round(total_return_pct, 2),
            "sharpe_ratio": round(sharpe, 2) if isinstance(sharpe, float) else sharpe,
            "sortino_ratio": round(sortino, 2) if isinstance(sortino, float) else sortino,
            "max_drawdown_pct": round(max_dd, 2),
            "max_drawdown_date": max_dd_date,
            "calmar_ratio": calmar,
            "win_rate": round(win_rate, 4),
            "avg_win_pct": round(avg_win_pct, 2),
            "avg_loss_pct": round(avg_loss_pct, 2),
            "profit_factor": round(profit_factor, 2),
            "trade_count": trade_count,
        }

    def _compute_monthly_returns(
        self, nav_series: List[Dict[str, Any]]
    ) -> Dict[str, float]:
        """Compute monthly return percentages from NAV series."""
        if not nav_series:
            return {}

        # Group by YYYY-MM, take last NAV per month
        monthly_nav: Dict[str, float] = {}
        for pt in nav_series:
            month_key = pt["date"][:7]  # YYYY-MM
            monthly_nav[month_key] = pt["nav"]

        months = sorted(monthly_nav.keys())
        if not months:
            return {}

        result: Dict[str, float] = {}
        prev_nav = self.initial_capital
        for m in months:
            nav = monthly_nav[m]
            ret_pct = ((nav - prev_nav) / prev_nav * 100.0) if prev_nav > 0 else 0.0
            result[m] = round(ret_pct, 2)
            prev_nav = nav

        return result

    def build_equity_brief(self) -> str:
        """Build formatted equity brief for display or injection."""
        data = self.build()
        stats = data["stats"]

        if stats["trade_count"] == 0:
            return "Equity Curve: No closed trades."

        lines = ["=== EQUITY CURVE ==="]
        lines.append(
            f"NAV: ${data['current_nav']:,.0f} "
            f"(initial ${data['initial_capital']:,.0f})"
        )
        lines.append(
            f"Realized P&L: ${data['realized_pnl']:+,.0f} | "
            f"Unrealized: ${data['unrealized_pnl']:+,.0f}"
        )
        lines.append(
            f"Total return: {stats['total_return_pct']:+.2f}% | "
            f"Win rate: {stats['win_rate']:.0%} ({stats['trade_count']} trades)"
        )

        sharpe = stats["sharpe_ratio"]
        sortino = stats["sortino_ratio"]
        calmar = stats["calmar_ratio"]
        lines.append(
            f"Sharpe: {sharpe} | Sortino: {sortino} | "
            f"Calmar: {calmar}"
        )
        lines.append(
            f"Max DD: {stats['max_drawdown_pct']:.1f}% "
            f"({stats['max_drawdown_date'] or 'N/A'})"
        )
        lines.append(
            f"Profit factor: {stats['profit_factor']:.2f} | "
            f"Avg win: {stats['avg_win_pct']:+.2f}% | "
            f"Avg loss: {stats['avg_loss_pct']:+.2f}%"
        )

        return "\n".join(lines)
