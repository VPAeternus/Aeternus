"""Broker order status normalization helpers."""

from __future__ import annotations

from typing import Any, Dict, List


def extract_broker_orders(snapshot: Any) -> List[Dict[str, Any]]:
    if isinstance(snapshot, list):
        return [row for row in snapshot if isinstance(row, dict)]
    if isinstance(snapshot, dict):
        for key in ("orders", "results", "items", "data", "broker_orders"):
            value = snapshot.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
    return []


def normalize_broker_status(raw_status: str) -> str:
    status = str(raw_status or "").strip().upper().replace("-", "_").replace(" ", "_")
    if not status:
        return ""
    if "PARTIAL" in status:
        return "PARTIALLY_FILLED"
    if "FILLED" in status:
        return "FILLED"
    if "CANCEL" in status:
        return "CANCELED"
    if "REJECT" in status:
        return "REJECTED"
    if "REPLACE" in status:
        return "REPLACED"
    if "EXPIRE" in status or status == "DONE_FOR_DAY":
        return "EXPIRED"
    if status in {"NEW", "ACCEPTED", "PENDING_NEW", "SUBMITTED"}:
        return "SUBMITTED"
    return status


def safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def count_outbox_statuses(rows: List[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        status = str(row.get("status") or "UNKNOWN").upper().strip()
        counts[status] = counts.get(status, 0) + 1
    return counts


def dedupe_list(values: List[str]) -> List[str]:
    seen: List[str] = []
    for value in values:
        text = str(value).strip()
        if text and text not in seen:
            seen.append(text)
    return seen
