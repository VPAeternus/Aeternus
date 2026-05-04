"""System halt control artifact helpers."""

from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Optional

from tradingagents.default_config import DEFAULT_CONFIG

from .control_io import read_json_locked, write_json_locked

if TYPE_CHECKING:
    from tradingagents.alerting import AlertDispatcher

logger = logging.getLogger(__name__)


DEFAULT_SYSTEM_HALT_PATH = Path("eval_results") / "control" / "system_halt.json"


def system_halt_path(config: Optional[Dict[str, Any]] = None) -> Path:
    cfg = config or DEFAULT_CONFIG
    configured = str(cfg.get("operator_gateway_system_halt_path", "")).strip()
    if configured:
        return Path(configured)
    return DEFAULT_SYSTEM_HALT_PATH


def load_system_halt(config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    path = system_halt_path(config)
    payload = read_json_locked(
        path,
        default_factory=lambda: {
            "active": False,
            "scope": "HANDS_OFF",
            "reason": "",
            "set_at_utc": "",
            "set_by": "",
            "cleared_at_utc": "",
            "cleared_by": "",
            "updated_at_utc": "",
        },
    )
    return dict(payload)


def set_system_halt(
    *,
    reason: str,
    set_by: str = "operator",
    scope: str = "HANDS_OFF",
    config: Optional[Dict[str, Any]] = None,
    now: Optional[dt.datetime] = None,
    alert_dispatcher: Optional["AlertDispatcher"] = None,
) -> Dict[str, Any]:
    timestamp = _as_utc(now).isoformat()
    payload = {
        "active": True,
        "scope": str(scope or "HANDS_OFF").upper(),
        "reason": str(reason or "").strip(),
        "set_at_utc": timestamp,
        "set_by": str(set_by or "operator"),
        "cleared_at_utc": "",
        "cleared_by": "",
        "updated_at_utc": timestamp,
    }
    write_json_locked(system_halt_path(config), payload)
    logger.warning("System halt SET: %s (set_by=%s scope=%s)", reason, set_by, scope)
    if alert_dispatcher is not None:
        alert_dispatcher.system_halt_activated(reason=str(reason or ""), set_by=str(set_by or "operator"))
    return payload


def clear_system_halt(
    *,
    cleared_by: str = "operator",
    config: Optional[Dict[str, Any]] = None,
    now: Optional[dt.datetime] = None,
) -> Dict[str, Any]:
    current = load_system_halt(config)
    timestamp = _as_utc(now).isoformat()
    payload = {
        "active": False,
        "scope": str(current.get("scope") or "HANDS_OFF").upper(),
        "reason": str(current.get("reason") or ""),
        "set_at_utc": str(current.get("set_at_utc") or ""),
        "set_by": str(current.get("set_by") or ""),
        "cleared_at_utc": timestamp,
        "cleared_by": str(cleared_by or "operator"),
        "updated_at_utc": timestamp,
    }
    write_json_locked(system_halt_path(config), payload)
    logger.info("System halt CLEARED (cleared_by=%s)", cleared_by)
    return payload


def is_hands_off_active(config: Optional[Dict[str, Any]] = None) -> bool:
    payload = load_system_halt(config)
    return bool(payload.get("active")) and str(payload.get("scope", "")).upper() == "HANDS_OFF"


def _as_utc(value: Optional[dt.datetime]) -> dt.datetime:
    if value is None:
        return dt.datetime.now(dt.timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(dt.timezone.utc)
