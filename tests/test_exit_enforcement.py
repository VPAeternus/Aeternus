"""Tests for exit enforcement: thesis invalidation and conviction decay."""
import json
import uuid
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock
from tradingagents.graph.paper_execution import (
    build_exit_execution_plan,
    _apply_fill_to_position,
)


def _make_positions_file(tmp_path, positions_dict):
    """Write a positions.json file and return the path."""
    data = {"open_positions": positions_dict, "closed_positions": {}}
    path = tmp_path / "positions.json"
    path.write_text(json.dumps(data))
    return str(path)


def _make_outbox_file(tmp_path):
    """Write an empty outbox file and return the path."""
    path = tmp_path / "outbox.json"
    path.write_text("[]")
    return str(path)


def _make_position(
    symbol="AAPL",
    net_quantity=10,
    avg_price=150.0,
    mark_price=160.0,
    hold_days=5,
    invalidation_conditions=None,
    original_conviction=0,
    playbook="CORE",
):
    """Build a position dict for testing."""
    opened_at = (datetime.now(timezone.utc) - timedelta(days=hold_days)).isoformat()
    pos = {
        "symbol": symbol,
        "net_quantity": net_quantity,
        "avg_price": avg_price,
        "last_mark_price": mark_price,
        "opened_at": opened_at,
        "direction": "LONG" if net_quantity > 0 else "SHORT",
        "rating_ids": ["test-rating"],
        "lane": "CORE",
        "research_playbook": playbook,
        "updated_at": opened_at,
    }
    if invalidation_conditions is not None:
        pos["invalidation_conditions"] = invalidation_conditions
    if original_conviction > 0:
        pos["original_conviction"] = original_conviction
    return pos


