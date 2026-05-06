"""Write filing-confirmed theme acceleration rows back to AKG."""

from __future__ import annotations

import json
from typing import Any, Iterable

from tradingagents.dealflow.theme_aliases import canonicalize_theme_id, load_theme_aliases


def write_theme_acceleration_to_akg(akg: Any, rows: Iterable[dict[str, Any]], as_of_date: str) -> int:
    """Write LLM/fundamental theme acceleration output rows into AKG nodes.

    Returns count of rows attempted with valid ticker. AKG enforces evidence-required
    score zeroing and rescan/research-visibility thresholds.
    """
    count = 0
    aliases = load_theme_aliases()
    for row in rows:
        ticker = str(row.get("ticker", "")).upper().strip()
        if not ticker:
            continue
        payload = {
            "as_of_date": as_of_date,
            "primary_theme": canonicalize_theme_id(row.get("primary_theme"), aliases),
            "secondary_themes": [canonicalize_theme_id(theme, aliases) for theme in _parse_list(row.get("secondary_themes") or [])],
            "theme_role": row.get("theme_role"),
            "theme_confidence": row.get("theme_confidence"),
            "theme_driver_type": row.get("theme_driver_type"),
            "theme_momentum": row.get("theme_momentum"),
            "theme_evidence": _parse_list(row.get("theme_evidence") or []),
            "theme_acceleration_score": _intish(row.get("theme_acceleration_score")),
            "theme_acceleration_reason": "filing_theme_acceleration",
        }
        akg.update_theme_acceleration_signal(ticker, payload)
        _write_theme_edges(akg, ticker, payload)
        count += 1
    return count


def _write_theme_edges(akg: Any, ticker: str, payload: dict[str, Any]) -> None:
    confidence = _theme_confidence_to_float(payload.get("theme_confidence"))
    primary = str(payload.get("primary_theme") or "").strip()
    if primary:
        _ensure_theme_node(akg, primary)
        akg.add_edge(
            source=ticker,
            target=primary,
            relationship="catalyst_beneficiary",
            confidence=confidence,
            evidence_source="filing_theme_acceleration",
        )
    for theme_id in payload.get("secondary_themes") or []:
        secondary = str(theme_id or "").strip()
        if not secondary or secondary == primary:
            continue
        _ensure_theme_node(akg, secondary)
        akg.add_edge(
            source=ticker,
            target=secondary,
            relationship="theme_exposure",
            confidence=confidence,
            evidence_source="filing_theme_acceleration",
        )


def _ensure_theme_node(akg: Any, theme_id: str) -> None:
    existing = getattr(akg, "_nodes", {}).get(theme_id)
    if existing is None:
        akg.add_node(theme_id, node_type="theme")
    else:
        existing["node_type"] = "theme"


def _theme_confidence_to_float(raw: Any) -> float:
    text = str(raw or "").lower().strip()
    return {"high": 0.9, "medium": 0.65, "low": 0.35, "none": 0.1, "": 0.1}.get(text, 0.5)


def _parse_list(raw: Any) -> list[str]:
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    text = str(raw or "").strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
        except Exception:
            pass
    if "|" in text:
        return [part.strip() for part in text.split("|") if part.strip()]
    return [text]


def _intish(raw: Any) -> int:
    try:
        return int(float(raw))
    except Exception:
        return 0
