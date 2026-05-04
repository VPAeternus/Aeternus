"""Portfolio drawdown health monitor.

Tracks portfolio equity vs. high-water mark and emits WARNING / ALERT levels
when drawdown thresholds are crossed.

This module is MONITORING ONLY — it never blocks, scales, or modifies orders.
The hedge engine (hedging.py) is responsible for portfolio protection via short
positions and bearish overlays. When drawdown thresholds are crossed the right
response is to review and fix the system, not freeze execution.

Alert levels:
  OK      — drawdown < 5% from HWM.
  WARNING — drawdown 5–15%. Logs warning; a post-mortem review should be triggered.
  ALERT   — drawdown >= 15%. Logs critical alert; immediate review required.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_WARNING_THRESHOLD_PCT: float = 5.0
_ALERT_THRESHOLD_PCT: float = 15.0

_DEFAULT_POSITIONS_PATH = "eval_results/paper_execution/positions.json"
_DEFAULT_HWM_PATH = "eval_results/control/hwm.json"


def compute_portfolio_equity(positions_path: str = _DEFAULT_POSITIONS_PATH) -> float:
    """Sum all open position market_value_usd as a proxy for portfolio mark value.

    Returns 0.0 on any failure — never raises.
    """
    try:
        data = json.loads(Path(positions_path).read_text())
        open_positions = data.get("open_positions", {})
        if not isinstance(open_positions, dict):
            return 0.0
        total = 0.0
        for pos in open_positions.values():
            if isinstance(pos, dict):
                mv = pos.get("market_value_usd")
                if mv is not None:
                    total += float(mv)
        return round(total, 2)
    except Exception as exc:
        logger.debug("compute_portfolio_equity failed: %s", exc)
        return 0.0


def check_drawdown_state(
    positions_path: str = _DEFAULT_POSITIONS_PATH,
    hwm_path: str = _DEFAULT_HWM_PATH,
) -> Dict[str, Any]:
    """Compute drawdown vs. HWM and return health monitor state.

    Returns a dict with keys:
        status         — "OK" | "WARNING" | "ALERT"
        drawdown_pct   — float, 0.0 if at/above HWM
        current_equity — float
        high_water_mark — float
        message        — human-readable explanation
        alert_triggered_at — ISO timestamp when ALERT first triggered, else None

    No execution actions are taken — this is informational only.
    The hedge engine handles portfolio protection.
    """
    current_equity = compute_portfolio_equity(positions_path=positions_path)

    try:
        hwm_data: Dict[str, Any] = json.loads(Path(hwm_path).read_text())
    except Exception as exc:
        logger.debug("check_drawdown_state: failed to load hwm.json: %s", exc)
        hwm_data = {}

    high_water_mark = float(hwm_data.get("high_water_mark", 0.0) or 0.0)

    # If HWM is zero or missing, treat as no drawdown (safe default)
    if high_water_mark <= 0.0:
        return {
            "status": "OK",
            "drawdown_pct": 0.0,
            "current_equity": current_equity,
            "high_water_mark": high_water_mark,
            "message": "No HWM baseline — monitor inactive.",
            "alert_triggered_at": None,
        }

    drawdown_pct = (
        (high_water_mark - current_equity) / high_water_mark * 100.0
        if current_equity < high_water_mark
        else 0.0
    )
    drawdown_pct = round(drawdown_pct, 4)

    alert_triggered_at: Optional[str] = hwm_data.get("alert_triggered_at")

    if drawdown_pct >= _ALERT_THRESHOLD_PCT:
        # Persist alert_triggered_at on first ALERT
        if not alert_triggered_at:
            alert_triggered_at = datetime.now(timezone.utc).isoformat()
            try:
                hwm_data["alert_triggered_at"] = alert_triggered_at
                Path(hwm_path).write_text(json.dumps(hwm_data, indent=2))
            except Exception as exc:
                logger.debug("check_drawdown_state: failed to persist alert_triggered_at: %s", exc)
        logger.critical(
            "DRAWDOWN ALERT: portfolio down %.1f%% from HWM $%.0f → review system, check hedge engine",
            drawdown_pct, high_water_mark,
        )
        return {
            "status": "ALERT",
            "drawdown_pct": drawdown_pct,
            "current_equity": current_equity,
            "high_water_mark": high_water_mark,
            "message": (
                f"ALERT: portfolio drawdown {drawdown_pct:.1f}% exceeds "
                f"{_ALERT_THRESHOLD_PCT:.0f}% threshold. Immediate system review required."
            ),
            "alert_triggered_at": alert_triggered_at,
        }

    if drawdown_pct >= _WARNING_THRESHOLD_PCT:
        logger.warning(
            "DRAWDOWN WARNING: portfolio down %.1f%% from HWM $%.0f → review open positions and signals",
            drawdown_pct, high_water_mark,
        )
        return {
            "status": "WARNING",
            "drawdown_pct": drawdown_pct,
            "current_equity": current_equity,
            "high_water_mark": high_water_mark,
            "message": (
                f"WARNING: portfolio drawdown {drawdown_pct:.1f}% exceeds "
                f"{_WARNING_THRESHOLD_PCT:.0f}% threshold. Review positions and signals."
            ),
            "alert_triggered_at": None,
        }

    # Clear any previously persisted alert_triggered_at when recovery occurs
    if alert_triggered_at:
        try:
            hwm_data.pop("alert_triggered_at", None)
            Path(hwm_path).write_text(json.dumps(hwm_data, indent=2))
        except Exception as exc:
            logger.debug("check_drawdown_state: failed to clear alert_triggered_at: %s", exc)

    return {
        "status": "OK",
        "drawdown_pct": drawdown_pct,
        "current_equity": current_equity,
        "high_water_mark": high_water_mark,
        "message": f"OK: drawdown {drawdown_pct:.1f}% is within acceptable range.",
        "alert_triggered_at": None,
    }


def update_hwm_equity(
    current_equity: float,
    hwm_path: str = _DEFAULT_HWM_PATH,
) -> None:
    """Update current_equity in hwm.json and raise HWM if a new high is reached.

    Silently ignores all failures — never crashes execution.
    """
    try:
        hwm_file = Path(hwm_path)
        try:
            hwm_data: Dict[str, Any] = json.loads(hwm_file.read_text())
        except Exception:
            hwm_data = {}

        hwm_data["current_equity"] = round(current_equity, 2)

        existing_hwm = float(hwm_data.get("high_water_mark", 0.0) or 0.0)
        if current_equity > existing_hwm:
            hwm_data["high_water_mark"] = round(current_equity, 2)
            hwm_data["updated_at_utc"] = datetime.now(timezone.utc).isoformat()

        hwm_file.write_text(json.dumps(hwm_data, indent=2))
    except Exception as exc:
        logger.debug("update_hwm_equity failed: %s", exc)