class TestThesisInvalidation:
    @patch("tradingagents.graph.paper_execution._fetch_reference_price_from_market")
    def test_price_below_triggers_exit(self, mock_fetch, tmp_path):
        """Price dropping below invalidation threshold should trigger exit."""
        positions = {
            "AAPL": _make_position(
                mark_price=135.0,  # Below the 140 threshold
                invalidation_conditions=[
                    {
                        "metric": "price",
                        "operator": "<",
                        "threshold": 140.0,
                        "description": "Below key support",
                    }
                ],
            ),
        }
        pos_path = _make_positions_file(tmp_path, positions)
        outbox_path = _make_outbox_file(tmp_path)

        result = build_exit_execution_plan(
            execution_mode="paper",
            positions_path=pos_path,
            outbox_path=outbox_path,
        )
        signals = result.get("signals", [])
        assert len(signals) == 1
        assert signals[0]["rule"] == "THESIS_INVALIDATED"
        assert "Below key support" in signals[0]["reason"]

    @patch("tradingagents.graph.paper_execution._fetch_reference_price_from_market")
    def test_price_above_triggers_exit(self, mock_fetch, tmp_path):
        """Short position: price rising above threshold triggers invalidation."""
        positions = {
            "TSLA": _make_position(
                symbol="TSLA",
                net_quantity=-5,
                avg_price=200.0,
                mark_price=220.0,  # Above 210 threshold
                invalidation_conditions=[
                    {
                        "metric": "price",
                        "operator": ">",
                        "threshold": 210.0,
                        "description": "Breakout above resistance",
                    }
                ],
            ),
        }
        pos_path = _make_positions_file(tmp_path, positions)
        outbox_path = _make_outbox_file(tmp_path)

        result = build_exit_execution_plan(
            execution_mode="paper",
            positions_path=pos_path,
            outbox_path=outbox_path,
        )
        signals = result.get("signals", [])
        assert len(signals) == 1
        assert signals[0]["rule"] == "THESIS_INVALIDATED"

    @patch("tradingagents.graph.paper_execution._fetch_reference_price_from_market")
    def test_price_not_triggered(self, mock_fetch, tmp_path):
        """Price within acceptable range should not trigger invalidation."""
        positions = {
            "AAPL": _make_position(
                mark_price=155.0,  # Above 140 threshold
                invalidation_conditions=[
                    {
                        "metric": "price",
                        "operator": "<",
                        "threshold": 140.0,
                        "description": "Below support",
                    }
                ],
            ),
        }
        pos_path = _make_positions_file(tmp_path, positions)
        outbox_path = _make_outbox_file(tmp_path)

        result = build_exit_execution_plan(
            execution_mode="paper",
            positions_path=pos_path,
            outbox_path=outbox_path,
        )
        signals = result.get("signals", [])
        # Should be skipped, not exited
        assert all(s.get("rule") != "THESIS_INVALIDATED" for s in signals)

    @patch("tradingagents.graph.paper_execution._fetch_reference_price_from_market")
    def test_non_price_metric_skipped(self, mock_fetch, tmp_path):
        """Non-price metrics should be skipped (deferred to future)."""
        positions = {
            "AAPL": _make_position(
                mark_price=160.0,
                invalidation_conditions=[
                    {
                        "metric": "PE_ratio",
                        "operator": ">",
                        "threshold": 35.0,
                        "description": "PE too high",
                    }
                ],
            ),
        }
        pos_path = _make_positions_file(tmp_path, positions)
        outbox_path = _make_outbox_file(tmp_path)

        result = build_exit_execution_plan(
            execution_mode="paper",
            positions_path=pos_path,
            outbox_path=outbox_path,
        )
        signals = result.get("signals", [])
        assert all(s.get("rule") != "THESIS_INVALIDATED" for s in signals)

    @patch("tradingagents.graph.paper_execution._fetch_reference_price_from_market")
    def test_crosses_below_operator(self, mock_fetch, tmp_path):
        """crosses_below should work the same as < for price."""
        positions = {
            "AAPL": _make_position(
                mark_price=135.0,
                invalidation_conditions=[
                    {
                        "metric": "stock_price",
                        "operator": "crosses_below",
                        "threshold": 140.0,
                        "description": "Crossed below support",
                    }
                ],
            ),
        }
        pos_path = _make_positions_file(tmp_path, positions)
        outbox_path = _make_outbox_file(tmp_path)

        result = build_exit_execution_plan(
            execution_mode="paper",
            positions_path=pos_path,
            outbox_path=outbox_path,
        )
        signals = result.get("signals", [])
        assert len(signals) == 1
        assert signals[0]["rule"] == "THESIS_INVALIDATED"


