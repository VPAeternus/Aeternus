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


def test_event_state_json_returns_backend_payload():
    payload = {
        "as_of_date": "2026-03-22",
        "triggered": True,
        "reasons": ["VIX jump 17.20%"],
        "metrics": {"vix_jump_pct": 17.2, "spy_move_pct": 0.4},
    }

    with patch("cli.commands.context.get_event_state", return_value=payload) as state_mock:
        result = runner.invoke(app, ["event-state", "--date", "2026-03-22", "--format", "json"])

    assert result.exit_code == 0
    assert '"triggered": true' in result.stdout
    assert '"VIX jump 17.20%"' in result.stdout
    state_mock.assert_called_once()


def test_event_state_rejects_invalid_format():
    result = runner.invoke(app, ["event-state", "--format", "yaml"])

    assert result.exit_code == 1
    assert "format must be table or json" in result.stdout


def test_event_state_table_rounds_metric_display_to_two_decimals():
    payload = {
        "as_of_date": "2026-03-22",
        "triggered": False,
        "reasons": [],
        "metrics": {"vix_jump_pct": 11.305075981208415, "spy_move_pct": -1.433577587250426},
    }

    with patch("cli.commands.context.get_event_state", return_value=payload):
        result = runner.invoke(app, ["event-state"])

    assert result.exit_code == 0
    assert "-1.43" in result.stdout
    assert "11.31" in result.stdout
    assert "-1.433577587250426" not in result.stdout
    assert "11.305075981208415" not in result.stdout
