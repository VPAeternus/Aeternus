"""Small formatting/parsing helpers for execution artifacts."""

from __future__ import annotations

import datetime as dt
from typing import Any, List, Optional


def as_string_list(raw: Any) -> List[str]:
    if isinstance(raw, list):
        values = [str(v).strip() for v in raw if str(v).strip()]
    else:
        values = []
    seen: List[str] = []
    for value in values:
        if value not in seen:
            seen.append(value)
    return seen


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def build_client_order_id(plan_id: str, symbol: str, ordinal: int) -> str:
    compact = str(plan_id).replace("-", "")[:10]
    ticker = str(symbol or "").upper().strip()[:8]
    return f"{compact}-{ticker}-{int(ordinal):03d}"


def parse_iso(raw: Any) -> Optional[dt.datetime]:
    text = str(raw or "").strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        value = dt.datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(dt.timezone.utc)


def parse_iso_or_now(raw: Any) -> dt.datetime:
    parsed = parse_iso(raw)
    if parsed is not None:
        return parsed
    return dt.datetime.now(dt.timezone.utc)