class TestConvictionDecay:
    @patch("tradingagents.graph.paper_execution._fetch_reference_price_from_market")
    def test_decay_triggers_after_threshold(self, mock_fetch, tmp_path):
        """Position held > 10 days with low original conviction should decay out."""
        # conviction 3.0 after 20 days: 3.0 * 0.9^(20/5) = 3.0 * 0.9^4 = 3.0 * 0.6561 = 1.97
        positions = {
            "AAPL": _make_position(
                hold_days=20,
                original_conviction=3,
                mark_price=155.0,  # Small gain, no stop/take profit
            ),
        }
        pos_path = _make_positions_file(tmp_path, positions)
        outbox_path = _make_outbox_file(tmp_path)

        result = build_exit_execution_plan(
            execution_mode="paper",
            positions_path=pos_path,
            outbox_path=outbox_path,
        )
        signals = result.get("signals", [])
        assert len(signals) == 1
        assert signals[0]["rule"] == "CONVICTION_DECAY"

    @patch("tradingagents.graph.paper_execution._fetch_reference_price_from_market")
    def test_no_decay_under_10_days(self, mock_fetch, tmp_path):
        """Positions held <= 10 days should not trigger conviction decay."""
        positions = {
            "AAPL": _make_position(
                hold_days=8,
                original_conviction=3,
                mark_price=155.0,
            ),
        }
        pos_path = _make_positions_file(tmp_path, positions)
        outbox_path = _make_outbox_file(tmp_path)

        result = build_exit_execution_plan(
            execution_mode="paper",
            positions_path=pos_path,
            outbox_path=outbox_path,
        )
        signals = result.get("signals", [])
        assert all(s.get("rule") != "CONVICTION_DECAY" for s in signals)

    @patch("tradingagents.graph.paper_execution._fetch_reference_price_from_market")
    def test_high_conviction_survives_longer(self, mock_fetch, tmp_path):
        """High conviction (5) decays more slowly: 5 * 0.9^(15/5) = 5 * 0.729 = 3.645"""
        positions = {
            "AAPL": _make_position(
                hold_days=15,
                original_conviction=5,
                mark_price=155.0,
            ),
        }
        pos_path = _make_positions_file(tmp_path, positions)
        outbox_path = _make_outbox_file(tmp_path)

        result = build_exit_execution_plan(
            execution_mode="paper",
            positions_path=pos_path,
            outbox_path=outbox_path,
        )
        signals = result.get("signals", [])
        assert all(s.get("rule") != "CONVICTION_DECAY" for s in signals)

    @patch("tradingagents.graph.paper_execution._fetch_reference_price_from_market")
    def test_zero_conviction_no_decay(self, mock_fetch, tmp_path):
        """Zero original conviction should not trigger decay (guard clause)."""
        positions = {
            "AAPL": _make_position(
                hold_days=30,
                original_conviction=0,
                mark_price=155.0,
            ),
        }
        pos_path = _make_positions_file(tmp_path, positions)
        outbox_path = _make_outbox_file(tmp_path)

        result = build_exit_execution_plan(
            execution_mode="paper",
            positions_path=pos_path,
            outbox_path=outbox_path,
        )
        signals = result.get("signals", [])
        assert all(s.get("rule") != "CONVICTION_DECAY" for s in signals)


class TestApplyFillStoresNewFields:
    def test_stores_invalidation_conditions(self):
        """_apply_fill_to_position should store invalidation_conditions from order."""
        open_positions = {}
        order = {
            "symbol": "AAPL",
            "signed_quantity": 10,
            "filled_price": 150.0,
            "rating_id": "r1",
            "lane": "CORE",
            "research_playbook": "CORE",
            "invalidation_conditions": [
                {"metric": "price", "operator": "<", "threshold": 140.0, "description": "Support"}
            ],
            "confidence": 4,
        }
        _apply_fill_to_position(open_positions, order)
        assert "AAPL" in open_positions
        pos = open_positions["AAPL"]
        assert len(pos["invalidation_conditions"]) == 1
        assert pos["invalidation_conditions"][0]["threshold"] == 140.0
        assert pos["original_conviction"] == 4.0

    def test_preserves_existing_conditions_on_add(self):
        """When adding to existing position, preserve invalidation if order lacks them."""
        open_positions = {
            "AAPL": {
                "symbol": "AAPL",
                "net_quantity": 10,
                "avg_price": 150.0,
                "last_mark_price": 155.0,
                "opened_at": "2026-01-01T00:00:00",
                "direction": "LONG",
                "rating_ids": ["r1"],
                "lane": "CORE",
                "research_playbook": "CORE",
                "invalidation_conditions": [
                    {"metric": "price", "operator": "<", "threshold": 140.0, "description": "Support"}
                ],
                "original_conviction": 4.0,
                "updated_at": "2026-01-01T00:00:00",
            }
        }
        order = {
            "symbol": "AAPL",
            "signed_quantity": 5,
            "filled_price": 155.0,
            "rating_id": "r2",
            "lane": "CORE",
            "research_playbook": "CORE",
        }
        _apply_fill_to_position(open_positions, order)
        pos = open_positions["AAPL"]
        assert pos["net_quantity"] == 15
        # Should preserve existing conditions since order has none
        assert len(pos["invalidation_conditions"]) == 1
        assert pos["original_conviction"] == 4.0
