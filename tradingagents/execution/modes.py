"""Execution mode and environment helpers split from graph.paper_execution."""

from __future__ import annotations

import os

from .constants import EXECUTION_MODE_ALPACA_PAPER, EXECUTION_MODE_PAPER


def normalize_execution_mode(mode: str) -> str:
    text = str(mode or EXECUTION_MODE_PAPER).strip().lower().replace("_", "-")
    if text == "alpaca":
        return EXECUTION_MODE_ALPACA_PAPER
    return text


def env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return bool(default)
    return str(raw).strip().lower() in {"1", "true", "yes", "y", "on"}


def clamp_float(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))
