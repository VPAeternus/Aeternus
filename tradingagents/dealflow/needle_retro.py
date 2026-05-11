"""Retired false-negative audit for the old pre-fundamental selection path."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict


def compute_needle_retro(*args: Any, **kwargs: Any) -> Dict[str, Any]:
    return {
        "status": "retired",
        "cycles_requested": int(kwargs.get("last", 0) or 0),
        "cycles_completed": 0,
        "cycles": [],
        "opportunities": [],
        "stage_summary": [],
    }
