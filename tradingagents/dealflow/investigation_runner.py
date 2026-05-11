"""Scout-handoff-only investigation runner."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


def run_investigation(*, investigation_packet: Dict[str, Any], as_of_date: str) -> Dict[str, Any]:
    root = Path("eval_results") / "deal_flow" / str(as_of_date)
    handoff_path = root / "final_dealflow_tickers.json"
    handoff = json.loads(handoff_path.read_text()) if handoff_path.exists() else {}
    target_entities = [str(x).upper() for x in investigation_packet.get("target_entities", []) or []]
    tickers = {str(x).upper() for x in handoff.get("tickers", []) or []}
    matched = [symbol for symbol in target_entities if symbol in tickers]
    return {
        "status": "COMPLETE" if matched else "PARTIAL",
        "coverage_status": "COMPLETE" if matched else "PARTIAL",
        "matched_entities": matched,
        "summary": "Matched entities against scout ticker handoff only.",
        "evidence_missing": [] if matched else ["scout_handoff"],
        "manual_gap_fill_requests": [],
    }
