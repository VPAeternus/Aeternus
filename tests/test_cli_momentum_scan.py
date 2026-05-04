import sys
import types
from unittest.mock import patch

from typer.testing import CliRunner

if "chromadb" not in sys.modules or not hasattr(sys.modules.get("chromadb", None), "__path__"):
    _stub = types.ModuleType("chromadb")
    _stub.__path__ = []
    _stub.Client = None
    _config_stub = types.ModuleType("chromadb.config")
    _config_stub.Settings = type("Settings", (), {})
    sys.modules["chromadb"] = _stub
    sys.modules["chromadb.config"] = _config_stub

from cli.main import app


runner = CliRunner()


def test_momentum_scan_table_shows_portfolio_backtest_columns():
    stock_signal = {
        "ticker": "AAPL",
        "state": "long",
        "regime": "ABOVE_BOTH",
        "accel_percentile": 0.91,
        "days_out": 0,
        "invested_pct": 94.0,
        "close": 220.0,
    }
    index_signal = {
        "ticker": "QQQ",
        "rth": True,
        "overnight": True,
        "active_leg": "leg2_stay_long",
        "vix": 18.5,
        "regime": "accel_up",
        "close": 500.0,
    }
    metrics = {
        "strategy_return_pct": 12.34,
        "buy_hold_return_pct": 10.01,
        "strategy_cagr_pct": 8.76,
        "sharpe_strat": 0.55,
        "max_dd_strat": -22.11,
    }

    with (
        patch("tradingagents.phase_engine.data_engine.load", return_value={"fake": "frame"}),
        patch("tradingagents.phase_engine.cc_overbought.CCOverboughtEngine.get_signal", return_value=stock_signal),
        patch("tradingagents.phase_engine.index_overlay.IndexOverlayEngine.get_signal", return_value=index_signal),
        patch("cli.commands.technical._build_cc_portfolio_metrics", return_value=metrics, create=True),
    ):
        result = runner.invoke(
            app,
            ["momentum-scan", "--tickers", "AAPL", "--tickers", "QQQ"],
            env={"COLUMNS": "200"},
        )

    assert result.exit_code == 0
    assert "CC OVERBOUGHT" in result.stdout
    assert "AAPL" in result.stdout
    assert "12.34%" in result.stdout
    assert "10.01%" in result.stdout
    assert "8.76%" in result.stdout
    assert "0.55" in result.stdout
    assert "-22.11%" in result.stdout


def test_momentum_scan_table_omits_invested_and_close_columns_for_compact_readability():
    stock_signal = {
        "ticker": "AAPL",
        "state": "long",
        "regime": "ABOVE_BOTH",
        "accel_percentile": 0.91,
        "days_out": 0,
        "invested_pct": 94.0,
        "close": 220.0,
    }

    with (
        patch("tradingagents.phase_engine.data_engine.load", return_value={"fake": "frame"}),
        patch("tradingagents.phase_engine.cc_overbought.CCOverboughtEngine.get_signal", return_value=stock_signal),
        patch("cli.commands.technical._build_cc_portfolio_metrics", return_value={}, create=True),
    ):
        result = runner.invoke(
            app,
            ["momentum-scan", "--tickers", "AAPL"],
            env={"COLUMNS": "200"},
        )

    assert result.exit_code == 0
    assert "Invested %" not in result.stdout
    assert "Close" not in result.stdout
