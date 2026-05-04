"""Portfolio drift computation for alignment pulse in operator bootstrap."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any, Dict, Optional


def compute_portfolio_drift(
    *,
    config: Dict[str, Any],
    now: dt.datetime,
    sensitivity: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """Compute deterministic portfolio drift percentage from broker/model allocation artifacts."""
    model_path = Path(str(config.get("operator_gateway_model_allocation_path", "")).strip())
    broker_path = Path(str(config.get("operator_gateway_broker_allocation_path", "")).strip())
    if not model_path.exists() or not broker_path.exists():
        return _unknown("Connect broker sync to activate alignment pulse.")

    model_payload = _safe_read_json(model_path)
    broker_payload = _safe_read_json(broker_path)
    if not model_payload or not broker_payload:
        return _unknown("Allocation snapshots unavailable.")

    model_weights = _extract_weights(model_payload)
    broker_weights = _extract_weights(broker_payload)
    if not model_weights or not broker_weights:
        return _unknown("Allocation snapshots missing weights.")

    last_sync = _resolve_snapshot_time(broker_payload, broker_path, now)
    stale_seconds = float(config.get("operator_gateway_portfolio_sync_stale_seconds", 1200.0))
    if (now - last_sync).total_seconds() > stale_seconds:
        return _unknown(
            "Broker sync is stale. Refresh account holdings.",
            last_sync_utc=last_sync.isoformat(),
        )

    drift_pct = _total_variation_distance_pct(model_weights, broker_weights)
    aligned_threshold = float(
        (sensitivity or {}).get(
            "amber_threshold_pct",
            config.get("operator_gateway_drift_aligned_threshold_pct", 5.0),
        )
    )
    disconnected_threshold = float(
        (sensitivity or {}).get(
            "red_threshold_pct",
            config.get("operator_gateway_drift_disconnected_threshold_pct", 15.0),
        )
    )

    if drift_pct <= aligned_threshold:
        status = "ALIGNED"
        message = "You are fully aligned with Aeternus."
    elif drift_pct <= disconnected_threshold:
        status = "DRIFTING"
        message = "Your portfolio is drifting from Aeternus logic."
    else:
        status = "DISCONNECTED"
        message = "Significant divergence detected. Review mirror alignment."

    return {
        "portfolio_drift_pct": round(float(drift_pct), 4),
        "portfolio_drift_status": status,
        "portfolio_last_sync_utc": last_sync.isoformat(),
        "portfolio_drift_message": message,
    }


def build_symbol_alignment_delta(
    *,
    config: Dict[str, Any],
    symbol: str,
) -> Dict[str, Any]:
    """Build symbol-level side-by-side weight comparison for mirror preview."""
    model_path = Path(str(config.get("operator_gateway_model_allocation_path", "")).strip())
    broker_path = Path(str(config.get("operator_gateway_broker_allocation_path", "")).strip())
    if not model_path.exists() or not broker_path.exists():
        return {
            "available": False,
            "current_weight_pct": None,
            "target_weight_pct": None,
            "delta_weight_pct": None,
        }
    model_payload = _safe_read_json(model_path)
    broker_payload = _safe_read_json(broker_path)
    model_weights = _extract_weights(model_payload)
    broker_weights = _extract_weights(broker_payload)
    if not model_weights and not broker_weights:
        return {
            "available": False,
            "current_weight_pct": None,
            "target_weight_pct": None,
            "delta_weight_pct": None,
        }
    key = str(symbol or "").upper().strip()
    target = float(model_weights.get(key, 0.0) * 100.0)
    current = float(broker_weights.get(key, 0.0) * 100.0)
    delta = target - current
    return {
        "available": True,
        "current_weight_pct": round(current, 4),
        "target_weight_pct": round(target, 4),
        "delta_weight_pct": round(delta, 4),
    }


def build_drift_impact(
    *,
    config: Dict[str, Any],
    now: dt.datetime,
    sensitivity: Optional[Dict[str, float]] = None,
    max_items: int = 8,
) -> Dict[str, Any]:
    """Build ranked drift-impact list with explicit non-model exposure detection."""
    model_path = Path(str(config.get("operator_gateway_model_allocation_path", "")).strip())
    broker_path = Path(str(config.get("operator_gateway_broker_allocation_path", "")).strip())
    if not model_path.exists() or not broker_path.exists():
        return {
            "available": False,
            "portfolio_drift_pct": None,
            "portfolio_drift_status": "UNKNOWN",
            "last_sync_utc": "",
            "non_model_exposure_count": 0,
            "non_model_symbols": [],
            "items": [],
            "message": "Connect broker sync to view drift impact.",
        }

    model_payload = _safe_read_json(model_path)
    broker_payload = _safe_read_json(broker_path)
    model_weights = _extract_weights(model_payload)
    broker_weights = _extract_weights(broker_payload)
    if not model_weights and not broker_weights:
        return {
            "available": False,
            "portfolio_drift_pct": None,
            "portfolio_drift_status": "UNKNOWN",
            "last_sync_utc": "",
            "non_model_exposure_count": 0,
            "non_model_symbols": [],
            "items": [],
            "message": "Allocation snapshots missing weights.",
        }

    drift = compute_portfolio_drift(config=config, now=now, sensitivity=sensitivity)
    non_model_floor_pct = float(config.get("operator_gateway_non_model_min_pct", 1.0))
    universe = set(model_weights.keys()) | set(broker_weights.keys())
    rows = []
    non_model_symbols = []
    for symbol in sorted(universe):
        current_pct = float(broker_weights.get(symbol, 0.0) * 100.0)
        target_pct = float(model_weights.get(symbol, 0.0) * 100.0)
        delta = target_pct - current_pct
        if target_pct <= 0.0 and current_pct >= non_model_floor_pct:
            classification = "NON_MODEL_EXPOSURE"
            non_model_symbols.append(symbol)
        elif delta > 0.0:
            classification = "UNDERWEIGHT_VS_MODEL"
        elif delta < 0.0:
            classification = "OVERWEIGHT_VS_MODEL"
        else:
            classification = "ALIGNED"
        rows.append(
            {
                "symbol": symbol,
                "current_weight_pct": round(current_pct, 4),
                "target_weight_pct": round(target_pct, 4),
                "delta_weight_pct": round(delta, 4),
                "classification": classification,
                "drift_abs_pct": round(abs(delta), 4),
            }
        )
    rows.sort(key=lambda item: float(item.get("drift_abs_pct", 0.0)), reverse=True)
    top = rows[: max(1, int(max_items))]
    for row in top:
        row.pop("drift_abs_pct", None)
    return {
        "available": True,
        "portfolio_drift_pct": drift.get("portfolio_drift_pct"),
        "portfolio_drift_status": str(drift.get("portfolio_drift_status") or "UNKNOWN"),
        "last_sync_utc": str(drift.get("portfolio_last_sync_utc") or ""),
        "non_model_exposure_count": len(non_model_symbols),
        "non_model_symbols": sorted(non_model_symbols),
        "items": top,
        "message": str(drift.get("portfolio_drift_message") or ""),
    }


def _unknown(message: str, *, last_sync_utc: str = "") -> Dict[str, Any]:
    return {
        "portfolio_drift_pct": None,
        "portfolio_drift_status": "UNKNOWN",
        "portfolio_last_sync_utc": str(last_sync_utc or ""),
        "portfolio_drift_message": str(message or "Alignment unavailable."),
    }


def _safe_read_json(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text())
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _extract_weights(payload: Dict[str, Any]) -> Dict[str, float]:
    weights = payload.get("weights")
    if isinstance(weights, dict):
        out: Dict[str, float] = {}
        for symbol, raw in weights.items():
            key = str(symbol or "").upper().strip()
            if not key:
                continue
            try:
                value = float(raw)
            except Exception:
                continue
            out[key] = max(0.0, value)
        return _normalize(out)

    allocations = payload.get("allocations")
    if isinstance(allocations, list):
        out = {}
        for row in allocations:
            if not isinstance(row, dict):
                continue
            key = str(row.get("symbol") or row.get("asset") or "").upper().strip()
            if not key:
                continue
            raw_weight = row.get("weight")
            try:
                value = float(raw_weight)
            except Exception:
                continue
            out[key] = max(0.0, value)
        return _normalize(out)

    positions = payload.get("positions")
    if isinstance(positions, list):
        notionals: Dict[str, float] = {}
        total = 0.0
        for row in positions:
            if not isinstance(row, dict):
                continue
            key = str(row.get("symbol") or row.get("asset") or "").upper().strip()
            if not key:
                continue
            raw_notional = row.get("market_value_usd", row.get("notional_usd"))
            try:
                notional = abs(float(raw_notional))
            except Exception:
                continue
            if notional <= 0.0:
                continue
            notionals[key] = notionals.get(key, 0.0) + notional
            total += notional
        if total <= 0.0:
            return {}
        return {key: value / total for key, value in notionals.items()}

    return {}


def _normalize(weights: Dict[str, float]) -> Dict[str, float]:
    total = float(sum(max(0.0, value) for value in weights.values()))
    if total <= 0.0:
        return {}
    return {key: max(0.0, value) / total for key, value in weights.items()}


def _total_variation_distance_pct(model: Dict[str, float], broker: Dict[str, float]) -> float:
    universe = set(model.keys()) | set(broker.keys())
    if not universe:
        return 0.0
    diff = 0.0
    for symbol in universe:
        diff += abs(float(model.get(symbol, 0.0)) - float(broker.get(symbol, 0.0)))
    # TVD in [0,1]; convert to percentage points.
    return 50.0 * diff


def _resolve_snapshot_time(payload: Dict[str, Any], path: Path, now: dt.datetime) -> dt.datetime:
    candidates = [
        payload.get("as_of_utc"),
        payload.get("last_synced_at_utc"),
        payload.get("updated_at_utc"),
        payload.get("snapshot_time_utc"),
    ]
    for raw in candidates:
        if not raw:
            continue
        try:
            parsed = dt.datetime.fromisoformat(str(raw))
        except Exception:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        else:
            parsed = parsed.astimezone(dt.timezone.utc)
        return parsed
    mtime = dt.datetime.fromtimestamp(path.stat().st_mtime, tz=dt.timezone.utc)
    return mtime if mtime <= now else now
