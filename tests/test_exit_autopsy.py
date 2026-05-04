# tests/test_exit_autopsy.py

import sys
import types
import json
import pytest
from pathlib import Path

# Stub chromadb (Python 3.14 compat)
if "chromadb" not in sys.modules or not hasattr(sys.modules.get("chromadb", None), "__path__"):
    _stub = types.ModuleType("chromadb")
    _stub.__path__ = []
    _stub.Client = None
    _config_stub = types.ModuleType("chromadb.config")
    _config_stub.Settings = type("Settings", (), {})
    sys.modules["chromadb"] = _stub
    sys.modules["chromadb.config"] = _config_stub

from tradingagents.graph.exit_autopsy import ExitAutopsyLedger


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------


def _make_trade(
    symbol="AAPL",
    return_pct=5.0,
    pnl_usd=500.0,
    exit_rule="stop_loss",
):
    """Factory helper to build a fake trade dict."""
    return {
        "symbol": symbol,
        "return_pct": return_pct,
        "pnl_usd": pnl_usd,
        "exit_rule": exit_rule,
    }


# ---------------------------------------------------------------------------
# Bayesian accuracy tests
# ---------------------------------------------------------------------------


class TestBayesianAccuracy:
    """Test the Beta-Binomial posterior mean calculation."""

    def test_bayesian_zero_trades(self):
        """0 trades returns 0.5 (neutral prior)."""
        result = ExitAutopsyLedger._bayesian_accuracy(0, 0)
        assert result == 0.5

    def test_bayesian_one_win(self):
        """1/1 returns 0.6 (slightly optimistic)."""
        result = ExitAutopsyLedger._bayesian_accuracy(1, 1)
        assert result == 0.6

    def test_bayesian_one_loss(self):
        """0/1 returns 0.4 (slightly pessimistic)."""
        result = ExitAutopsyLedger._bayesian_accuracy(0, 1)
        assert result == 0.4

    def test_bayesian_seven_of_ten(self):
        """7/10 returns ~0.643."""
        result = ExitAutopsyLedger._bayesian_accuracy(7, 10)
        assert abs(result - 0.643) < 0.001


# ---------------------------------------------------------------------------
# Build tests
# ---------------------------------------------------------------------------


