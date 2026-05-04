"""Tests for tradingagents.graph.impl_shortfall."""

import json
from pathlib import Path

import pytest


def _write_orders(tmp_path, orders):
    path = tmp_path / "orders.json"
    path.write_text(json.dumps(orders))
    return str(path)


class TestComputeImplShortfall:
    def test_empty_orders(self, tmp_path):
        from tradingagents.graph.impl_shortfall import compute_impl_shortfall
        path = _write_orders(tmp_path, [])
        result = compute_impl_shortfall(orders_path=path)
        assert result["order_count"] == 0
        assert result["mean_slippage_bps"] == 0.0

    def test_no_reference_price_skipped(self, tmp_path):
        from tradingagents.graph.impl_shortfall import compute_impl_shortfall
        orders = [
            {"status": "FILLED", "filled_price": 100.0, "side": "BUY", "symbol": "AAPL"},
        ]
        path = _write_orders(tmp_path, orders)
        result = compute_impl_shortfall(orders_path=path)
        assert result["order_count"] == 0

    def test_buy_positive_slippage(self, tmp_path):
        """Buying at a higher price = adverse slippage (positive)."""
        from tradingagents.graph.impl_shortfall import compute_impl_shortfall
        orders = [{
            "status": "FILLED",
            "reference_price": 100.0,
            "filled_price": 100.10,
            "side": "BUY",
            "symbol": "AAPL",
            "date": "2026-03-01",
            "lane": "CORE",
        }]
        path = _write_orders(tmp_path, orders)
        result = compute_impl_shortfall(orders_path=path)
        assert result["order_count"] == 1
        assert result["mean_slippage_bps"] == pytest.approx(10.0, abs=0.1)

    def test_buy_negative_slippage(self, tmp_path):
        """Buying at a lower price = favorable slippage (negative)."""
        from tradingagents.graph.impl_shortfall import compute_impl_shortfall
        orders = [{
            "status": "FILLED",
            "reference_price": 100.0,
            "filled_price": 99.95,
            "side": "BUY",
            "symbol": "AAPL",
            "date": "2026-03-01",
            "lane": "CORE",
        }]
        path = _write_orders(tmp_path, orders)
        result = compute_impl_shortfall(orders_path=path)
        assert result["mean_slippage_bps"] < 0  # Favorable

    def test_sell_adverse_slippage(self, tmp_path):
        """Selling at a lower price = adverse slippage (positive)."""
        from tradingagents.graph.impl_shortfall import compute_impl_shortfall
        orders = [{
            "status": "FILLED",
            "reference_price": 100.0,
            "filled_price": 99.90,
            "side": "SELL",
            "symbol": "AAPL",
            "date": "2026-03-01",
            "lane": "CORE",
        }]
        path = _write_orders(tmp_path, orders)
        result = compute_impl_shortfall(orders_path=path)
        assert result["mean_slippage_bps"] == pytest.approx(10.0, abs=0.1)

    def test_sell_favorable_slippage(self, tmp_path):
        """Selling at a higher price = favorable slippage (negative)."""
        from tradingagents.graph.impl_shortfall import compute_impl_shortfall
        orders = [{
            "status": "FILLED",
            "reference_price": 100.0,
            "filled_price": 100.05,
            "side": "SELL",
            "symbol": "AAPL",
            "date": "2026-03-01",
            "lane": "CORE",
        }]
        path = _write_orders(tmp_path, orders)
        result = compute_impl_shortfall(orders_path=path)
        assert result["mean_slippage_bps"] < 0  # Favorable

    def test_multiple_orders_stats(self, tmp_path):
        from tradingagents.graph.impl_shortfall import compute_impl_shortfall
        orders = [
            {"status": "FILLED", "reference_price": 100.0, "filled_price": 100.05,
             "side": "BUY", "symbol": "AAPL", "date": "2026-03-01", "lane": "CORE"},
            {"status": "FILLED", "reference_price": 200.0, "filled_price": 199.90,
             "side": "BUY", "symbol": "MSFT", "date": "2026-03-01", "lane": "CORE"},
            {"status": "FILLED", "reference_price": 50.0, "filled_price": 49.95,
             "side": "SELL", "symbol": "XOM", "date": "2026-03-01", "lane": "MOMENTUM"},
        ]
        path = _write_orders(tmp_path, orders)
        result = compute_impl_shortfall(orders_path=path)
        assert result["order_count"] == 3
        assert result["std_slippage_bps"] > 0
        assert "BUY" in result["by_side"]
        assert "SELL" in result["by_side"]
        assert "CORE" in result["by_lane"]
        assert "MOMENTUM" in result["by_lane"]

    def test_worst_slippage(self, tmp_path):
        from tradingagents.graph.impl_shortfall import compute_impl_shortfall
        orders = [
            {"status": "FILLED", "reference_price": 100.0, "filled_price": 100.01,
             "side": "BUY", "symbol": "AAPL", "date": "2026-03-01", "lane": "CORE"},
            {"status": "FILLED", "reference_price": 100.0, "filled_price": 101.0,
             "side": "BUY", "symbol": "BAD", "date": "2026-03-01", "lane": "CORE"},
        ]
        path = _write_orders(tmp_path, orders)
        result = compute_impl_shortfall(orders_path=path)
        assert result["worst_slippage"]["symbol"] == "BAD"
        assert result["worst_slippage"]["slippage_bps"] == pytest.approx(100.0, abs=0.1)

    def test_unfilled_orders_skipped(self, tmp_path):
        from tradingagents.graph.impl_shortfall import compute_impl_shortfall
        orders = [
            {"status": "PENDING", "reference_price": 100.0, "filled_price": 100.05,
             "side": "BUY", "symbol": "AAPL"},
            {"status": "FILLED", "reference_price": 100.0, "filled_price": 100.05,
             "side": "BUY", "symbol": "MSFT", "date": "2026-03-01", "lane": "CORE"},
        ]
        path = _write_orders(tmp_path, orders)
        result = compute_impl_shortfall(orders_path=path)
        assert result["order_count"] == 1

    def test_cumulative_drag(self, tmp_path):
        from tradingagents.graph.impl_shortfall import compute_impl_shortfall
        orders = [
            {"status": "FILLED", "reference_price": 100.0, "filled_price": 100.10,
             "side": "BUY", "symbol": "A", "date": "2026-03-01", "lane": "CORE"},
            {"status": "FILLED", "reference_price": 100.0, "filled_price": 100.20,
             "side": "BUY", "symbol": "B", "date": "2026-03-01", "lane": "CORE"},
        ]
        path = _write_orders(tmp_path, orders)
        result = compute_impl_shortfall(orders_path=path)
        # 10 + 20 = 30 bps cumulative
        assert result["cumulative_drag_bps"] == pytest.approx(30.0, abs=0.1)


class TestBuildShortfallBrief:
    def test_empty_returns_empty(self, tmp_path):
        from tradingagents.graph.impl_shortfall import build_shortfall_brief
        path = _write_orders(tmp_path, [])
        assert build_shortfall_brief(orders_path=path) == ""

    def test_brief_has_content(self, tmp_path):
        from tradingagents.graph.impl_shortfall import build_shortfall_brief
        orders = [
            {"status": "FILLED", "reference_price": 100.0, "filled_price": 100.10,
             "side": "BUY", "symbol": "AAPL", "date": "2026-03-01", "lane": "CORE"},
        ]
        path = _write_orders(tmp_path, orders)
        brief = build_shortfall_brief(orders_path=path)
        assert "IMPLEMENTATION SHORTFALL" in brief
        assert "bps" in brief
