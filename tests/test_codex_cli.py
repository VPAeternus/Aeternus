"""Tests for ChatCodexCLI."""
from __future__ import annotations

import subprocess
import sys
import types
from pathlib import Path
import unittest.mock as mock

import pytest

if "chromadb" not in sys.modules:
    _stub = types.ModuleType("chromadb")
    _stub.__path__ = []
    _stub.Client = None
    _cfg_stub = types.ModuleType("chromadb.config")
    _cfg_stub.Settings = type("Settings", (), {})
    sys.modules["chromadb"] = _stub
    sys.modules["chromadb.config"] = _cfg_stub

from langchain_core.messages import HumanMessage

from tradingagents.dataflows.codex_cli import ChatCodexCLI


def test_codex_cli_generates_from_output_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    def fake_tempdir(*args, **kwargs):
        class _Ctx:
            def __enter__(self):
                return str(tmp_path)

            def __exit__(self, exc_type, exc, tb):
                return False
        return _Ctx()

    def fake_run(cmd, **kwargs):
        output_idx = cmd.index("-o")
        out_path = Path(cmd[output_idx + 1])
        out_path.write_text("BUY")
        proc = mock.MagicMock()
        proc.returncode = 0
        proc.stdout = ""
        proc.stderr = ""
        return proc

    monkeypatch.setattr("tradingagents.dataflows.codex_cli.tempfile.TemporaryDirectory", fake_tempdir)
    monkeypatch.setattr(subprocess, "run", fake_run)

    llm = ChatCodexCLI()
    result = llm._generate([HumanMessage(content="Rate AAPL")])
    assert result.generations[0].message.content == "BUY"


def test_codex_cli_timeout(monkeypatch: pytest.MonkeyPatch):
    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=180)

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(TimeoutError, match="timed out"):
        ChatCodexCLI(timeout=180)._generate([HumanMessage(content="hello")])


def test_trading_graph_codex_cli_provider(monkeypatch: pytest.MonkeyPatch):
    import os
    import tradingagents.graph.trading_graph as tg_module
    from tradingagents.dataflows.codex_cli import ChatCodexCLI
    from tradingagents.default_config import DEFAULT_CONFIG

    for key in (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GOOGLE_API_KEY",
        "MINIMAX_API_KEY",
        "OPENAI_AUTH_TOKEN",
        "ANTHROPIC_AUTH_TOKEN",
    ):
        monkeypatch.delenv(key, raising=False)

    monkeypatch.setattr(tg_module, "GraphSetup", mock.MagicMock())
    monkeypatch.setattr(tg_module, "Propagator", mock.MagicMock())
    monkeypatch.setattr(tg_module, "Reflector", mock.MagicMock())
    monkeypatch.setattr(tg_module, "SignalProcessor", mock.MagicMock())
    monkeypatch.setattr(tg_module, "SectorContext", mock.MagicMock())
    monkeypatch.setattr(tg_module, "TrackRecord", mock.MagicMock())
    monkeypatch.setattr(tg_module, "AeternusScorer", mock.MagicMock())
    monkeypatch.setattr(tg_module, "ThesisChecker", mock.MagicMock())
    monkeypatch.setattr(tg_module, "ConditionalLogic", mock.MagicMock())
    monkeypatch.setattr(tg_module, "FinancialSituationMemory", mock.MagicMock())
    monkeypatch.setattr(tg_module, "TradeMemory", mock.MagicMock())
    monkeypatch.setattr(tg_module, "set_config", mock.MagicMock())
    monkeypatch.setattr(os, "makedirs", mock.MagicMock())
    monkeypatch.setattr(tg_module, "ToolNode", mock.MagicMock())

    config = dict(DEFAULT_CONFIG)
    config["llm_provider"] = "codex_cli"
    config["quick_think_provider"] = "codex_cli"
    graph = tg_module.TradingAgentsGraph(config=config)

    assert isinstance(graph.deep_thinking_llm, ChatCodexCLI)
    assert isinstance(graph.quick_thinking_llm, ChatCodexCLI)
