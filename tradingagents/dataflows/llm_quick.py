"""
Provider-aware quick LLM completion for simple prompt → text tasks.

Routes through claude_cli (zero cost). Used by dealflow connectors and
structural forces for pure-reasoning calls that don't need x_search.
"""
from __future__ import annotations

import json
import os
import subprocess
from typing import Optional


def quick_complete(
    prompt: str,
    max_tokens: int = 200,
    temperature: float = 0.0,
) -> Optional[str]:
    """
    Send a simple prompt and get text back via claude_cli.

    Returns the raw text response, or None on failure.
    """
    return _claude_cli_complete(prompt, max_tokens)


def _claude_cli_complete(prompt: str, max_tokens: int = 200) -> Optional[str]:
    """Invoke claude -p subprocess (zero marginal cost)."""
    cmd = [
        "claude", "-p",
        "--model", "claude-haiku-4-5-20251001",
        "--tools", "",
        "--permission-mode", "bypassPermissions",
        "--output-format", "json",
        "--no-session-persistence",
        "--max-tokens", str(max_tokens),
    ]
    try:
        proc = subprocess.run(
            cmd, input=prompt, capture_output=True, text=True, timeout=30,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None

    stdout = proc.stdout.strip()
    if not stdout:
        return None

    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return None

    if data.get("is_error"):
        return None

    return data.get("result", "")
