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


def test_context_company_json_returns_backend_payload():
    payload = {
        "symbol": "AAPL",
        "as_of_date": "2026-03-22",
        "search_scope": "internal_only",
        "akg": {"found": True, "display_name": "Apple Inc"},
        "analysis": {"found": False},
        "dealflow": {
            "research_queue": {"found": False},
            "shortlist": {"found": False},
        },
        "portfolio": {"found": False},
        "x_feed": {"found": False},
        "known_gaps": [],
    }

    with patch("cli.commands.context.get_company_context", return_value=payload) as context_mock:
        result = runner.invoke(app, ["context", "company", "AAPL", "--date", "2026-03-22", "--format", "json"])

    assert result.exit_code == 0
    assert '"symbol": "AAPL"' in result.stdout
    assert '"search_scope": "internal_only"' in result.stdout
    context_mock.assert_called_once()


def test_context_company_rejects_invalid_format():
    result = runner.invoke(app, ["context", "company", "AAPL", "--format", "yaml"])

    assert result.exit_code == 1
    assert "format must be table or json" in result.stdout