class TestBuild:
    """Test the build() method."""

    def test_build_empty_trades(self, tmp_path, monkeypatch):
        """No trades → trade_count=0, by_exit_rule empty."""
        trades_file = tmp_path / "closed_trades.json"
        trades_file.write_text(json.dumps([]))

        ledger = ExitAutopsyLedger(str(trades_file))
        result = ledger.build()

        assert result["trade_count"] == 0
        assert result["by_exit_rule"] == {}

    def test_build_nonexistent_file(self, tmp_path, monkeypatch):
        """Nonexistent file → trade_count=0."""
        trades_file = tmp_path / "nonexistent.json"

        ledger = ExitAutopsyLedger(str(trades_file))
        result = ledger.build()

        assert result["trade_count"] == 0
        assert result["by_exit_rule"] == {}

    def test_build_three_trades_mixed_rules(self, tmp_path, monkeypatch):
        """3 trades with mixed rules → correct counts, accuracy, avg_return."""
        trades = [
            _make_trade(symbol="AAPL", return_pct=10.0, exit_rule="stop_loss"),
            _make_trade(symbol="TSLA", return_pct=3.0, exit_rule="stop_loss"),
            _make_trade(symbol="MSFT", return_pct=-5.0, exit_rule="trailing_stop"),
        ]
        trades_file = tmp_path / "closed_trades.json"
        trades_file.write_text(json.dumps(trades))

        ledger = ExitAutopsyLedger(str(trades_file))
        result = ledger.build()

        assert result["trade_count"] == 3
        assert "STOP_LOSS" in result["by_exit_rule"]
        assert "TRAILING_STOP" in result["by_exit_rule"]

        # stop_loss: 10%, 3% → both > 0.5%, so 2 wins, 0 losses
        stop_loss_stats = result["by_exit_rule"]["STOP_LOSS"]
        assert stop_loss_stats["wins"] == 2
        assert stop_loss_stats["losses"] == 0
        assert stop_loss_stats["total"] == 2
        assert stop_loss_stats["accuracy"] == ExitAutopsyLedger._bayesian_accuracy(2, 2)
        assert abs(stop_loss_stats["avg_return"] - 6.5) < 0.001

        # trailing_stop: -5% → 0 wins, 1 loss
        trailing_stop_stats = result["by_exit_rule"]["TRAILING_STOP"]
        assert trailing_stop_stats["wins"] == 0
        assert trailing_stop_stats["losses"] == 1
        assert trailing_stop_stats["total"] == 1
        assert abs(trailing_stop_stats["avg_return"] - (-5.0)) < 0.001

    def test_build_missing_exit_rule(self, tmp_path, monkeypatch):
        """Missing exit_rule bucketed as UNKNOWN."""
        trades = [
            _make_trade(symbol="AAPL", return_pct=5.0, exit_rule="stop_loss"),
            {"symbol": "TSLA", "return_pct": 3.0, "pnl_usd": 300.0},  # No exit_rule
        ]
        trades_file = tmp_path / "closed_trades.json"
        trades_file.write_text(json.dumps(trades))

        ledger = ExitAutopsyLedger(str(trades_file))
        result = ledger.build()

        assert "UNKNOWN" in result["by_exit_rule"]
        assert result["by_exit_rule"]["UNKNOWN"]["total"] == 1
        assert result["by_exit_rule"]["UNKNOWN"]["wins"] == 1

    def test_build_empty_exit_rule_string(self, tmp_path, monkeypatch):
        """Empty exit_rule string treated as UNKNOWN."""
        trades = [
            _make_trade(symbol="AAPL", return_pct=5.0, exit_rule=""),
        ]
        trades_file = tmp_path / "closed_trades.json"
        trades_file.write_text(json.dumps(trades))

        ledger = ExitAutopsyLedger(str(trades_file))
        result = ledger.build()

        assert "UNKNOWN" in result["by_exit_rule"]
        assert result["by_exit_rule"]["UNKNOWN"]["total"] == 1

    def test_build_all_same_rule(self, tmp_path, monkeypatch):
        """All trades with same rule → single bucket with correct stats."""
        trades = [
            _make_trade(symbol="AAPL", return_pct=10.0, exit_rule="take_profit"),
            _make_trade(symbol="TSLA", return_pct=5.0, exit_rule="take_profit"),
            _make_trade(symbol="MSFT", return_pct=15.0, exit_rule="take_profit"),
        ]
        trades_file = tmp_path / "closed_trades.json"
        trades_file.write_text(json.dumps(trades))

        ledger = ExitAutopsyLedger(str(trades_file))
        result = ledger.build()

        assert len(result["by_exit_rule"]) == 1
        assert "TAKE_PROFIT" in result["by_exit_rule"]

        take_profit_stats = result["by_exit_rule"]["TAKE_PROFIT"]
        assert take_profit_stats["total"] == 3
        assert take_profit_stats["wins"] == 3
        assert take_profit_stats["losses"] == 0
        assert abs(take_profit_stats["avg_return"] - 10.0) < 0.001

    def test_build_negative_returns_as_losses(self, tmp_path, monkeypatch):
        """Negative returns counted as losses (return_pct < 0.5 threshold)."""
        trades = [
            _make_trade(symbol="AAPL", return_pct=-10.0, exit_rule="stop_loss"),
            _make_trade(symbol="TSLA", return_pct=-0.5, exit_rule="stop_loss"),
        ]
        trades_file = tmp_path / "closed_trades.json"
        trades_file.write_text(json.dumps(trades))

        ledger = ExitAutopsyLedger(str(trades_file))
        result = ledger.build()

        stop_loss_stats = result["by_exit_rule"]["STOP_LOSS"]
        assert stop_loss_stats["losses"] == 2
        assert stop_loss_stats["wins"] == 0
        assert stop_loss_stats["total"] == 2

    def test_build_flat_returns_as_loss(self, tmp_path, monkeypatch):
        """Flat returns (0.3%) counted as loss (below 0.5 threshold)."""
        trades = [
            _make_trade(symbol="AAPL", return_pct=0.3, exit_rule="trailing_stop"),
        ]
        trades_file = tmp_path / "closed_trades.json"
        trades_file.write_text(json.dumps(trades))

        ledger = ExitAutopsyLedger(str(trades_file))
        result = ledger.build()

        trailing_stop_stats = result["by_exit_rule"]["TRAILING_STOP"]
        assert trailing_stop_stats["losses"] == 1
        assert trailing_stop_stats["wins"] == 0

    def test_build_threshold_boundary(self, tmp_path, monkeypatch):
        """Test exact threshold: 0.5% is loss, 0.51% is win."""
        trades = [
            _make_trade(symbol="AAPL", return_pct=0.5, exit_rule="stop_loss"),
            _make_trade(symbol="TSLA", return_pct=0.51, exit_rule="stop_loss"),
        ]
        trades_file = tmp_path / "closed_trades.json"
        trades_file.write_text(json.dumps(trades))

        ledger = ExitAutopsyLedger(str(trades_file))
        result = ledger.build()

        stop_loss_stats = result["by_exit_rule"]["STOP_LOSS"]
        # 0.5 is NOT > 0.5, so loss. 0.51 IS > 0.5, so win.
        assert stop_loss_stats["wins"] == 1
        assert stop_loss_stats["losses"] == 1


