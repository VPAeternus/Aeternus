"""Negative-constraint overlays for triage BLOCK actions."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from tradingagents.default_config import DEFAULT_CONFIG

from .canonical_json import canonical_hash
from .control_io import read_json_locked, update_json_locked


DEFAULT_CONSTRAINTS_PATH = Path("eval_results") / "deal_flow" / "ui" / "negative_constraints.json"


def constraints_path(config: Optional[Dict[str, Any]] = None) -> Path:
    cfg = config or DEFAULT_CONFIG
    configured = str(cfg.get("operator_gateway_negative_constraints_path", "")).strip()
    if configured:
        return Path(configured)
    return DEFAULT_CONSTRAINTS_PATH


def load_constraints(config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return dict(
        read_json_locked(
            constraints_path(config),
            default_factory=lambda: {"updated_at_utc": "", "items": []},
        )
    )


def add_symbol_theme_constraint(
    *,
    symbol: str,
    thesis_tags: Sequence[str],
    reason: str = "",
    created_by: str = "operator",
    ttl_days: Optional[int] = None,
    config: Optional[Dict[str, Any]] = None,
    now: Optional[dt.datetime] = None,
) -> Dict[str, Any]:
    cfg = config or DEFAULT_CONFIG
    ttl = int(ttl_days or cfg.get("operator_gateway_negative_constraint_ttl_days", 14))
    created_at = _as_utc(now)
    expires_at = created_at + dt.timedelta(days=max(1, ttl))
    normalized_symbol = str(symbol or "").upper().strip()
    normalized_tags = sorted(
        {
            str(tag or "").strip().lower()
            for tag in thesis_tags
            if str(tag or "").strip()
        }
    )
    entry = {
        "constraint_id": canonical_hash(
            {
                "symbol": normalized_symbol,
                "thesis_tags": normalized_tags,
                "created_at_utc": created_at.isoformat(),
                "expires_at_utc": expires_at.isoformat(),
            }
        )[:16],
        "scope": "SYMBOL_THEME",
        "symbol": normalized_symbol,
        "thesis_tags": normalized_tags,
        "reason": str(reason or "").strip(),
        "created_by": str(created_by or "operator"),
        "created_at_utc": created_at.isoformat(),
        "expires_at_utc": expires_at.isoformat(),
        "active": True,
    }

    def _update(payload: Any) -> Dict[str, Any]:
        current = payload if isinstance(payload, dict) else {}
        items = list(current.get("items", [])) if isinstance(current.get("items", []), list) else []
        items.append(entry)
        return {"updated_at_utc": created_at.isoformat(), "items": items}

    update_json_locked(constraints_path(cfg), _update, default_factory=lambda: {"updated_at_utc": "", "items": []})
    return entry


def list_active_constraints(
    config: Optional[Dict[str, Any]] = None,
    now: Optional[dt.datetime] = None,
) -> List[Dict[str, Any]]:
    as_of = _as_utc(now)
    payload = load_constraints(config)
    active: List[Dict[str, Any]] = []
    for raw in payload.get("items", []) if isinstance(payload.get("items"), list) else []:
        if not isinstance(raw, dict):
            continue
        if not bool(raw.get("active", True)):
            continue
        expires = _parse_utc(str(raw.get("expires_at_utc") or ""))
        if expires and expires < as_of:
            continue
        active.append(dict(raw))
    return active


def check_symbol_theme_suppression(
    *,
    symbol: str,
    thesis_tags: Sequence[str],
    config: Optional[Dict[str, Any]] = None,
    now: Optional[dt.datetime] = None,
) -> Tuple[bool, Optional[Dict[str, Any]]]:
    normalized_symbol = str(symbol or "").upper().strip()
    normalized_tags = {
        str(tag or "").strip().lower()
        for tag in thesis_tags
        if str(tag or "").strip()
    }
    for row in list_active_constraints(config=config, now=now):
        if str(row.get("scope") or "").upper() != "SYMBOL_THEME":
            continue
        if str(row.get("symbol") or "").upper().strip() != normalized_symbol:
            continue
        blocked_tags = {
            str(tag or "").strip().lower()
            for tag in row.get("thesis_tags", [])
            if str(tag or "").strip()
        }
        if not blocked_tags:
            return True, row
        if normalized_tags & blocked_tags:
            return True, row
    return False, None


def _as_utc(value: Optional[dt.datetime]) -> dt.datetime:
    if value is None:
        return dt.datetime.now(dt.timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(dt.timezone.utc)


def _parse_utc(raw: str) -> Optional[dt.datetime]:
    text = str(raw or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)
