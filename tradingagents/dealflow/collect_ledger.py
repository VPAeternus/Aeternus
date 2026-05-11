"""Retired old-funnel collect ledger helpers."""

from __future__ import annotations

from typing import Any, Dict


def write_collect_ledger_rows(*args: Any, **kwargs: Any) -> Dict[str, Any]:
    return {"status": "retired", "rows": []}


def build_evidence_gate_drop_metadata(*args: Any, **kwargs: Any) -> Dict[str, Dict[str, Any]]:
    return {}


def build_scout_handoff_drop_metadata(*args: Any, **kwargs: Any) -> Dict[str, Dict[str, Any]]:
    return {}
