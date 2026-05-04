"""Tests for tradingagents.graph.equity_curve."""

import json
import math
from pathlib import Path

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _write_closed_trades(tmp_path, trades):
    path = tmp_path / "closed_trades.json"
    path.write_text(json.dumps(trades))
    return str(path)


def _write_positions(tmp_path, positions_dict):
    path = tmp_path / "positions.json"
    path.write_text(json.dumps({"open_positions": positions_dict}))
    return str(path)


def _sample_trades():
    return [
        {"close_date": "2026-01-15", "pnl_usd": 500.0, "return_pct": 5.0},
        {"close_date": "2026-01-20", "pnl_usd": -200.0, "return_pct": -2.0},
        {"close_date": "2026-02-01", "pnl_usd": 800.0, "return_pct": 8.0},
        {"close_date": "2026-02-10", "pnl_usd": 300.0, "return_pct": 3.0},
        {"close_date": "2026-02-15", "pnl_usd": -100.0, "return_pct": -1.0},
    ]


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestEquityCurveEngine:
    def test_no_closed_trades(self, tmp_path):
        from tradingagents.graph.equity_curve import EquityCurveEngine
        trades_path = _write_closed_trades(tmp_path, [])
        positions_path = _write_positions(tmp_path, {})
        engine = EquityCurveEngine(
            initial_capital=200_000,
            closed_trades_path=trades_path,
            positions_path=positions_path,
        )
        result = engine.build()
        assert result["initial_capital"] == 200_000
        assert result["current_nav"] == 200_000
        assert result["realized_pnl"] == 0
        assert result["stats"]["trade_count"] == 0
        assert result["stats"]["win_rate"] == 0.0

    def test_single_winning_trade(self, tmp_path):
        from tradingagents.graph.equity_curve import EquityCurveEngine
        trades = [{"close_date": "2026-01-15", "pnl_usd": 1000.0, "return_pct": 5.0}]
        trades_path = _write_closed_trades(tmp_path, trades)
        positions_path = _write_positions(tmp_path, {})
        engine = EquityCurveEngine(
            initial_capital=200_000,
            closed_trades_path=trades_path,
            positions_path=positions_path,
        )
        result = engine.build()
        assert result["realized_pnl"] == 1000.0
        assert result["current_nav"] == 201_000.0
        assert result["stats"]["win_rate"] == 1.0
        assert result["stats"]["profit_factor"] == 99.9  # All wins capped
        assert result["stats"]["sharpe_ratio"] == "N/A"  # Single point, no std

    def test_multiple_trades_stats(self, tmp_path):
        from tradingagents.graph.equity_curve import EquityCurveEngine
        trades = _sample_trades()
        trades_path = _write_closed_trades(tmp_path, trades)
        positions_path = _write_positions(tmp_path, {})
        engine = EquityCurveEngine(
            initial_capital=200_000,
            closed_trades_path=trades_path,
            positions_path=positions_path,
        )
        result = engine.build()
        stats = result["stats"]
        assert stats["trade_count"] == 5
        assert stats["win_rate"] == pytest.approx(0.6, abs=0.01)  # 3 wins, 2 losses
        assert stats["avg_win_pct"] == pytest.approx(5.33, abs=0.1)
        assert stats["avg_loss_pct"] == pytest.approx(-1.5, abs=0.1)
        assert result["realized_pnl"] == 1300.0
        assert result["current_nav"] == 201_300.0

    def test_nav_series_dates(self, tmp_path):
        from tradingagents.graph.equity_curve import EquityCurveEngine
        trades = _sample_trades()
        trades_path = _write_closed_trades(tmp_path, trades)
        positions_path = _write_positions(tmp_path, {})
        engine = EquityCurveEngine(
            initial_capital=200_000,
            closed_trades_path=trades_path,
            positions_path=positions_path,
        )
        result = engine.build()
        nav_dates = [pt["date"] for pt in result["nav_series"]]
        assert nav_dates == sorted(nav_dates)  # Sorted
        assert len(nav_dates) == 5

    def test_nav_series_values_accumulate(self, tmp_path):
        from tradingagents.graph.equity_curve import EquityCurveEngine
        trades = [
            {"close_date": "2026-01-10", "pnl_usd": 100.0, "return_pct": 1.0},
            {"close_date": "2026-01-20", "pnl_usd": 200.0, "return_pct": 2.0},
        ]
        trades_path = _write_closed_trades(tmp_path, trades)
        positions_path = _write_positions(tmp_path, {})
        engine = EquityCurveEngine(
            initial_capital=10_000,
            closed_trades_path=trades_path,
            positions_path=positions_path,
        )
        result = engine.build()
        assert result["nav_series"][0]["nav"] == 10_100.0
        assert result["nav_series"][1]["nav"] == 10_300.0

    def test_unrealized_pnl_from_open_positions(self, tmp_path):
        from tradingagents.graph.equity_curve import EquityCurveEngine
        trades_path = _write_closed_trades(tmp_path, [])
        positions = {
            "AAPL": {
                "net_quantity": 100,
                "avg_price": 170.0,
                "last_mark_price": 180.0,
            }
        }
        positions_path = _write_positions(tmp_path, positions)
        engine = EquityCurveEngine(
            initial_capital=200_000,
            closed_trades_path=trades_path,
            positions_path=positions_path,
        )
        result = engine.build(include_open_mtm=True)
        assert result["unrealized_pnl"] == 1000.0  # 100 * (180-170)
        assert result["current_nav"] == 201_000.0

    def test_exclude_open_mtm(self, tmp_path):
        from tradingagents.graph.equity_curve import EquityCurveEngine
        trades_path = _write_closed_trades(tmp_path, [])
        positions = {
            "AAPL": {"net_quantity": 100, "avg_price": 170.0, "last_mark_price": 180.0}
        }
        positions_path = _write_positions(tmp_path, positions)
        engine = EquityCurveEngine(
            initial_capital=200_000,
            closed_trades_path=trades_path,
            positions_path=positions_path,
        )
        result = engine.build(include_open_mtm=False)
        assert result["unrealized_pnl"] == 0.0
        assert result["current_nav"] == 200_000.0

    def test_monthly_returns(self, tmp_path):
        from tradingagents.graph.equity_curve import EquityCurveEngine
        trades = _sample_trades()
        trades_path = _write_closed_trades(tmp_path, trades)
        positions_path = _write_positions(tmp_path, {})
        engine = EquityCurveEngine(
            initial_capital=200_000,
            closed_trades_path=trades_path,
            positions_path=positions_path,
        )
        result = engine.build()
        monthly = result["monthly_returns"]
        assert "2026-01" in monthly
        assert "2026-02" in monthly

    def test_profit_factor_all_wins(self, tmp_path):
        from tradingagents.graph.equity_curve import EquityCurveEngine
        trades = [
            {"close_date": "2026-01-10", "pnl_usd": 100.0, "return_pct": 1.0},
            {"close_date": "2026-01-20", "pnl_usd": 200.0, "return_pct": 2.0},
        ]
        trades_path = _write_closed_trades(tmp_path, trades)
        positions_path = _write_positions(tmp_path, {})
        engine = EquityCurveEngine(
            initial_capital=10_000,
            closed_trades_path=trades_path,
            positions_path=positions_path,
        )
        result = engine.build()
        assert result["stats"]["profit_factor"] == 99.9  # Capped

    def test_max_drawdown(self, tmp_path):
        """Drawdown after a loss should be tracked."""
        from tradingagents.graph.equity_curve import EquityCurveEngine
        trades = [
            {"close_date": "2026-01-10", "pnl_usd": 1000.0, "return_pct": 10.0},
            {"close_date": "2026-01-20", "pnl_usd": -500.0, "return_pct": -5.0},
            {"close_date": "2026-01-30", "pnl_usd": 200.0, "return_pct": 2.0},
        ]
        trades_path = _write_closed_trades(tmp_path, trades)
        positions_path = _write_positions(tmp_path, {})
        engine = EquityCurveEngine(
            initial_capital=10_000,
            closed_trades_path=trades_path,
            positions_path=positions_path,
        )
        result = engine.build()
        assert result["stats"]["max_drawdown_pct"] > 0

    def test_short_position_unrealized(self, tmp_path):
        from tradingagents.graph.equity_curve import EquityCurveEngine
        trades_path = _write_closed_trades(tmp_path, [])
        positions = {
            "SPY": {
                "net_quantity": -100,
                "avg_price": 500.0,
                "last_mark_price": 490.0,
            }
        }
        positions_path = _write_positions(tmp_path, positions)
        engine = EquityCurveEngine(
            initial_capital=200_000,
            closed_trades_path=trades_path,
            positions_path=positions_path,
        )
        result = engine.build()
        # Short: profit when price drops
        assert result["unrealized_pnl"] == 1000.0  # 100 * (500-490) * -1 * -1


class TestBuildEquityBrief:
    def test_no_trades_brief(self, tmp_path):
        from tradingagents.graph.equity_curve import EquityCurveEngine
        trades_path = _write_closed_trades(tmp_path, [])
        positions_path = _write_positions(tmp_path, {})
        engine = EquityCurveEngine(
            closed_trades_path=trades_path,
            positions_path=positions_path,
        )
        brief = engine.build_equity_brief()
        assert "No closed trades" in brief

    def test_brief_has_key_stats(self, tmp_path):
        from tradingagents.graph.equity_curve import EquityCurveEngine
        trades = _sample_trades()
        trades_path = _write_closed_trades(tmp_path, trades)
        positions_path = _write_positions(tmp_path, {})
        engine = EquityCurveEngine(
            initial_capital=200_000,
            closed_trades_path=trades_path,
            positions_path=positions_path,
        )
        brief = engine.build_equity_brief()
        assert "EQUITY CURVE" in brief
        assert "NAV" in brief
        assert "Win rate" in brief
        assert "Profit factor" in brief
