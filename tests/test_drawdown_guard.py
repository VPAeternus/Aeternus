"""Tests for tradingagents.graph.drawdown_guard.

The drawdown guard is a MONITORING module — it tracks equity vs. HWM and
emits WARNING/ALERT states for review. It does NOT block or scale orders.
The hedge engine handles portfolio protection.
"""

import json

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _write_positions(tmp_path, open_positions: dict) -> str:
    """Write a positions.json file and return its path string."""
    path = tmp_path / "positions.json"
    path.write_text(json.dumps({"open_positions": open_positions}))
    return str(path)


def _write_hwm(tmp_path, hwm: float, current_equity: float | None = None, alert_triggered_at: str | None = None) -> str:
    """Write a hwm.json file and return its path string."""
    path = tmp_path / "hwm.json"
    data = {"high_water_mark": hwm, "updated_at_utc": "2026-03-01T00:00:00+00:00"}
    if current_equity is not None:
        data["current_equity"] = current_equity
    if alert_triggered_at is not None:
        data["alert_triggered_at"] = alert_triggered_at
    path.write_text(json.dumps(data))
    return str(path)


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestCheckDrawdownState:
    def test_ok_state_below_threshold(self, tmp_path):
        """0% drawdown → OK status."""
        from tradingagents.graph.drawdown_guard import check_drawdown_state

        positions = {"AAPL": {"market_value_usd": 100_000.0}}
        pos_path = _write_positions(tmp_path, positions)
        hwm_path = _write_hwm(tmp_path, hwm=100_000.0)

        result = check_drawdown_state(positions_path=pos_path, hwm_path=hwm_path)

        assert result["status"] == "OK"
        assert result["drawdown_pct"] == 0.0
        assert result["alert_triggered_at"] is None

    def test_warning_state_at_5pct(self, tmp_path):
        """5% drawdown → WARNING status (informational only, no order blocking)."""
        from tradingagents.graph.drawdown_guard import check_drawdown_state

        hwm = 100_000.0
        current = 95_000.0  # exactly 5% down
        positions = {"AAPL": {"market_value_usd": current}}
        pos_path = _write_positions(tmp_path, positions)
        hwm_path = _write_hwm(tmp_path, hwm=hwm)

        result = check_drawdown_state(positions_path=pos_path, hwm_path=hwm_path)

        assert result["status"] == "WARNING"
        assert result["drawdown_pct"] == pytest.approx(5.0, abs=0.01)
        assert result["alert_triggered_at"] is None
        # No scale_factor — this module does not control execution
        assert "scale_factor" not in result

    def test_alert_state_at_15pct(self, tmp_path):
        """15% drawdown → ALERT status (triggers immediate system review alert)."""
        from tradingagents.graph.drawdown_guard import check_drawdown_state

        hwm = 100_000.0
        current = 85_000.0  # exactly 15% down
        positions = {"AAPL": {"market_value_usd": current}}
        pos_path = _write_positions(tmp_path, positions)
        hwm_path = _write_hwm(tmp_path, hwm=hwm)

        result = check_drawdown_state(positions_path=pos_path, hwm_path=hwm_path)

        assert result["status"] == "ALERT"
        assert result["drawdown_pct"] == pytest.approx(15.0, abs=0.01)
        assert result["alert_triggered_at"] is not None  # timestamp persisted

    def test_no_hwm_returns_ok(self, tmp_path):
        """Missing HWM → OK (monitor inactive, safe default)."""
        from tradingagents.graph.drawdown_guard import check_drawdown_state

        positions = {"AAPL": {"market_value_usd": 50_000.0}}
        pos_path = _write_positions(tmp_path, positions)
        # Write hwm.json with zero HWM
        hwm_path = _write_hwm(tmp_path, hwm=0.0)

        result = check_drawdown_state(positions_path=pos_path, hwm_path=hwm_path)

        assert result["status"] == "OK"

    def test_alert_triggered_at_persisted_on_first_alert(self, tmp_path):
        """First ALERT persists alert_triggered_at; subsequent call reuses it."""
        from tradingagents.graph.drawdown_guard import check_drawdown_state

        hwm = 100_000.0
        current = 80_000.0  # 20% down → ALERT
        positions = {"AAPL": {"market_value_usd": current}}
        pos_path = _write_positions(tmp_path, positions)
        hwm_path = _write_hwm(tmp_path, hwm=hwm)

        result1 = check_drawdown_state(positions_path=pos_path, hwm_path=hwm_path)
        result2 = check_drawdown_state(positions_path=pos_path, hwm_path=hwm_path)

        assert result1["status"] == "ALERT"
        assert result1["alert_triggered_at"] is not None
        # Second call reuses same timestamp
        assert result2["alert_triggered_at"] == result1["alert_triggered_at"]

    def test_alert_cleared_on_recovery(self, tmp_path):
        """Recovery to OK clears alert_triggered_at from hwm.json."""
        from tradingagents.graph.drawdown_guard import check_drawdown_state

        hwm = 100_000.0
        # Start in ALERT
        positions = {"AAPL": {"market_value_usd": 80_000.0}}
        pos_path = _write_positions(tmp_path, positions)
        hwm_path = _write_hwm(tmp_path, hwm=hwm, alert_triggered_at="2026-03-01T12:00:00+00:00")

        # Simulate recovery — update positions to near-HWM
        pos_path2 = str(tmp_path / "positions_recovered.json")
        (tmp_path / "positions_recovered.json").write_text(
            json.dumps({"open_positions": {"AAPL": {"market_value_usd": 99_000.0}}})
        )
        result = check_drawdown_state(positions_path=pos_path2, hwm_path=hwm_path)

        assert result["status"] == "OK"
        assert result["alert_triggered_at"] is None


