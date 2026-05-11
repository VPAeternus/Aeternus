"""Retired contribution reports for old pre-fundamental scoring."""

from __future__ import annotations

from typing import Any, Dict


def build_family_contribution_report(*args: Any, **kwargs: Any) -> Dict[str, Any]:
    return {
        "status": "retired",
        "reason": "Dealflow no longer calculates pre-fundamental contribution weights.",
    }
