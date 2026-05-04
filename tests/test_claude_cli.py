"""Tests for ChatClaudeCLI (S-057) — all subprocess calls are mocked."""
from __future__ import annotations

import json
import subprocess
import sys
import types
import unittest.mock as mock

import pytest

# Stub chromadb before any tradingagents import (Python 3.14 pydantic v1 incompatibility)
if "chromadb" not in sys.modules:
    _stub = types.ModuleType("chromadb")
    _stub.__path__ = []
    _stub.Client = None
    _cfg_stub = types.ModuleType("chromadb.config")
    _cfg_stub.Settings = type("Settings", (), {})
    sys.modules["chromadb"] = _stub
    sys.modules["chromadb.config"] = _cfg_stub

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from tradingagents.dataflows.claude_cli import ChatClaudeCLI


# ── helpers ──────────────────────────────────────────────────────────────────

def _ok_proc(result_text: str) -> mock.MagicMock:
    """Return a completed subprocess mock with a valid JSON body."""
    p = mock.MagicMock()
    p.stdout = json.dumps({"result": result_text, "is_error": False})
    p.stderr = ""
    p.returncode = 0
    return p


def _err_proc(error_msg: str) -> mock.MagicMock:
    """Return a completed subprocess mock with is_error = True."""
    p = mock.MagicMock()
    p.stdout = json.dumps({"result": error_msg, "is_error": True})
    p.stderr = ""
    p.returncode = 1
    return p


# ── Test 1: _llm_type ────────────────────────────────────────────────────────

def test_llm_type():
    llm = ChatClaudeCLI()
    assert llm._llm_type == "claude-cli"


# ── Test 2: Single HumanMessage → clean prompt (no "Human:" wrapper) ─────────

def test_single_human_message_no_prefix():
    llm = ChatClaudeCLI()
    msgs = [HumanMessage(content="What is the P/E ratio?")]
    result = llm._format_messages(msgs)
    assert result == "What is the P/E ratio?"
    assert not result.startswith("Human:")


# ── Test 3: Multi-turn formatting ────────────────────────────────────────────

def test_multi_turn_formatting():
    llm = ChatClaudeCLI()
    msgs = [
        HumanMessage(content="Hello"),
        AIMessage(content="Hi there"),
        HumanMessage(content="What's the news?"),
    ]
    result = llm._format_messages(msgs)
    assert result == "Human: Hello\n\nAssistant: Hi there\n\nHuman: What's the news?"


# ── Test 4: SystemMessage extracted → passed to CLI, excluded from prompt ────

def test_system_message_extracted_not_in_prompt(monkeypatch):
    captured_cmd = []

    def fake_run(cmd, **kwargs):
        captured_cmd.extend(cmd)
        return _ok_proc("analysis result")

    monkeypatch.setattr(subprocess, "run", fake_run)

    llm = ChatClaudeCLI()
    msgs = [
        SystemMessage(content="You are a financial analyst."),
        HumanMessage(content="Analyze AAPL"),
    ]
    result = llm._generate(msgs)

    # System prompt passed via --append-system-prompt
    assert "--append-system-prompt" in captured_cmd
    sys_idx = captured_cmd.index("--append-system-prompt")
    assert captured_cmd[sys_idx + 1] == "You are a financial analyst."

    # The prompt sent to stdin must NOT contain the system text
    # (verified by checking _format_messages excludes SystemMessages)
    non_system_prompt = llm._format_messages(msgs)
    assert "You are a financial analyst." not in non_system_prompt
    assert non_system_prompt == "Analyze AAPL"

    # Result is correct
    assert result.generations[0].message.content == "analysis result"


# ── Test 5: Successful subprocess response → AIMessage with correct content ──

def test_successful_response(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: _ok_proc("Strong BUY signal"))

    llm = ChatClaudeCLI()
    msgs = [HumanMessage(content="Rate NVDA")]
    result = llm._generate(msgs)

    assert len(result.generations) == 1
    msg = result.generations[0].message
    assert isinstance(msg, AIMessage)
    assert msg.content == "Strong BUY signal"


# ── Test 6: is_error: true in JSON → raises RuntimeError ─────────────────────

def test_is_error_raises_runtime_error(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: _err_proc("authentication failed"))

    llm = ChatClaudeCLI()
    msgs = [HumanMessage(content="Analyze TSLA")]
    with pytest.raises(RuntimeError, match="claude -p error"):
        llm._generate(msgs)


# ── Test 7: TimeoutExpired → raises TimeoutError ──────────────────────────────

def test_timeout_raises_timeout_error(monkeypatch):
    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=120)

    monkeypatch.setattr(subprocess, "run", fake_run)

    llm = ChatClaudeCLI(timeout=120)
    msgs = [HumanMessage(content="slow query")]
    with pytest.raises(TimeoutError, match="timed out after 120s"):
        llm._generate(msgs)


# ── Test 8: FileNotFoundError → RuntimeError with install hint ───────────────

def test_file_not_found_raises_runtime_with_hint(monkeypatch):
    def fake_run(cmd, **kwargs):
        raise FileNotFoundError("claude not found")

    monkeypatch.setattr(subprocess, "run", fake_run)

    llm = ChatClaudeCLI()
    msgs = [HumanMessage(content="query")]
    with pytest.raises(RuntimeError, match="npm install"):
        llm._generate(msgs)


