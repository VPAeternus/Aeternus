# Task: S-057

## Tier
sonnet

## Summary
Build a `claude_cli` LLM vendor that wraps `claude -p` (Claude Code CLI print mode) as a LangChain `BaseChatModel`. Enables fully autonomous pipeline runs (`aeternus workflow-run --mode auto`) outside of a chat session, at zero marginal API cost, using Claude Code subscription auth. No API keys required.

## Context

### The Problem
The two existing pipeline modes both have friction:
- **API mode** (MiniMax/OpenAI): works as a cron job, costs $0.05–0.15/ticker
- **Session mode**: zero cost but requires a Claude Code chat session open

### The Solution
`claude -p` (Claude Code's headless "print" mode) is a full LLM runtime accessible via subprocess. No API keys — uses Claude Code subscription auth. Returns JSON with `result`, `is_error`, `total_cost_usd`. Supports model selection, system prompts, session IDs, and timeout.

Adding a LangChain-compatible `ChatClaudeCLI` class wires this into the existing LangGraph pipeline with zero changes to agents.

### Key CLI flags used
```bash
echo "$PROMPT" | claude -p \
  --model claude-sonnet-4-6 \
  --fallback-model claude-haiku-4-5-20251001 \
  --tools "" \
  --no-session-persistence \
  --permission-mode bypassPermissions \
  --output-format json
```
- `--tools ""` — pure LLM mode (no file system access; agents fetch their own data)
- `--no-session-persistence` — stateless; state lives in LangGraph not the LLM
- `--output-format json` — parseable `{"result": "...", "is_error": false, ...}`

---

## Requirements

### 1. New file: `tradingagents/dataflows/claude_cli.py`

```python
"""
Claude CLI vendor — wraps `claude -p` as a LangChain BaseChatModel (S-057).
Enables autonomous pipeline runs at zero marginal API cost.
Requires Claude Code CLI installed and authenticated.
"""
from __future__ import annotations
import json
import subprocess
from typing import Any, List, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult


class ChatClaudeCLI(BaseChatModel):
    """LangChain-compatible LLM backed by `claude -p` subprocess."""

    model: str = "claude-sonnet-4-6"
    fallback_model: str = "claude-haiku-4-5-20251001"
    timeout: int = 120
    session_id: Optional[str] = None  # if set, uses --session-id (multi-turn context)

    @property
    def _llm_type(self) -> str:
        return "claude-cli"

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        system = self._extract_system(messages)
        prompt = self._format_messages(messages)
        text = self._invoke_cli(prompt, system)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text))])

    # ── helpers ──────────────────────────────────────────────────────────────

    def _extract_system(self, messages: List[BaseMessage]) -> str:
        """Return content of first SystemMessage, or ''."""
        for m in messages:
            if isinstance(m, SystemMessage):
                return m.content if isinstance(m.content, str) else ""
        return ""

    def _format_messages(self, messages: List[BaseMessage]) -> str:
        """
        Format non-system messages as a conversation string for stdin.
        Single HumanMessage → just its content (most common case).
        Multi-turn → "Human: ...\n\nAssistant: ...\n\nHuman: ..."
        """
        non_system = [m for m in messages if not isinstance(m, SystemMessage)]
        if len(non_system) == 1 and isinstance(non_system[0], HumanMessage):
            content = non_system[0].content
            return content if isinstance(content, str) else str(content)
        parts = []
        for m in non_system:
            content = m.content if isinstance(m.content, str) else str(m.content)
            if isinstance(m, HumanMessage):
                parts.append(f"Human: {content}")
            elif isinstance(m, AIMessage):
                parts.append(f"Assistant: {content}")
            else:
                parts.append(content)
        return "\n\n".join(parts)

    def _invoke_cli(self, prompt: str, system: str = "") -> str:
        """Spawn `claude -p` subprocess and return the result text."""
        cmd = [
            "claude", "-p",
            "--model", self.model,
            "--fallback-model", self.fallback_model,
            "--tools", "",
            "--permission-mode", "bypassPermissions",
            "--output-format", "json",
        ]
        if self.session_id:
            cmd += ["--session-id", self.session_id]
        else:
            cmd += ["--no-session-persistence"]
        if system:
            cmd += ["--append-system-prompt", system]

        try:
            proc = subprocess.run(
                cmd,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired as e:
            raise TimeoutError(f"claude -p timed out after {self.timeout}s") from e
        except FileNotFoundError as e:
            raise RuntimeError(
                "claude CLI not found. Install with: npm install -g @anthropic-ai/claude-code"
            ) from e

        stdout = proc.stdout.strip()
        if not stdout:
            stderr = proc.stderr.strip()
            raise RuntimeError(f"claude -p returned no output. stderr: {stderr}")

        try:
            data = json.loads(stdout)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"claude -p non-JSON output: {stdout[:200]}") from e

        if data.get("is_error"):
            raise RuntimeError(f"claude -p error: {data.get('result', 'unknown error')}")

        return data.get("result", "")
```

### 2. Update `tradingagents/graph/trading_graph.py`

Read the file fully first. The LLM instantiation is in `_setup_llms()` (or equivalent). Add a new `elif` branch for `claude_cli` following the exact same pattern as the `openai` branch.

**Location:** In the provider dispatch block (after the `xai` branch, before the final `else`):

```python
elif provider == "claude_cli":
    from tradingagents.dataflows.claude_cli import ChatClaudeCLI
    self.deep_thinking_llm = ChatClaudeCLI(
        model=self.config.get("claude_cli_deep_model", "claude-sonnet-4-6"),
        fallback_model=self.config.get("claude_cli_fallback_model", "claude-haiku-4-5-20251001"),
        timeout=int(self.config.get("claude_cli_timeout", 120)),
    )
    self.quick_thinking_llm = ChatClaudeCLI(
        model=self.config.get("claude_cli_quick_model", "claude-haiku-4-5-20251001"),
        fallback_model=self.config.get("claude_cli_fallback_model", "claude-haiku-4-5-20251001"),
        timeout=int(self.config.get("claude_cli_timeout", 60)),
    )
```

**Also:** In the API key validation block, add `claude_cli` to the no-key-required list:
```python
if provider not in ("ollama", "minimax", "claude_cli") and not api_key:
    raise ValueError(...)
```

**Also:** In the `quick_think_provider` override block (line ~200), handle `claude_cli`:
```python
elif _quick_provider == "claude_cli":
    from tradingagents.dataflows.claude_cli import ChatClaudeCLI
    self.quick_thinking_llm = ChatClaudeCLI(
        model=self.config.get("claude_cli_quick_model", "claude-haiku-4-5-20251001"),
        timeout=int(self.config.get("claude_cli_timeout", 60)),
    )
```

### 3. Update `tradingagents/default_config.py`

Add after the existing LLM provider keys:
```python
# Claude CLI vendor (S-057) — subprocess wrapper for `claude -p`
# Requires: npm install -g @anthropic-ai/claude-code + claude login
"claude_cli_deep_model": "claude-sonnet-4-6",
"claude_cli_quick_model": "claude-haiku-4-5-20251001",
"claude_cli_fallback_model": "claude-haiku-4-5-20251001",
"claude_cli_timeout": 120,  # seconds per subprocess call
```

### 4. New file: `tests/test_claude_cli.py`

Mock `subprocess.run` — no real `claude` binary required. Use `monkeypatch`.

Tests:
1. `_llm_type` returns `"claude-cli"`
2. Single `HumanMessage` → prompt is just the message content (no "Human:" prefix)
3. Multi-turn messages → formatted as "Human: ...\n\nAssistant: ...\n\nHuman: ..."
4. `SystemMessage` extracted → passed as `--append-system-prompt`, NOT in formatted prompt
5. Successful subprocess response → `AIMessage` with correct content
6. `is_error: true` in JSON → raises `RuntimeError`
7. `subprocess.TimeoutExpired` → raises `TimeoutError` (not subprocess exception)
8. `FileNotFoundError` (claude not installed) → raises `RuntimeError` with install hint
9. Empty stdout → raises `RuntimeError`
10. `session_id` set → `--session-id` in cmd, `--no-session-persistence` NOT in cmd
11. No `session_id` → `--no-session-persistence` in cmd, no `--session-id`
12. `trading_graph.py`: provider `"claude_cli"` → no API key validation error
13. `default_config.py`: all 4 new keys present

---

## Files to Touch
- `tradingagents/dataflows/claude_cli.py` — NEW
- `tradingagents/graph/trading_graph.py` — add `claude_cli` branch + skip key validation
- `tradingagents/default_config.py` — 4 new config keys
- `tests/test_claude_cli.py` — NEW

---

## Acceptance Criteria
- [ ] `ChatClaudeCLI._llm_type == "claude-cli"`
- [ ] Single HumanMessage → clean prompt (no "Human:" wrapper)
- [ ] SystemMessage → `--append-system-prompt`, excluded from prompt body
- [ ] `is_error: true` → `RuntimeError`
- [ ] TimeoutExpired → `TimeoutError` with clear message
- [ ] FileNotFoundError → `RuntimeError` with install hint
- [ ] `session_id` controls `--session-id` vs `--no-session-persistence` correctly
- [ ] `provider == "claude_cli"` → no API key required, no validation error
- [ ] `provider == "claude_cli"` → `deep_thinking_llm` and `quick_thinking_llm` are `ChatClaudeCLI`
- [ ] All 13 tests pass
- [ ] `python3 -m pytest tests/test_claude_cli.py -v` — all pass
- [ ] `python3 -m pytest tests/ -v --ignore=tests/test_cli_dealflow.py --ignore=tests/test_cli_hedging.py --ignore=tests/test_cli_score.py -q 2>&1 | tail -5` — no regressions

---

## Usage (after implementation)

```bash
# .env
AETERNUS_LLM_PROVIDER=claude_cli
AETERNUS_DEEP_MODEL=claude-sonnet-4-6
AETERNUS_QUICK_MODEL=claude-haiku-4-5-20251001

# Run full pipeline as cron job — zero API credits
aeternus workflow-run --mode auto --profile daily --execution-mode alpaca-paper
```

---

## Notes for Implementer
- Read `trading_graph.py` fully before touching it — understand the full provider dispatch block including the `quick_think_provider` override
- The `BaseChatModel` Pydantic fields (`model`, `fallback_model`, etc.) need `model_config = ConfigDict(arbitrary_types_allowed=True)` if Pydantic v2 is in use — check existing `ChatXAI` or `ChatAnthropic` usage for the pattern
- Do NOT add `claude_cli` to the `api_key` env var lookup — it has no key
- Karpathy rules: surgical changes only. Do not refactor the provider block, just add the new `elif`

## Status
done

## Priority
HIGH — unlocks autonomous nightly pipeline runs at zero marginal cost
