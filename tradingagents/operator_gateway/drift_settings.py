"""Persistence and validation for operator drift sensitivity settings."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from tradingagents.dealflow.control_io import read_json_locked, write_json_locked


def default_drift_sensitivity(config: Dict[str, Any]) -> Dict[str, float]:
    amber = float(config.get("operator_gateway_drift_aligned_threshold_pct", 5.0))
    red = float(config.get("operator_gateway_drift_disconnected_threshold_pct", 15.0))
    if red <= amber:
        red = amber + 1.0
    return {
        "amber_threshold_pct": round(amber, 4),
        "red_threshold_pct": round(red, 4),
    }


def load_drift_sensitivity(config: Dict[str, Any]) -> Dict[str, float]:
    path = _settings_path(config)
    defaults = default_drift_sensitivity(config)
    payload = read_json_locked(path, default_factory=lambda: dict(defaults))
    if not isinstance(payload, dict):
        return defaults
    amber = _as_float(payload.get("amber_threshold_pct"), defaults["amber_threshold_pct"])
    red = _as_float(payload.get("red_threshold_pct"), defaults["red_threshold_pct"])
    return normalize_drift_sensitivity({"amber_threshold_pct": amber, "red_threshold_pct": red})


def save_drift_sensitivity(config: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, float]:
    normalized = normalize_drift_sensitivity(payload)
    write_json_locked(_settings_path(config), normalized)
    return normalized


def normalize_drift_sensitivity(payload: Dict[str, Any]) -> Dict[str, float]:
    amber = max(0.5, min(40.0, _as_float(payload.get("amber_threshold_pct"), 5.0)))
    red = max(1.0, min(80.0, _as_float(payload.get("red_threshold_pct"), 15.0)))
    if red <= amber:
        red = min(80.0, amber + 1.0)
    return {
        "amber_threshold_pct": round(amber, 4),
        "red_threshold_pct": round(red, 4),
    }


def _settings_path(config: Dict[str, Any]) -> Path:
    return Path(
        str(
            config.get(
                "operator_gateway_drift_settings_path",
                "eval_results/control/drift_sensitivity.json",
            )
        ).strip()
    )


def _as_float(raw: Any, default: float) -> float:
    try:
        return float(raw)
    except Exception:
        return float(default)

