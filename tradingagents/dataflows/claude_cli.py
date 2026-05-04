"""
Claude CLI vendor — wraps `claude -p` as a LangChain BaseChatModel (S-057).
Enables autonomous pipeline runs at zero marginal API cost.
Requires Claude Code CLI installed and authenticated.
"""
from __future__ import annotations
import json
import os
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
            "--tools", "",
            "--permission-mode", "bypassPermissions",
            "--output-format", "json",
        ]
        if self.fallback_model and self.fallback_model != self.model:
            cmd += ["--fallback-model", self.fallback_model]
        if self.session_id:
            cmd += ["--session-id", self.session_id]
        else:
            cmd += ["--no-session-persistence"]
        if system:
            cmd += ["--append-system-prompt", system]

        # Unset CLAUDECODE so subprocess doesn't think it's a nested session.
        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

        try:
            proc = subprocess.run(
                cmd,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                env=env,
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