# ---------------------------------------------------------------------------
# Build autopsy brief tests
# ---------------------------------------------------------------------------


class TestBuildAutopsyBrief:
    """Test the build_autopsy_brief() method."""

    def test_brief_no_trades(self, tmp_path, monkeypatch):
        """No trades → empty string."""
        trades_file = tmp_path / "closed_trades.json"
        trades_file.write_text(json.dumps([]))

        ledger = ExitAutopsyLedger(str(trades_file))
        brief = ledger.build_autopsy_brief()

        assert brief == ""

    def test_brief_with_trades_format(self, tmp_path, monkeypatch):
        """Brief contains EXIT AUTOPSY header and footer."""
        trades = [
            _make_trade(symbol="AAPL", return_pct=10.0, exit_rule="stop_loss"),
        ]
        trades_file = tmp_path / "closed_trades.json"
        trades_file.write_text(json.dumps(trades))

        ledger = ExitAutopsyLedger(str(trades_file))
        brief = ledger.build_autopsy_brief()

        assert "=== EXIT AUTOPSY" in brief
        assert "=== END EXIT AUTOPSY ===" in brief

    def test_brief_contains_rule_stats(self, tmp_path, monkeypatch):
        """Brief shows win/loss counts and accuracy per rule."""
        trades = [
            _make_trade(symbol="AAPL", return_pct=10.0, exit_rule="stop_loss"),
            _make_trade(symbol="TSLA", return_pct=-5.0, exit_rule="stop_loss"),
        ]
        trades_file = tmp_path / "closed_trades.json"
        trades_file.write_text(json.dumps(trades))

        ledger = ExitAutopsyLedger(str(trades_file))
        brief = ledger.build_autopsy_brief()

        assert "STOP_LOSS" in brief
        assert "1W/1L" in brief  # 1 win, 1 loss

    def test_brief_shows_best_worst_rules(self, tmp_path, monkeypatch):
        """Brief shows best/worst rules when ≥3 trades per rule."""
        trades = [
            _make_trade(symbol="AAPL", return_pct=10.0, exit_rule="stop_loss"),
            _make_trade(symbol="TSLA", return_pct=5.0, exit_rule="stop_loss"),
            _make_trade(symbol="MSFT", return_pct=15.0, exit_rule="stop_loss"),
            _make_trade(symbol="NFLX", return_pct=-10.0, exit_rule="take_profit"),
            _make_trade(symbol="META", return_pct=-5.0, exit_rule="take_profit"),
            _make_trade(symbol="GOOG", return_pct=-15.0, exit_rule="take_profit"),
        ]
        trades_file = tmp_path / "closed_trades.json"
        trades_file.write_text(json.dumps(trades))

        ledger = ExitAutopsyLedger(str(trades_file))
        brief = ledger.build_autopsy_brief()

        assert "Best exit rule:" in brief
        assert "Worst exit rule:" in brief
        assert "STOP_LOSS" in brief  # Best (3/3 wins)
        assert "TAKE_PROFIT" in brief  # Worst (0/3 losses)

    def test_brief_skips_best_worst_when_insufficient_trades(self, tmp_path, monkeypatch):
        """Brief skips best/worst when < 3 trades per rule."""
        trades = [
            _make_trade(symbol="AAPL", return_pct=10.0, exit_rule="stop_loss"),
            _make_trade(symbol="TSLA", return_pct=-5.0, exit_rule="trailing_stop"),
        ]
        trades_file = tmp_path / "closed_trades.json"
        trades_file.write_text(json.dumps(trades))

        ledger = ExitAutopsyLedger(str(trades_file))
        brief = ledger.build_autopsy_brief()

        # Should not have best/worst (< 3 per rule)
        assert "Best exit rule:" not in brief
        assert "Worst exit rule:" not in brief
        # But should still show rules
        assert "STOP_LOSS" in brief
        assert "TRAILING_STOP" in brief

    def test_brief_sorts_by_total_trades(self, tmp_path, monkeypatch):
        """Rules sorted by total trades (descending) in brief."""
        trades = [
            _make_trade(symbol="A1", return_pct=10.0, exit_rule="stop_loss"),
            _make_trade(symbol="A2", return_pct=10.0, exit_rule="stop_loss"),
            _make_trade(symbol="A3", return_pct=10.0, exit_rule="stop_loss"),
            _make_trade(symbol="B1", return_pct=10.0, exit_rule="take_profit"),
            _make_trade(symbol="B2", return_pct=10.0, exit_rule="take_profit"),
        ]
        trades_file = tmp_path / "closed_trades.json"
        trades_file.write_text(json.dumps(trades))

        ledger = ExitAutopsyLedger(str(trades_file))
        brief = ledger.build_autopsy_brief()

        # STOP_LOSS (3 trades) should appear before TAKE_PROFIT (2 trades)
        stop_loss_pos = brief.find("STOP_LOSS")
        take_profit_pos = brief.find("TAKE_PROFIT")
        assert stop_loss_pos < take_profit_pos

    def test_brief_accuracy_color_hints(self, tmp_path, monkeypatch):
        """Brief includes accuracy percentages (good/neutral/poor hinting)."""
        trades = [
            _make_trade(symbol="AAPL", return_pct=10.0, exit_rule="stop_loss"),
        ]
        trades_file = tmp_path / "closed_trades.json"
        trades_file.write_text(json.dumps(trades))

        ledger = ExitAutopsyLedger(str(trades_file))
        brief = ledger.build_autopsy_brief()

        # Should show accuracy as percentage
        assert "%" in brief
        assert "STOP_LOSS" in brief


