import json
import sys
import types

import pytest
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


def test_research_analysts_status(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "tradingagents.graph.codex_research_bridge.get_manual_bundle_readiness",
        lambda **kwargs: {
            "ready": False,
            "required_analysts": ["market", "social", "news", "fundamentals"],
            "completed_analysts": ["market"],
            "missing_analysts": ["social", "news", "fundamentals"],
        },
    )
    result = runner.invoke(
        app,
        ["research-analysts", "--status", "--provider", "grok_manual", "--ticker", "AAPL", "--date", "2026-03-09"],
    )
    assert result.exit_code == 0, result.stdout
    assert "INCOMPLETE" in result.stdout
    assert "Missing analysts: social, news, fundamentals" in result.stdout


def test_research_analysts_ingest(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "tradingagents.graph.codex_research_bridge.ingest_manual_analyst",
        lambda **kwargs: {
            "artifact_path": "/tmp/aapl-market.json",
            "prompt_path": "/tmp/aapl-market.txt",
        },
    )
    result = runner.invoke(
        app,
        [
            "research-analysts",
            "--ingest",
            "--provider",
            "grok_manual",
            "--ticker",
            "AAPL",
            "--date",
            "2026-03-09",
            "--analyst",
            "market",
        ],
        input=json.dumps({"report_markdown": "## Thesis\nGood"}),
    )
    assert result.exit_code == 0, result.stdout
    assert "/tmp/aapl-market.json" in result.stdout


def test_research_analysts_generate_prints_all_prompts():
    result = runner.invoke(
        app,
        ["research-analysts", "--generate", "--provider", "grok_manual", "--ticker", "AAPL", "--date", "2026-03-09"],
    )
    assert result.exit_code == 0, result.stdout
    assert "AAPL 2026-03-09" in result.stdout
    assert "MARKET analyst".lower() in result.stdout.lower() or "market" in result.stdout.lower()
    assert "fundamentals" in result.stdout.lower()


def test_research_analysts_rejects_unsupported_provider():
    result = runner.invoke(
        app,
        ["research-analysts", "--status", "--provider", "gemini", "--ticker", "AAPL"],
    )
    assert result.exit_code == 1
    assert "Only grok_manual is supported in v1." in result.stdout
