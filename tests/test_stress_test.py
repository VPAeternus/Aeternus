"""Tests for tradingagents.graph.stress_test."""

import json
import math
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import numpy as np
import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _write_positions(tmp_path, positions_dict):
    """Write a positions.json file and return its path string."""
    path = tmp_path / "positions.json"
    path.write_text(json.dumps({"open_positions": positions_dict}))
    return str(path)


def _mock_yf_download(symbols, **kwargs):
    """Return a fake DataFrame of daily closes for testing."""
    import pandas as pd
    dates = pd.bdate_range(end="2026-03-01", periods=60)
    np.random.seed(42)
    if isinstance(symbols, str):
        symbols = [symbols]
    data = {}
    for sym in symbols:
        base = 100 + hash(sym) % 50
        returns = np.random.normal(0.0005, 0.015, len(dates))
        prices = base * np.cumprod(1 + returns)
        data[sym] = prices
    df = pd.DataFrame(data, index=dates)
    df.columns = pd.MultiIndex.from_product([["Close"], df.columns])
    return df


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestComputeStressMetrics:
    def test_empty_positions(self, tmp_path):
        from tradingagents.graph.stress_test import compute_stress_metrics
        path = _write_positions(tmp_path, {})
        result = compute_stress_metrics(positions_path=path)
        assert result["positions_analyzed"] == 0
        assert result["portfolio_var_95"] == 0.0
        assert result["portfolio_cvar_95"] == 0.0
        assert "No open positions" in result["warnings"][0]

    def test_single_position_no_scenarios(self, tmp_path):
        """< 2 positions should skip scenario analysis."""
        from tradingagents.graph.stress_test import compute_stress_metrics
        positions = {
            "AAPL": {
                "net_quantity": 100,
                "last_mark_price": 180.0,
                "avg_price": 170.0,
                "sector": "Technology",
            }
        }
        path = _write_positions(tmp_path, positions)
        with patch("yfinance.download", side_effect=_mock_yf_download):
            result = compute_stress_metrics(positions_path=path)
        assert result["positions_analyzed"] == 1
        assert result["scenario_results"] == {}  # < 2 positions
        assert result["portfolio_var_95"] >= 0
        assert result["portfolio_cvar_95"] >= result["portfolio_var_95"]

    def test_two_positions_with_scenarios(self, tmp_path):
        from tradingagents.graph.stress_test import compute_stress_metrics
        positions = {
            "AAPL": {
                "net_quantity": 100,
                "last_mark_price": 180.0,
                "avg_price": 170.0,
                "sector": "Technology",
            },
            "XOM": {
                "net_quantity": 50,
                "last_mark_price": 110.0,
                "avg_price": 105.0,
                "sector": "Energy",
            },
        }
        path = _write_positions(tmp_path, positions)
        with patch("yfinance.download", side_effect=_mock_yf_download):
            result = compute_stress_metrics(positions_path=path)
        assert result["positions_analyzed"] == 2
        assert len(result["scenario_results"]) == 4
        assert "COVID crash" in result["scenario_results"]
        assert "impact_pct" in result["scenario_results"]["COVID crash"]
        assert "worst_position" in result["scenario_results"]["COVID crash"]

    def test_cvar_greater_equal_var(self, tmp_path):
        """CVaR should always be >= VaR (further into the tail)."""
        from tradingagents.graph.stress_test import compute_stress_metrics
        positions = {
            "MSFT": {"net_quantity": 200, "last_mark_price": 400.0, "sector": "Technology"},
            "JPM": {"net_quantity": 100, "last_mark_price": 200.0, "sector": "Financials"},
        }
        path = _write_positions(tmp_path, positions)
        with patch("yfinance.download", side_effect=_mock_yf_download):
            result = compute_stress_metrics(positions_path=path)
        assert result["portfolio_cvar_95"] >= result["portfolio_var_95"]

    def test_concentration_metrics(self, tmp_path):
        from tradingagents.graph.stress_test import compute_stress_metrics
        positions = {
            "AAPL": {"net_quantity": 100, "last_mark_price": 180.0, "sector": "Technology"},
            "MSFT": {"net_quantity": 10, "last_mark_price": 400.0, "sector": "Technology"},
            "XOM": {"net_quantity": 5, "last_mark_price": 110.0, "sector": "Energy"},
        }
        path = _write_positions(tmp_path, positions)
        with patch("yfinance.download", side_effect=_mock_yf_download):
            result = compute_stress_metrics(positions_path=path)
        conc = result["concentration"]
        assert conc["top_position_pct"] > 0
        assert conc["top_3_pct"] > 0
        assert conc["top_3_pct"] >= conc["top_position_pct"]

    def test_price_fetch_failure_uses_fallback(self, tmp_path):
        from tradingagents.graph.stress_test import compute_stress_metrics
        positions = {
            "AAPL": {"net_quantity": 100, "last_mark_price": 180.0, "sector": "Technology"},
            "MSFT": {"net_quantity": 50, "last_mark_price": 400.0, "sector": "Technology"},
        }
        path = _write_positions(tmp_path, positions)
        with patch("yfinance.download", side_effect=Exception("Network error")):
            result = compute_stress_metrics(positions_path=path)
        assert result["portfolio_var_95"] == 2.5  # fallback
        assert result["portfolio_cvar_95"] == 3.5
        assert any("Price fetch failed" in w for w in result["warnings"])

    def test_flash_crash_uniform(self, tmp_path):
        """Flash crash applies -5% uniform to all positions."""
        from tradingagents.graph.stress_test import compute_stress_metrics
        positions = {
            "AAPL": {"net_quantity": 100, "last_mark_price": 100.0, "sector": "Technology"},
            "XOM": {"net_quantity": 100, "last_mark_price": 100.0, "sector": "Energy"},
        }
        path = _write_positions(tmp_path, positions)
        with patch("yfinance.download", side_effect=_mock_yf_download):
            result = compute_stress_metrics(positions_path=path)
        flash = result["scenario_results"]["Flash crash"]
        assert flash["impact_pct"] == pytest.approx(-5.0, abs=0.1)

    def test_all_same_sector_concentration(self, tmp_path):
        """All tech positions should show concentrated scenario risk."""
        from tradingagents.graph.stress_test import compute_stress_metrics
        positions = {
            "AAPL": {"net_quantity": 100, "last_mark_price": 180.0, "sector": "Technology"},
            "MSFT": {"net_quantity": 50, "last_mark_price": 400.0, "sector": "Technology"},
        }
        path = _write_positions(tmp_path, positions)
        with patch("yfinance.download", side_effect=_mock_yf_download):
            result = compute_stress_metrics(positions_path=path)
        tech_selloff = result["scenario_results"]["Tech sell-off"]
        assert tech_selloff["impact_pct"] < -10  # All tech = full -15% hit