# ---------------------------------------------------------------------------
# Load trades tests
# ---------------------------------------------------------------------------


class TestLoadTrades:
    """Test the _load_trades() method."""

    def test_load_trades_nonexistent_file(self, tmp_path, monkeypatch):
        """Nonexistent file → empty list."""
        trades_file = tmp_path / "nonexistent.json"

        ledger = ExitAutopsyLedger(str(trades_file))
        trades = ledger._load_trades()

        assert trades == []

    def test_load_trades_malformed_json(self, tmp_path, monkeypatch):
        """Malformed JSON → empty list."""
        trades_file = tmp_path / "closed_trades.json"
        trades_file.write_text("{ invalid json }")

        ledger = ExitAutopsyLedger(str(trades_file))
        trades = ledger._load_trades()

        assert trades == []

    def test_load_trades_not_list(self, tmp_path, monkeypatch):
        """JSON dict (not list) → empty list."""
        trades_file = tmp_path / "closed_trades.json"
        trades_file.write_text(json.dumps({"trades": []}))

        ledger = ExitAutopsyLedger(str(trades_file))
        trades = ledger._load_trades()

        assert trades == []

    def test_load_trades_valid_list(self, tmp_path, monkeypatch):
        """Valid JSON list → returns list."""
        trades = [
            _make_trade(symbol="AAPL", return_pct=5.0),
            _make_trade(symbol="TSLA", return_pct=-3.0),
        ]
        trades_file = tmp_path / "closed_trades.json"
        trades_file.write_text(json.dumps(trades))

        ledger = ExitAutopsyLedger(str(trades_file))
        loaded = ledger._load_trades()

        assert len(loaded) == 2
        assert loaded[0]["symbol"] == "AAPL"
        assert loaded[1]["symbol"] == "TSLA"


