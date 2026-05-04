from __future__ import annotations

import re
from typing import Any, Dict, List


_TICKER_RE = re.compile(r"\b[A-Z]{1,5}\b")
_MOVE_RE = re.compile(r"\b(?:(up|down)\s+)?(\d+(?:\.\d+)?)%", re.IGNORECASE)
_COMMON_WORDS = {
    "A",
    "AN",
    "AND",
    "AS",
    "AT",
    "BY",
    "DID",
    "DO",
    "FOR",
    "HOW",
    "IN",
    "IRAN",
    "IT",
    "OF",
    "ON",
    "OR",
    "OUR",
    "THE",
    "TO",
    "TODAY",
    "TRUMP",
    "UP",
    "WAR",
    "WENT",
    "WHAT",
    "WHY",
    "WITH",
}

_REQUIRED_STAGES = [
    "scouts",
    "event_cards",
    "universe_filter",
    "collect",
    "shortlist",
    "deep_selection",
]


def _extract_tickers(question: str) -> List[str]:
    tickers = []
    seen = set()
    for token in _TICKER_RE.findall(question or ""):
        value = token.strip().upper()
        if not value or value in _COMMON_WORDS or value in seen:
            continue
        seen.add(value)
        tickers.append(value)
    return tickers


def _extract_observation(question: str, as_of_date: str) -> Dict[str, Any]:
    text = str(question or "")
    match = _MOVE_RE.search(text)
    if not match:
        return {"kind": "unspecified", "value": None, "date": as_of_date}

    direction = (match.group(1) or "").lower().strip()
    pct = match.group(2)
    if direction == "down":
        value = f"-{pct}%"
    else:
        value = f"+{pct}%"
    return {"kind": "price_move", "value": value, "date": as_of_date}


def _classify(question: str) -> Dict[str, str]:
    lower = str(question or "").lower()

    reverse_markers = (
        "why did we miss",
        "why didnt we miss",
        "why didn't we miss",
        "why didnt we flag",
        "why didn't we flag",
    )
    if any(marker in lower for marker in reverse_markers):
        return {
            "query_type": "reverse_forensic",
            "intent": "missed_alpha_diagnosis",
        }

    return {
        "query_type": "forward_scenario",
        "intent": "scenario_impact_analysis",
    }


def _required_dimensions(query_type: str) -> List[str]:
    if query_type == "reverse_forensic":
        return ["social", "technical", "macro", "filing", "options", "portfolio"]
    return ["social", "macro", "portfolio"]


def compile_question(*, question: str, as_of_date: str) -> Dict[str, Any]:
    classification = _classify(question)
    query_type = classification["query_type"]
    return {
        "query_type": query_type,
        "intent": classification["intent"],
        "raw_question": str(question or "").strip(),
        "target_entities": _extract_tickers(question),
        "observation": _extract_observation(question, as_of_date),
        "required_stages": list(_REQUIRED_STAGES),
        "required_dimensions": _required_dimensions(query_type),
        "manual_only": True,
    }
