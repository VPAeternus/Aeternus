"""Manual Grok earnings/options scout artifact helpers."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional


def _artifact_path(as_of_date: str) -> str:
    return os.path.join("eval_results", "deal_flow", f"earnings_options_scout_{as_of_date}.json")


def load_earnings_options_scout(as_of_date: str) -> Optional[Dict[str, Any]]:
    path = _artifact_path(as_of_date)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r") as f:
            payload = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    return payload if isinstance(payload, dict) else None


def save_earnings_options_scout(as_of_date: str, data: Dict[str, Any]) -> str:
    path = _artifact_path(as_of_date)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    return path


def scan_manual_earnings_options_setups(as_of_date: str) -> Dict[str, Any]:
    payload = load_earnings_options_scout(as_of_date) or {}
    raw_entries = payload.get("trending", [])
    if not isinstance(raw_entries, list):
        raw_entries = []

    promoted: List[Dict[str, Any]] = []
    promoted_symbols: List[str] = []
    signals: List[Dict[str, Any]] = []
    for entry in raw_entries:
        if not isinstance(entry, dict):
            continue
        symbol = str(entry.get("ticker", "") or "").upper().strip()
        if not symbol:
            continue
        promoted_entry = {
            "ticker": symbol,
            "buzz_rank": int(entry.get("buzz_rank", len(promoted) + 1) or len(promoted) + 1),
            "sentiment": str(entry.get("sentiment", "NEUTRAL") or "NEUTRAL").upper(),
            "velocity": str(entry.get("velocity", "STEADY") or "STEADY").upper(),
            "catalyst": str(entry.get("catalyst", "") or "").strip(),
            "sector": str(entry.get("sector", "Unclassified Equity") or "Unclassified Equity").strip(),
            "earnings_date": str(entry.get("earnings_date", "") or "").strip() or None,
            "setup_type": str(entry.get("setup_type", "earnings_options") or "earnings_options").strip(),
            "flow_summary": str(entry.get("flow_summary", "") or "").strip() or None,
            "accounts_flagged": int(entry.get("accounts_flagged", 0) or 0),
        }
        promoted.append(promoted_entry)
        promoted_symbols.append(symbol)
        signals.append(
            {
                "symbol": symbol,
                "source": "earnings_options",
                "delta_kind": "earnings_options",
                "direction": "BULLISH" if promoted_entry["sentiment"] in {"BULLISH", "VERY_BULLISH"} else promoted_entry["sentiment"],
                "raw_strength": max(0.0, 1.0 - (float(promoted_entry["buzz_rank"]) - 1.0) / 30.0),
                "confidence_score": min(1.0, 0.55 + 0.10 * max(promoted_entry["accounts_flagged"], 0)),
                "tags": ["earnings_options", promoted_entry["velocity"].lower()],
            }
        )

    artifact_path = _artifact_path(as_of_date)
    return {
        "promoted_count": len(promoted_symbols),
        "promoted_symbols": promoted_symbols,
        "promoted": promoted,
        "signals": signals,
        "artifact_path": artifact_path,
        "source_status": "OK" if promoted_symbols else "NO_DATA",
    }