# ── Test 9: Empty stdout → raises RuntimeError ───────────────────────────────

def test_empty_stdout_raises_runtime_error(monkeypatch):
    p = mock.MagicMock()
    p.stdout = ""
    p.stderr = "some error"
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: p)

    llm = ChatClaudeCLI()
    msgs = [HumanMessage(content="query")]
    with pytest.raises(RuntimeError, match="no output"):
        llm._generate(msgs)


# ── Test 10: session_id set → --session-id in cmd, --no-session-persistence absent

def test_session_id_uses_session_flag(monkeypatch):
    captured_cmd = []

    def fake_run(cmd, **kwargs):
        captured_cmd.extend(cmd)
        return _ok_proc("ok")

    monkeypatch.setattr(subprocess, "run", fake_run)

    llm = ChatClaudeCLI(session_id="abc123")
    msgs = [HumanMessage(content="query")]
    llm._generate(msgs)

    assert "--session-id" in captured_cmd
    sid_idx = captured_cmd.index("--session-id")
    assert captured_cmd[sid_idx + 1] == "abc123"
    assert "--no-session-persistence" not in captured_cmd


# ── Test 11: No session_id → --no-session-persistence in cmd, no --session-id ─

def test_no_session_id_uses_no_persistence_flag(monkeypatch):
    captured_cmd = []

    def fake_run(cmd, **kwargs):
        captured_cmd.extend(cmd)
        return _ok_proc("ok")

    monkeypatch.setattr(subprocess, "run", fake_run)

    llm = ChatClaudeCLI()  # session_id=None by default
    msgs = [HumanMessage(content="query")]
    llm._generate(msgs)

    assert "--no-session-persistence" in captured_cmd
    assert "--session-id" not in captured_cmd


# ── Test 12: provider "claude_cli" → no API key validation error ─────────────

@pytest.mark.parametrize("provider_name", ["claude_cli", "codex_cli"])
def test_financial_situation_memory_local_cli_provider_disables_embeddings_without_keys(
    monkeypatch, provider_name
):
    import tradingagents.agents.utils.memory as memory_module

    for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "XAI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(key, raising=False)

    monkeypatch.setattr(memory_module, "_CHROMADB_AVAILABLE", False)

    memory = memory_module.FinancialSituationMemory(
        "test_memory",
        {"llm_provider": provider_name, "backend_url": provider_name},
    )

    assert memory.embed_type == "none"
    assert memory.embed_client is None


def test_trading_graph_claude_cli_no_api_key_required(monkeypatch):
    """TradingAgentsGraph with provider=claude_cli must not raise a key validation error."""
    import os

    # Ensure no API keys are present for claude_cli
    for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "XAI_API_KEY", "GOOGLE_API_KEY",
                 "OPENAI_AUTH_TOKEN", "ANTHROPIC_AUTH_TOKEN", "MINIMAX_OAUTH_TOKEN",
                 "MINIMAX_API_KEY"):
        monkeypatch.delenv(key, raising=False)

    # Patch out the heavy downstream constructors
    import tradingagents.graph.trading_graph as tg_module

    # Stub GraphSetup and other heavy components
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

    # Stub set_config and os.makedirs
    monkeypatch.setattr(tg_module, "set_config", mock.MagicMock())
    monkeypatch.setattr(os, "makedirs", mock.MagicMock())

    # Stub ToolNode
    monkeypatch.setattr(tg_module, "ToolNode", mock.MagicMock())

    from tradingagents.default_config import DEFAULT_CONFIG
    config = dict(DEFAULT_CONFIG)
    config["llm_provider"] = "claude_cli"
    config["quick_think_provider"] = "claude_cli"
    config["claude_cli_deep_model"] = "claude-sonnet-4-6"
    config["claude_cli_quick_model"] = "claude-haiku-4-5-20251001"
    config["claude_cli_fallback_model"] = "claude-haiku-4-5-20251001"
    config["claude_cli_timeout"] = 120

    # Should not raise ValueError about missing API key
    graph = tg_module.TradingAgentsGraph(config=config)

    assert isinstance(graph.deep_thinking_llm, ChatClaudeCLI)
    assert isinstance(graph.quick_thinking_llm, ChatClaudeCLI)


# ── Test 13: default_config.py has all 4 new keys ────────────────────────────

def test_default_config_has_claude_cli_keys():
    from tradingagents.default_config import DEFAULT_CONFIG

    assert "claude_cli_deep_model" in DEFAULT_CONFIG
    assert "claude_cli_quick_model" in DEFAULT_CONFIG
    assert "claude_cli_fallback_model" in DEFAULT_CONFIG
    assert "claude_cli_timeout" in DEFAULT_CONFIG

    assert DEFAULT_CONFIG["claude_cli_deep_model"] == "claude-sonnet-4-6"
    assert DEFAULT_CONFIG["claude_cli_quick_model"] == "claude-haiku-4-5-20251001"
    assert DEFAULT_CONFIG["claude_cli_fallback_model"] == "claude-haiku-4-5-20251001"
    assert DEFAULT_CONFIG["claude_cli_timeout"] == 120