# ---------------------------------------------------------------------------
# Edge cases and integration
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Test edge cases and corner scenarios."""

    def test_case_insensitive_rules(self, tmp_path, monkeypatch):
        """Exit rules normalized to uppercase."""
        trades = [
            _make_trade(symbol="AAPL", return_pct=5.0, exit_rule="stop_loss"),
            _make_trade(symbol="TSLA", return_pct=3.0, exit_rule="STOP_LOSS"),
            _make_trade(symbol="MSFT", return_pct=2.0, exit_rule="Stop_Loss"),
        ]
        trades_file = tmp_path / "closed_trades.json"
        trades_file.write_text(json.dumps(trades))

        ledger = ExitAutopsyLedger(str(trades_file))
        result = ledger.build()

        # All should be grouped under STOP_LOSS
        assert len(result["by_exit_rule"]) == 1
        assert result["by_exit_rule"]["STOP_LOSS"]["total"] == 3

    def test_whitespace_stripped_from_rules(self, tmp_path, monkeypatch):
        """Whitespace trimmed from exit rules."""
        trades = [
            _make_trade(symbol="AAPL", return_pct=5.0, exit_rule="  stop_loss  "),
        ]
        trades_file = tmp_path / "closed_trades.json"
        trades_file.write_text(json.dumps(trades))

        ledger = ExitAutopsyLedger(str(trades_file))
        result = ledger.build()

        assert "STOP_LOSS" in result["by_exit_rule"]

    def test_missing_return_pct_defaults_zero(self, tmp_path, monkeypatch):
        """Missing return_pct defaults to 0 (treated as loss)."""
        trades = [
            {"symbol": "AAPL", "pnl_usd": 0, "exit_rule": "stop_loss"},
        ]
        trades_file = tmp_path / "closed_trades.json"
        trades_file.write_text(json.dumps(trades))

        ledger = ExitAutopsyLedger(str(trades_file))
        result = ledger.build()

        stop_loss_stats = result["by_exit_rule"]["STOP_LOSS"]
        assert stop_loss_stats["losses"] == 1  # 0 is not > 0.5

    def test_many_trades_accuracy(self, tmp_path, monkeypatch):
        """Large number of trades computed accurately."""
        trades = [
            _make_trade(symbol=f"SYM{i}", return_pct=10.0, exit_rule="stop_loss")
            for i in range(50)
        ]
        trades_file = tmp_path / "closed_trades.json"
        trades_file.write_text(json.dumps(trades))

        ledger = ExitAutopsyLedger(str(trades_file))
        result = ledger.build()

        assert result["trade_count"] == 50
        stop_loss_stats = result["by_exit_rule"]["STOP_LOSS"]
        assert stop_loss_stats["total"] == 50
        assert stop_loss_stats["wins"] == 50
        assert stop_loss_stats["losses"] == 0
        expected_accuracy = ExitAutopsyLedger._bayesian_accuracy(50, 50)
        assert abs(stop_loss_stats["accuracy"] - expected_accuracy) < 0.001