class TestBuildStressBrief:
    def test_empty_returns_empty(self, tmp_path):
        from tradingagents.graph.stress_test import build_stress_brief
        path = _write_positions(tmp_path, {})
        result = build_stress_brief(positions_path=path)
        assert result == ""

    def test_nonempty_has_sections(self, tmp_path):
        from tradingagents.graph.stress_test import build_stress_brief
        positions = {
            "AAPL": {"net_quantity": 100, "last_mark_price": 180.0, "sector": "Technology"},
            "XOM": {"net_quantity": 50, "last_mark_price": 110.0, "sector": "Energy"},
        }
        path = _write_positions(tmp_path, positions)
        with patch("yfinance.download", side_effect=_mock_yf_download):
            brief = build_stress_brief(positions_path=path)
        assert "STRESS TEST" in brief
        assert "VaR" in brief
        assert "CVaR" in brief
        assert "Scenario impacts" in brief


class TestClassifySector:
    def test_sector_keywords(self):
        from tradingagents.graph.stress_test import _classify_sector
        assert _classify_sector("Information Technology") == "Technology"
        assert _classify_sector("Health Care") == "Healthcare"
        assert _classify_sector("Oil & Gas") == "Energy"
        assert _classify_sector("Banking Services") == "Financials"
        assert _classify_sector("Consumer Staples") == "_other"
        assert _classify_sector("") == "_other"
