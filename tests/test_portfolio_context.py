"""Tests for portfolio context builder."""
import json
import pytest
from unittest.mock import patch
from tradingagents.graph.portfolio_context import (
    _load_json,
    _format_positions_summary,
    _format_calibration,
    _format_drawdown,
    build_portfolio_context,
)


class TestLoadJson:
    def test_missing_file(self):
        result = _load_json("/nonexistent/path.json", default={"x": 1})
        assert result == {"x": 1}

    def test_missing_file_default_none(self):
        result = _load_json("/nonexistent/path.json")
        assert result == {}

    def test_valid_json(self, tmp_path):
        p = tmp_path / "test.json"
        p.write_text(json.dumps({"key": "value"}))
        result = _load_json(str(p))
        assert result == {"key": "value"}


class TestFormatPositionsSummary:
    def test_empty_positions(self):
        result = _format_positions_summary({})
        assert "No open positions" in result

    def test_single_long_position(self):
        positions = {
            "AAPL": {
                "net_quantity": 10,
                "avg_price": 150.0,
                "last_mark_price": 165.0,
                "sector": "Technology",
            },
        }
        result = _format_positions_summary(positions)
        assert "1 open" in result
        assert "AAPL" in result
        assert "LONG" in result

    def test_concentration_warning(self):
        positions = {
            "AAPL": {
                "net_quantity": 100,
                "avg_price": 150.0,
                "last_mark_price": 160.0,
                "sector": "Technology",
            },
        }
        result = _format_positions_summary(positions)
        assert "WARNING" in result
        assert "concentration" in result.lower()

    def test_short_position(self):
        positions = {
            "SPY": {
                "net_quantity": -50,
                "avg_price": 500.0,
                "last_mark_price": 490.0,
                "sector": "Index",
            },
        }
        result = _format_positions_summary(positions)
        assert "SHORT" in result

    def test_multiple_positions_with_sectors(self):
        positions = {
            "AAPL": {
                "net_quantity": 10, "avg_price": 150.0,
                "last_mark_price": 160.0, "sector": "Technology",
            },
            "KO": {
                "net_quantity": 20, "avg_price": 60.0,
                "last_mark_price": 62.0, "sector": "Consumer Staples",
            },
        }
        result = _format_positions_summary(positions)
        assert "2 open" in result
        assert "Technology" in result
        assert "Consumer Staples" in result

    def test_missing_mark_price_uses_avg(self):
        positions = {
            "AAPL": {
                "net_quantity": 10, "avg_price": 150.0,
                "last_mark_price": 0, "sector": "Tech",
            },
        }
        result = _format_positions_summary(positions)
        assert "AAPL" in result
        assert "N/A" not in result or "LONG" in result


class TestFormatCalibration:
    def test_insufficient_data(self):
        result = _format_calibration({"closed_decisions": 5, "sample_sufficient": False})
        assert "insufficient" in result.lower()

    def test_empty_calibration(self):
        result = _format_calibration({})
        assert "insufficient" in result.lower()

    def test_none_calibration(self):
        result = _format_calibration(None)
        assert "insufficient" in result.lower()

    def test_sufficient_with_biases(self):
        cal = {
            "sample_sufficient": True,
            "closed_decisions": 50,
            "systematic_biases": ["Overconfident at level 5: predicted 100%, actual 60%"],
            "accuracy_by_sector": {"Technology": 0.85, "Energy": 0.35},
        }
        result = _format_calibration(cal)
        assert "Overconfident" in result
        assert "Technology" in result
        assert "Energy" in result

    def test_sufficient_no_biases(self):
        cal = {
            "sample_sufficient": True,
            "closed_decisions": 50,
            "systematic_biases": [],
            "accuracy_by_sector": {},
        }
        result = _format_calibration(cal)
        assert "No systematic biases" in result


class TestFormatDrawdown:
    def test_empty_data(self):
        result = _format_drawdown({})
        assert "no" in result.lower()

    def test_no_drawdown(self):
        result = _format_drawdown({"high_water_mark": 100000, "current_equity": 99000})
        assert "1.0%" in result
        assert "DRAWDOWN MODE ACTIVE" not in result

    def test_drawdown_active(self):
        result = _format_drawdown({"high_water_mark": 100000, "current_equity": 93000})
        assert "7.0%" in result
        assert "DRAWDOWN MODE ACTIVE" in result

    def test_at_hwm(self):
        result = _format_drawdown({"high_water_mark": 100000, "current_equity": 100000})
        assert "0.0%" in result
        assert "DRAWDOWN MODE ACTIVE" not in result

    def test_exactly_5pct(self):
        result = _format_drawdown({"high_water_mark": 100000, "current_equity": 95000})
        assert "DRAWDOWN MODE ACTIVE" in result

    def test_portfolio_value_fallback(self):
        result = _format_drawdown({"high_water_mark": 100000, "portfolio_value": 92000})
        assert "DRAWDOWN MODE ACTIVE" in result


