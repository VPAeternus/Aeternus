"""Small locked JSON IO helpers for execution artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tradingagents.dealflow.control_io import read_json_locked, write_json_locked


def load_json(path: Path, default: Any = None) -> Any:
    return read_json_locked(path, default_factory=lambda: default)


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json_locked(path, payload)