class TestComputePortfolioEquity:
    def test_sums_market_values(self, tmp_path):
        """Equity = sum of all market_value_usd across open positions."""
        from tradingagents.graph.drawdown_guard import compute_portfolio_equity

        positions = {
            "AAPL": {"market_value_usd": 50_000.0},
            "MSFT": {"market_value_usd": 30_000.0},
            "NVDA": {"market_value_usd": 20_000.0},
        }
        pos_path = _write_positions(tmp_path, positions)
        equity = compute_portfolio_equity(positions_path=pos_path)

        assert equity == pytest.approx(100_000.0)

    def test_returns_zero_on_missing_file(self):
        """Missing positions file → 0.0, never raises."""
        from tradingagents.graph.drawdown_guard import compute_portfolio_equity

        equity = compute_portfolio_equity(positions_path="/nonexistent/path/positions.json")
        assert equity == 0.0


class TestUpdateHwmEquity:
    def test_update_hwm_raises_hwm_on_new_high(self, tmp_path):
        """equity > HWM → HWM updated to new high."""
        from tradingagents.graph.drawdown_guard import update_hwm_equity

        hwm_path = _write_hwm(tmp_path, hwm=100_000.0)
        update_hwm_equity(current_equity=110_000.0, hwm_path=hwm_path)

        updated = json.loads((tmp_path / "hwm.json").read_text())
        assert updated["high_water_mark"] == pytest.approx(110_000.0)
        assert updated["current_equity"] == pytest.approx(110_000.0)

    def test_update_hwm_does_not_lower_hwm(self, tmp_path):
        """equity < HWM → HWM stays at original high, current_equity recorded."""
        from tradingagents.graph.drawdown_guard import update_hwm_equity

        hwm_path = _write_hwm(tmp_path, hwm=100_000.0)
        update_hwm_equity(current_equity=85_000.0, hwm_path=hwm_path)

        updated = json.loads((tmp_path / "hwm.json").read_text())
        assert updated["high_water_mark"] == pytest.approx(100_000.0)  # unchanged
        assert updated["current_equity"] == pytest.approx(85_000.0)   # recorded