class TestBuildPortfolioContext:
    @patch("tradingagents.graph.portfolio_context._load_json")
    @patch("tradingagents.graph.calibration.build_calibration_report")
    def test_basic_output_structure(self, mock_cal, mock_json):
        mock_json.return_value = {}
        mock_cal.return_value = {"sample_sufficient": False, "closed_decisions": 0}
        result = build_portfolio_context()
        assert "PORTFOLIO CONTEXT FOR RISK DEBATE" in result
        assert "END PORTFOLIO CONTEXT" in result

    @patch("tradingagents.graph.portfolio_context._load_json")
    @patch("tradingagents.graph.calibration.build_calibration_report")
    def test_with_regime(self, mock_cal, mock_json):
        mock_json.return_value = {}
        mock_cal.return_value = {"sample_sufficient": False, "closed_decisions": 0}
        result = build_portfolio_context(market_regime={"regime": "RISK_ON", "vix": 15.5})
        assert "RISK_ON" in result
        assert "15.5" in result

    @patch("tradingagents.graph.portfolio_context._load_json")
    @patch("tradingagents.graph.calibration.build_calibration_report")
    def test_drawdown_mode_detected(self, mock_cal, mock_json):
        def side_effect(path, default=None):
            if "hwm" in str(path):
                return {"high_water_mark": 100000, "current_equity": 90000}
            return {"open_positions": {}}
        mock_json.side_effect = side_effect
        mock_cal.return_value = {"sample_sufficient": False, "closed_decisions": 0}
        result = build_portfolio_context()
        assert "DRAWDOWN MODE ACTIVE" in result

    @patch("tradingagents.graph.portfolio_context._load_json")
    @patch("tradingagents.graph.calibration.build_calibration_report")
    @patch("tradingagents.graph.portfolio_context.AeternusKnowledgeGraph", create=True)
    def test_geopolitical_alert_commodity_shock(self, mock_akg_cls, mock_cal, mock_json):
        mock_json.return_value = {}
        mock_cal.return_value = {"sample_sufficient": False, "closed_decisions": 0}
        mock_akg = mock_akg_cls.return_value
        mock_akg.get_recent_causal_events.return_value = [
            {
                "ticker": "CLUSTER_OIL_DISRUPTION",
                "event_type": "COMMODITY_SHOCK",
                "event_date": "2026-03-02",
                "magnitude": 0.82,
                "direction": "POSITIVE",
                "source": "commodity_shock_scout",
                "cluster_name": "OIL_DISRUPTION",
                "triggered_instruments": ["USO", "BNO"],
                "volume_z_max": 2.3,
            }
        ]
        with patch(
            "tradingagents.graph.knowledge_graph.AeternusKnowledgeGraph",
            mock_akg_cls,
        ):
            result = build_portfolio_context()
        assert "GEOPOLITICAL ALERTS" in result
        assert "COMMODITY SHOCK" in result
        assert "OIL_DISRUPTION" in result
        assert "USO" in result
        assert "vol-Z 2.3" in result

    @patch("tradingagents.graph.portfolio_context._load_json")
    @patch("tradingagents.graph.calibration.build_calibration_report")
    @patch("tradingagents.graph.portfolio_context.AeternusKnowledgeGraph", create=True)
    def test_geopolitical_alert_dod_spike(self, mock_akg_cls, mock_cal, mock_json):
        mock_json.return_value = {}
        mock_cal.return_value = {"sample_sufficient": False, "closed_decisions": 0}
        mock_akg = mock_akg_cls.return_value
        mock_akg.get_recent_causal_events.return_value = [
            {
                "ticker": "DOD_MUNITIONS",
                "event_type": "COMMODITY_SHOCK",
                "event_date": "2026-03-02",
                "magnitude": 0.75,
                "direction": "POSITIVE",
                "source": "dod_contract_scout",
                "contract_sector": "MUNITIONS",
                "z_score": 3.1,
                "top_recipients": ["LMT", "RTX", "GD"],
            }
        ]
        with patch(
            "tradingagents.graph.knowledge_graph.AeternusKnowledgeGraph",
            mock_akg_cls,
        ):
            result = build_portfolio_context()
        assert "GEOPOLITICAL ALERTS" in result
        assert "DOD AWARD SPIKE" in result
        assert "MUNITIONS" in result
        assert "Z=3.1" in result
        assert "LMT" in result

    @patch("tradingagents.graph.portfolio_context._load_json")
    @patch("tradingagents.graph.calibration.build_calibration_report")
    @patch("tradingagents.graph.portfolio_context.AeternusKnowledgeGraph", create=True)
    def test_geopolitical_alert_no_events(self, mock_akg_cls, mock_cal, mock_json):
        mock_json.return_value = {}
        mock_cal.return_value = {"sample_sufficient": False, "closed_decisions": 0}
        mock_akg = mock_akg_cls.return_value
        mock_akg.get_recent_causal_events.return_value = []
        with patch(
            "tradingagents.graph.knowledge_graph.AeternusKnowledgeGraph",
            mock_akg_cls,
        ):
            result = build_portfolio_context()
        assert "GEOPOLITICAL ALERTS" not in result
