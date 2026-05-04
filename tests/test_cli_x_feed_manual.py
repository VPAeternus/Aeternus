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


def test_x_feed_run_browser_routes_requested_pass_range():
    payload = {
        "date": "2026-03-22",
        "start_pass": 2,
        "end_pass": 3,
        "completed_passes": [2, 3],
        "failed_passes": [],
        "results": [
            {"pass_num": 2, "tickers_parsed": 4, "tickers_merged": 10},
            {"pass_num": 3, "tickers_parsed": 5, "tickers_merged": 15},
        ],
    }

    with patch("cli.commands.x_feed_manual.run_browser_passes", return_value=payload) as run_mock:
        result = runner.invoke(
            app,
            ["x-feed", "--run-browser", "--date", "2026-03-22", "--start-pass", "2", "--end-pass", "3"],
        )

    assert result.exit_code == 0
    assert "Browser run complete" in result.stdout
    assert "Completed passes: 2, 3" in result.stdout
    run_mock.assert_called_once()
