"""Tests for morning brief generator."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from tradingagents.graph.morning_brief import build_morning_brief


class TestMorningBrief:
    """Test morning brief generation."""

    def test_brief_loads_positions_correctly(self):
        """Test that brief loads open positions and computes notional correctly."""
        with TemporaryDirectory() as tmpdir:
            # Create sample positions file
            positions = {
                "open_positions": {
                    "NVDA": {
                        "net_quantity": 100.0,
                        "avg_price": 100.0,
                        "last_mark_price": 110.0,
                    },
                    "GOOGL": {
                        "net_quantity": 50.0,
                        "avg_price": 200.0,
                        "last_mark_price": 210.0,
                    },
                }
            }

            pos_path = Path(tmpdir) / "positions.json"
            pos_path.write_text(json.dumps(positions))

            brief = build_morning_brief(
                positions_path=str(pos_path),
                hwm_path="/nonexistent",
                track_record_path="/nonexistent",
                deal_flow_path="/nonexistent",
            )

            # Check portfolio section
            assert brief["portfolio"]["open_positions"] == 2
            assert brief["portfolio"]["gross_exposure"] == pytest.approx(21000.0, rel=100)

            # Check top positions
            assert len(brief["portfolio"]["top_positions"]) == 2
            assert brief["portfolio"]["top_positions"][0]["symbol"] in ["NVDA", "GOOGL"]
            assert brief["portfolio"]["top_positions"][0]["pnl_pct"] == 10.0  # (110-100)/100

    def test_brief_computes_win_rate_from_track_record(self):
        """Test that brief computes win rate from closed trades."""
        with TemporaryDirectory() as tmpdir:
            # Create sample track record
            track_record = [
                {
                    "ticker": "AAPL",
                    "status": "CLOSED",
                    "price_at_rating": 100.0,
                    "close_price": 110.0,
                    "date": "2026-02-28",
                },
                {
                    "ticker": "MSFT",
                    "status": "CLOSED",
                    "price_at_rating": 200.0,
                    "close_price": 190.0,
                    "date": "2026-02-27",
                },
                {
                    "ticker": "GOOGL",
                    "status": "OPEN",
                    "price_at_rating": 150.0,
                    "close_price": None,
                },
            ]

            tr_path = Path(tmpdir) / "track_record.json"
            tr_path.write_text(json.dumps(track_record))

            brief = build_morning_brief(
                positions_path="/nonexistent",
                hwm_path="/nonexistent",
                track_record_path=str(tr_path),
                deal_flow_path="/nonexistent",
            )

            # Check performance section
            perf = brief["performance"]
            assert perf["total_trades"] == 3
            assert perf["closed_trades"] == 2
            assert perf["win_rate"] == pytest.approx(0.5, rel=0.01)  # 1 win, 1 loss
            assert perf["avg_win_pct"] == pytest.approx(10.0, rel=0.1)
            assert perf["avg_loss_pct"] == pytest.approx(-5.0, rel=0.1)

    def test_brief_handles_missing_files_gracefully(self):
        """Test that brief returns safe defaults when data files are missing."""
        brief = build_morning_brief(
            positions_path="/nonexistent/positions.json",
            hwm_path="/nonexistent/hwm.json",
            track_record_path="/nonexistent/track_record.json",
            deal_flow_path="/nonexistent/deal_flow/",
        )

        # Should have all expected keys
        assert "generated_at" in brief
        assert "date" in brief
        assert "portfolio" in brief
        assert "performance" in brief
        assert "risk" in brief
        assert "gex_regime" in brief
        assert "deal_flow" in brief

        # Should have safe defaults, not crash
        assert brief["portfolio"]["open_positions"] == 0
        assert brief["performance"]["closed_trades"] == 0
        assert brief["deal_flow"]["top_signals"] == []

    def test_brief_concentration_flag_above_15pct(self):
        """Test that concentration flags appear for positions >15% of portfolio."""
        with TemporaryDirectory() as tmpdir:
            positions = {
                "open_positions": {
                    "LARGE": {
                        "net_quantity": 100.0,
                        "avg_price": 1000.0,
                        "last_mark_price": 1000.0,
                    },
                    "SMALL": {
                        "net_quantity": 1.0,
                        "avg_price": 100.0,
                        "last_mark_price": 100.0,
                    },
                }
            }

            pos_path = Path(tmpdir) / "positions.json"
            pos_path.write_text(json.dumps(positions))

            brief = build_morning_brief(
                positions_path=str(pos_path),
                hwm_path="/nonexistent",
                track_record_path="/nonexistent",
                deal_flow_path="/nonexistent",
            )

            # Check concentration flags
            risk = brief["risk"]
            assert len(risk["concentration_flags"]) > 0
            assert "LARGE" in str(risk["concentration_flags"])

    def test_brief_top_signals_from_scout_handoff(self):
        """Test that top signals are loaded from latest scout handoff."""
        with TemporaryDirectory() as tmpdir:
            handoff_dir = Path(tmpdir) / "2026-03-01"
            handoff_dir.mkdir()

            handoff_data = {
                "date": "2026-03-01",
                "tickers": ["AAPL", "MSFT", "GOOGL"],
                "metadata_by_ticker": {
                    "AAPL": {"scouts": ["x_manual"]},
                    "MSFT": {"scouts": ["x_manual"]},
                    "GOOGL": {"scouts": ["macro"]},
                },
            }

            handoff_path = handoff_dir / "final_dealflow_tickers.json"
            handoff_path.write_text(json.dumps(handoff_data))

            brief = build_morning_brief(
                positions_path="/nonexistent",
                hwm_path="/nonexistent",
                track_record_path="/nonexistent",
                deal_flow_path=str(tmpdir),
            )

            # Check deal flow section
            deal_flow = brief["deal_flow"]
            assert deal_flow["latest_handoff_date"] == "2026-03-01"
            assert len(deal_flow["top_signals"]) == 3
            assert deal_flow["top_signals"][0]["symbol"] == "AAPL"
            assert deal_flow["top_signals"][0]["score"] is None
