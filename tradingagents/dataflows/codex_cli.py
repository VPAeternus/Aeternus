"""
Codex CLI vendor — wraps `codex exec` as a LangChain BaseChatModel.
Enables GPT-based autonomous pipeline runs via local Codex authentication.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, List, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult


class ChatCodexCLI(BaseChatModel):
    """LangChain-compatible LLM backed by `codex exec` subprocess."""

    model: str = "gpt-5.4"
    reasoning_effort: str = "high"
    timeout: int = 180
    binary: str = "codex"

    @property
    def _llm_type(self) -> str:
        return "codex-cli"

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

    def _extract_system(self, messages: List[BaseMessage]) -> str:
        for message in messages:
            if isinstance(message, SystemMessage):
                return message.content if isinstance(message.content, str) else ""
        return ""

    def _format_messages(self, messages: List[BaseMessage]) -> str:
        non_system = [m for m in messages if not isinstance(m, SystemMessage)]
        if len(non_system) == 1 and isinstance(non_system[0], HumanMessage):
            content = non_system[0].content
            return content if isinstance(content, str) else str(content)
        parts = []
        for message in non_system:
            content = message.content if isinstance(message.content, str) else str(message.content)
            if isinstance(message, HumanMessage):
                parts.append(f"Human: {content}")
            elif isinstance(message, AIMessage):
                parts.append(f"Assistant: {content}")
            else:
                parts.append(content)
        body = "\n\n".join(parts)
        if system:
            return f"System: {system}\n\n{body}"
        return body

    def _invoke_cli(self, prompt: str, system: str = "") -> str:
        env = dict(os.environ)
        env.pop("CLAUDECODE", None)
        env.pop("CODEX_DISABLE_MCP", None)

        with tempfile.TemporaryDirectory(prefix="codex-chat-") as temp_dir:
            output_path = Path(temp_dir) / "codex_last_message.txt"
            cmd = [
                self.binary,
                "exec",
                "-C",
                temp_dir,
                "--skip-git-repo-check",
                "--ephemeral",
                "-m",
                self.model,
                "-c",
                f'model_reasoning_effort="{self.reasoning_effort}"',
                "-o",
                str(output_path),
                "-",
            ]
            if system:
                prompt = f"{system}\n\n{prompt}"
            try:
                proc = subprocess.run(
                    cmd,
                    input=prompt,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout,
                    env=env,
                )
            except subprocess.TimeoutExpired as exc:
                raise TimeoutError(f"codex exec timed out after {self.timeout}s") from exc
            except FileNotFoundError as exc:
                raise RuntimeError(
                    "codex CLI not found. Install with: npm install -g @openai/codex"
                ) from exc

            if proc.returncode != 0:
                stderr = str(proc.stderr or "").strip()
                raise RuntimeError(f"codex exec error: {stderr or proc.returncode}")

            if not output_path.is_file():
                raise RuntimeError("codex exec completed without output message file")

            text = output_path.read_text().strip()
            if not text:
                raise RuntimeError("codex exec returned no final message")
            return text
