"""Tests for tradingagents.graph.regime_monitor."""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _write_state(tmp_path, state_dict):
    path = tmp_path / "regime_state.json"
    path.write_text(json.dumps(state_dict))
    return str(path)


def _mock_snapshot(spy_close=500.0, spy_sma200=490.0, vix_close=15.0):
    """Build a fake MarketRegimeSnapshot dict."""
    return {
        "timestamp": "2026-03-01T12:00:00",
        "spy_close": spy_close,
        "spy_sma20": 495.0,
        "spy_sma200": spy_sma200,
        "spy_sma200_5d_ago": spy_sma200 - 0.5,
        "spy_deviation_pct": (spy_close - 495.0) / 495.0 * 100.0,
        "vix_close": vix_close,
    }


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestCheckRegimeTransition:
    def test_first_run_no_alert(self, tmp_path):
        from tradingagents.graph.regime_monitor import check_regime_transition
        state_path = str(tmp_path / "regime_state.json")
        with patch("tradingagents.graph.market_regime.MarketRegimeProvider") as MockProvider:
            MockProvider.return_value.get_market_regime_snapshot.return_value = _mock_snapshot()
            result = check_regime_transition(state_path=state_path)

        assert result["current_regime"] == "BULL"
        assert result["transition_detected"] is False
        assert result["alert"] == ""
        # State file should be created
        assert Path(state_path).exists()

    def test_bull_to_bear_transition(self, tmp_path):
        from tradingagents.graph.regime_monitor import check_regime_transition
        state_path = _write_state(tmp_path, {
            "current_regime": "BULL",
            "regime_since": "2026-01-01",
            "previous_regime": "",
        })
        # SPY below SMA200 = BEAR
        with patch("tradingagents.graph.market_regime.MarketRegimeProvider") as MockProvider:
            MockProvider.return_value.get_market_regime_snapshot.return_value = _mock_snapshot(
                spy_close=480.0, spy_sma200=490.0, vix_close=20.0
            )
            result = check_regime_transition(state_path=state_path)

        assert result["current_regime"] == "BEAR"
        assert result["previous_regime"] == "BULL"
        assert result["transition_detected"] is True
        assert "BULL" in result["transition_type"]
        assert "BEAR" in result["transition_type"]
        assert "Review all positions" in result["alert"]

    def test_bear_to_bull_transition(self, tmp_path):
        from tradingagents.graph.regime_monitor import check_regime_transition
        state_path = _write_state(tmp_path, {
            "current_regime": "BEAR",
            "regime_since": "2026-01-01",
            "previous_regime": "",
        })
        with patch("tradingagents.graph.market_regime.MarketRegimeProvider") as MockProvider:
            MockProvider.return_value.get_market_regime_snapshot.return_value = _mock_snapshot(
                spy_close=500.0, spy_sma200=490.0, vix_close=15.0
            )
            result = check_regime_transition(state_path=state_path)

        assert result["current_regime"] == "BULL"
        assert result["transition_detected"] is True
        assert "Evaluate adding risk" in result["alert"]

    def test_no_transition_same_regime(self, tmp_path):
        from tradingagents.graph.regime_monitor import check_regime_transition
        state_path = _write_state(tmp_path, {
            "current_regime": "BULL",
            "regime_since": "2026-02-28",
            "previous_regime": "",
        })
        with patch("tradingagents.graph.market_regime.MarketRegimeProvider") as MockProvider:
            MockProvider.return_value.get_market_regime_snapshot.return_value = _mock_snapshot()
            result = check_regime_transition(state_path=state_path)

        assert result["transition_detected"] is False
        assert result["alert"] == ""

    def test_stale_regime_alert(self, tmp_path):
        from tradingagents.graph.regime_monitor import check_regime_transition
        state_path = _write_state(tmp_path, {
            "current_regime": "BULL",
            "regime_since": "2025-11-01",  # >60 days ago
            "previous_regime": "",
        })
        with patch("tradingagents.graph.market_regime.MarketRegimeProvider") as MockProvider:
            MockProvider.return_value.get_market_regime_snapshot.return_value = _mock_snapshot()
            result = check_regime_transition(state_path=state_path)

        assert result["transition_detected"] is False
        assert "assumptions may be stale" in result["alert"]

    def test_market_data_unavailable(self, tmp_path):
        from tradingagents.graph.regime_monitor import check_regime_transition
        state_path = _write_state(tmp_path, {
            "current_regime": "BULL",
            "regime_since": "2026-02-01",
        })
        with patch("tradingagents.graph.market_regime.MarketRegimeProvider") as MockProvider:
            MockProvider.return_value.get_market_regime_snapshot.return_value = None
            result = check_regime_transition(state_path=state_path)

        assert result["current_regime"] == "BULL"
        assert result["transition_detected"] is False
        assert result["data_available"] is False

    def test_persists_state(self, tmp_path):
        from tradingagents.graph.regime_monitor import check_regime_transition
        state_path = str(tmp_path / "regime_state.json")
        with patch("tradingagents.graph.market_regime.MarketRegimeProvider") as MockProvider:
            MockProvider.return_value.get_market_regime_snapshot.return_value = _mock_snapshot()
            check_regime_transition(state_path=state_path)

        saved = json.loads(Path(state_path).read_text())
        assert saved["current_regime"] == "BULL"
        assert "last_checked" in saved


class TestBuildRegimeAlert:
    def test_no_alert_returns_empty(self, tmp_path):
        from tradingagents.graph.regime_monitor import build_regime_alert
        state_path = _write_state(tmp_path, {
            "current_regime": "BULL",
            "regime_since": "2026-02-28",
        })
        with patch("tradingagents.graph.market_regime.MarketRegimeProvider") as MockProvider:
            MockProvider.return_value.get_market_regime_snapshot.return_value = _mock_snapshot()
            alert = build_regime_alert(state_path=state_path)
        assert alert == ""

    def test_transition_alert_has_content(self, tmp_path):
        from tradingagents.graph.regime_monitor import build_regime_alert
        state_path = _write_state(tmp_path, {
            "current_regime": "BULL",
            "regime_since": "2026-01-01",
        })
        with patch("tradingagents.graph.market_regime.MarketRegimeProvider") as MockProvider:
            MockProvider.return_value.get_market_regime_snapshot.return_value = _mock_snapshot(
                spy_close=480.0, spy_sma200=490.0, vix_close=20.0
            )
            alert = build_regime_alert(state_path=state_path)
        assert "REGIME MONITOR" in alert
        assert "VIX" in alert
