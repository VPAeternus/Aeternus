"""Triage intent/receipt control-plane primitives."""

from __future__ import annotations

import datetime as dt
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from tradingagents.default_config import DEFAULT_CONFIG

from .canonical_json import canonical_hash
from .control_io import read_json_locked, update_json_locked
from .negative_constraints import add_symbol_theme_constraint
from .system_halt import is_hands_off_active


DEFAULT_TRIAGE_INTENTS_PATH = Path("eval_results") / "deal_flow" / "ui" / "triage_intents.json"
DEFAULT_TRIAGE_RECEIPTS_PATH = Path("eval_results") / "deal_flow" / "ui" / "triage_receipts.json"


INTENT_STATUS_CREATED = "CREATED"
INTENT_STATUS_CANCELED = "CANCELED_BY_UNDO"
INTENT_STATUS_CONSUMED = "CONSUMED"
INTENT_STATUS_EXPIRED_WINDOW = "EXPIRED_MISSED_WINDOW"
INTENT_STATUS_EXPIRED_PRICE_SLIP = "EXPIRED_PRICE_SLIP"
INTENT_STATUS_REJECTED_STALE = "REJECTED_STALE_SNAPSHOT"
INTENT_STATUS_REJECTED_HALT = "REJECTED_SYSTEM_HALT"
INTENT_STATUS_SUPERSEDED = "SUPERSEDED"


class TriageValidationError(ValueError):
    """Raised when triage payload is malformed."""


class TriageConflictError(RuntimeError):
    """Raised when optimistic CAS updates cannot be applied."""


def triage_intents_path(config: Optional[Dict[str, Any]] = None) -> Path:
    cfg = config or DEFAULT_CONFIG
    configured = str(cfg.get("operator_gateway_triage_intents_path", "")).strip()
    if configured:
        return Path(configured)
    return DEFAULT_TRIAGE_INTENTS_PATH


def triage_receipts_path(config: Optional[Dict[str, Any]] = None) -> Path:
    cfg = config or DEFAULT_CONFIG
    configured = str(cfg.get("operator_gateway_triage_receipts_path", "")).strip()
    if configured:
        return Path(configured)
    return DEFAULT_TRIAGE_RECEIPTS_PATH


def load_intents(config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return dict(
        read_json_locked(
            triage_intents_path(config),
            default_factory=lambda: {"updated_at_utc": "", "items": []},
        )
    )


def load_receipts(config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return dict(
        read_json_locked(
            triage_receipts_path(config),
            default_factory=lambda: {"updated_at_utc": "", "items": []},
        )
    )


def create_intent(
    *,
    action: str,
    symbol: str,
    queue_id: str,
    target_queue_run_id: str,
    snapshot_id: str,
    snapshot_hash_canonical: str,
    snapshot_hash_raw: str,
    snapshot_validity: str,
    snapshot_price: Optional[float] = None,
    regime_label_at_snapshot: str = "",
    thesis_tags: Optional[Iterable[str]] = None,
    operator_note: str = "",
    created_by: str = "operator",
    config: Optional[Dict[str, Any]] = None,
    now: Optional[dt.datetime] = None,
) -> Dict[str, Any]:
    cfg = config or DEFAULT_CONFIG
    timestamp = _as_utc(now)
    action_norm = str(action or "").upper().strip()
    if action_norm not in {"APPROVE", "DEFER", "BLOCK"}:
        raise TriageValidationError(f"Invalid action: {action!r}")
    if str(snapshot_validity or "").upper().strip() != "VALID":
        raise TriageValidationError("Snapshot validity must be VALID for intent creation.")

    symbol_norm = str(symbol or "").upper().strip()
    queue_norm = str(queue_id or "").strip()
    run_norm = str(target_queue_run_id or "").strip()
    if not symbol_norm or not queue_norm or not run_norm:
        raise TriageValidationError("symbol, queue_id, and target_queue_run_id are required.")

    tags = sorted({str(tag or "").strip().lower() for tag in (thesis_tags or []) if str(tag or "").strip()})
    intent = {
        "intent_id": str(uuid.uuid4()),
        "action": action_norm,
        "symbol": symbol_norm,
        "queue_id": queue_norm,
        "target_queue_run_id": run_norm,
        "snapshot_id": str(snapshot_id or "").strip(),
        "snapshot_hash_canonical": str(snapshot_hash_canonical or "").strip(),
        "snapshot_hash_raw": str(snapshot_hash_raw or "").strip(),
        "snapshot_validity": "VALID",
        "snapshot_price": _as_float_or_none(snapshot_price),
        "regime_label_at_snapshot": str(regime_label_at_snapshot or "").strip(),
        "thesis_tags": tags,
        "operator_note": str(operator_note or "").strip(),
        "created_by": str(created_by or "operator"),
        "created_at_utc": timestamp.isoformat(),
        "status": INTENT_STATUS_CREATED,
        "decision_reason": "",
        "decided_at_utc": "",
        "consumed_by_run_id": "",
        "consumption_price": None,
        "price_delta_bps_vs_snapshot": None,
        "price_source_latency_ms": None,
        "market_data_quality": "",
    }
    intent["record_hash"] = _intent_record_hash(intent)

    def _updater(payload: Any) -> Dict[str, Any]:
        current = payload if isinstance(payload, dict) else {}
        items = list(current.get("items", [])) if isinstance(current.get("items"), list) else []
        # Supersede older CREATED intents for the same symbol+run (single active command).
        for row in items:
            if not isinstance(row, dict):
                continue
            if (
                str(row.get("symbol") or "").upper().strip() == symbol_norm
                and str(row.get("target_queue_run_id") or "").strip() == run_norm
                and str(row.get("status") or "") == INTENT_STATUS_CREATED
            ):
                row["status"] = INTENT_STATUS_SUPERSEDED
                row["decision_reason"] = "Superseded by newer intent."
                row["decided_at_utc"] = timestamp.isoformat()
                row["record_hash"] = _intent_record_hash(row)
        items.append(intent)
        return {"updated_at_utc": timestamp.isoformat(), "items": items}

    update_json_locked(
        triage_intents_path(cfg),
        _updater,
        default_factory=lambda: {"updated_at_utc": "", "items": []},
    )

    if action_norm == "BLOCK":
        add_symbol_theme_constraint(
            symbol=symbol_norm,
            thesis_tags=tags,
            reason=f"Triage BLOCK intent {intent['intent_id']}",
            created_by=created_by,
            config=cfg,
            now=timestamp,
        )

    return intent


def undo_intent(
    *,
    intent_id: str,
    last_known_record_hash: str,
    actor: str = "operator",
    config: Optional[Dict[str, Any]] = None,
    now: Optional[dt.datetime] = None,
) -> Dict[str, Any]:
    cfg = config or DEFAULT_CONFIG
    timestamp = _as_utc(now)
    updated_intent: Dict[str, Any] = {}

    def _updater(payload: Any) -> Dict[str, Any]:
        nonlocal updated_intent
        current = payload if isinstance(payload, dict) else {}
        items = list(current.get("items", [])) if isinstance(current.get("items"), list) else []
        target = None
        for row in items:
            if isinstance(row, dict) and str(row.get("intent_id") or "") == str(intent_id):
                target = row
                break
        if target is None:
            raise TriageValidationError(f"Intent not found: {intent_id}")

        current_hash = str(target.get("record_hash") or "")
        if current_hash != str(last_known_record_hash or ""):
            raise TriageConflictError("Intent changed; refresh status and retry.")
        if str(target.get("status") or "") != INTENT_STATUS_CREATED:
            raise TriageConflictError(f"Intent not cancelable in current state: {target.get('status')}")

        target["status"] = INTENT_STATUS_CANCELED
        target["decision_reason"] = f"Canceled by {actor}."
        target["decided_at_utc"] = timestamp.isoformat()
        target["consumed_by_run_id"] = ""
        target["record_hash"] = _intent_record_hash(target)
        updated_intent = dict(target)
        return {"updated_at_utc": timestamp.isoformat(), "items": items}

    update_json_locked(
        triage_intents_path(cfg),
        _updater,
        default_factory=lambda: {"updated_at_utc": "", "items": []},
    )

    append_receipt(
        intent=updated_intent,
        decision_status=INTENT_STATUS_CANCELED,
        decision_reason=str(updated_intent.get("decision_reason") or "Canceled."),
        consumed_by_run_id="",
        config=cfg,
        now=timestamp,
    )
    return updated_intent


def list_recent_intents(
    *,
    since_minutes: int = 60,
    config: Optional[Dict[str, Any]] = None,
    now: Optional[dt.datetime] = None,
) -> List[Dict[str, Any]]:
    as_of = _as_utc(now)
    lower = as_of - dt.timedelta(minutes=max(1, int(since_minutes)))
    payload = load_intents(config)
    rows: List[Dict[str, Any]] = []
    for raw in payload.get("items", []) if isinstance(payload.get("items"), list) else []:
        if not isinstance(raw, dict):
            continue
        created = _parse_utc(str(raw.get("created_at_utc") or ""))
        if created and created >= lower:
            rows.append(dict(raw))
    rows.sort(key=lambda item: str(item.get("created_at_utc") or ""), reverse=True)
    return rows


def resolve_intents_for_run(
    *,
    active_run_id: str,
    run_started_at_utc: str,
    consumption_prices: Optional[Dict[str, float]] = None,
    price_source_latency_ms: Optional[Any] = None,
    market_data_quality: str = "LIVE",
    regime_label_at_consumption: str = "",
    config: Optional[Dict[str, Any]] = None,
    now: Optional[dt.datetime] = None,
) -> Dict[str, Any]:
    cfg = config or DEFAULT_CONFIG
    timestamp = _as_utc(now)
    run_started = _parse_utc(str(run_started_at_utc or ""))
    if run_started is None:
        raise TriageValidationError("run_started_at_utc must be a valid ISO datetime.")

    prices = {
        str(symbol or "").upper().strip(): float(value)
        for symbol, value in (consumption_prices or {}).items()
    }
    maturity_seconds = float(cfg.get("operator_gateway_intent_maturity_seconds", 5.0))
    slip_bps_limit = float(cfg.get("operator_gateway_price_slip_max_bps", 150.0))
    latency_ms_limit = float(cfg.get("operator_gateway_price_latency_max_ms", 2000.0))
    matured_cutoff = run_started - dt.timedelta(seconds=maturity_seconds)

    consumed = 0
    expired_window = 0
    expired_slip = 0
    rejected_halt = 0
    touched: List[Dict[str, Any]] = []

    def _updater(payload: Any) -> Dict[str, Any]:
        nonlocal consumed, expired_window, expired_slip, rejected_halt, touched
        current = payload if isinstance(payload, dict) else {}
        items = list(current.get("items", [])) if isinstance(current.get("items"), list) else []
        touched = []

        for row in items:
            if not isinstance(row, dict):
                continue
            if str(row.get("status") or "") != INTENT_STATUS_CREATED:
                continue
            if str(row.get("target_queue_run_id") or "") != str(active_run_id):
                continue

            row_status = INTENT_STATUS_CONSUMED
            reason = "Intent consumed."
            symbol = str(row.get("symbol") or "").upper().strip()
            created_at = _parse_utc(str(row.get("created_at_utc") or ""))
            if created_at is None or created_at > matured_cutoff:
                row_status = INTENT_STATUS_EXPIRED_WINDOW
                reason = "Intent missed maturity cutoff before run start."
                expired_window += 1
            elif is_hands_off_active(cfg):
                row_status = INTENT_STATUS_REJECTED_HALT
                reason = "System halt active (HANDS_OFF)."
                rejected_halt += 1
            else:
                action = str(row.get("action") or "").upper().strip()
                if action == "APPROVE":
                    snapshot_price = _as_float_or_none(row.get("snapshot_price"))
                    consumption_price = prices.get(symbol, snapshot_price if snapshot_price else None)
                    latency_ms = _resolve_latency_ms(price_source_latency_ms, symbol)
                    delta_bps = _price_delta_bps(snapshot_price, consumption_price)
                    if latency_ms is None:
                        latency_ms = 0.0

                    if latency_ms > latency_ms_limit:
                        row_status = INTENT_STATUS_EXPIRED_PRICE_SLIP
                        reason = (
                            f"Price latency too high ({latency_ms:.2f}ms > {latency_ms_limit:.2f}ms)."
                        )
                        expired_slip += 1
                    elif delta_bps is None:
                        row_status = INTENT_STATUS_EXPIRED_PRICE_SLIP
                        reason = "Unable to compute price delta for APPROVE guard."
                        expired_slip += 1
                    elif abs(delta_bps) > slip_bps_limit:
                        row_status = INTENT_STATUS_EXPIRED_PRICE_SLIP
                        reason = (
                            f"Price slip exceeded limit ({delta_bps:.2f}bps vs {slip_bps_limit:.2f}bps)."
                        )
                        expired_slip += 1
                    else:
                        row["consumption_price"] = consumption_price
                        row["price_delta_bps_vs_snapshot"] = delta_bps
                        row["price_source_latency_ms"] = latency_ms
                        row["market_data_quality"] = market_data_quality
                        consumed += 1
                else:
                    consumed += 1

            row["status"] = row_status
            row["decision_reason"] = reason
            row["decided_at_utc"] = timestamp.isoformat()
            row["consumed_by_run_id"] = str(active_run_id)
            row["regime_label_at_consumption"] = str(regime_label_at_consumption or "")
            row["record_hash"] = _intent_record_hash(row)
            touched.append(dict(row))

        return {"updated_at_utc": timestamp.isoformat(), "items": items}

    update_json_locked(
        triage_intents_path(cfg),
        _updater,
        default_factory=lambda: {"updated_at_utc": "", "items": []},
    )

    for row in touched:
        append_receipt(
            intent=row,
            decision_status=str(row.get("status") or ""),
            decision_reason=str(row.get("decision_reason") or ""),
            consumed_by_run_id=str(active_run_id),
            config=cfg,
            now=timestamp,
        )

    return {
        "run_id": str(active_run_id),
        "run_started_at_utc": run_started.isoformat(),
        "resolved_count": len(touched),
        "consumed_count": int(consumed),
        "expired_window_count": int(expired_window),
        "expired_price_slip_count": int(expired_slip),
        "rejected_halt_count": int(rejected_halt),
        "resolved_intent_ids": [str(row.get("intent_id") or "") for row in touched],
    }


def append_receipt(
    *,
    intent: Dict[str, Any],
    decision_status: str,
    decision_reason: str,
    consumed_by_run_id: str,
    config: Optional[Dict[str, Any]] = None,
    now: Optional[dt.datetime] = None,
) -> Dict[str, Any]:
    cfg = config or DEFAULT_CONFIG
    timestamp = _as_utc(now).isoformat()
    receipt = {
        "receipt_id": str(uuid.uuid4()),
        "intent_id": str(intent.get("intent_id") or ""),
        "decision_status": str(decision_status or ""),
        "decision_reason": str(decision_reason or ""),
        "decided_at_utc": str(intent.get("decided_at_utc") or timestamp),
        "consumed_by_run_id": str(consumed_by_run_id or intent.get("consumed_by_run_id") or ""),
        "snapshot_id": str(intent.get("snapshot_id") or ""),
        "snapshot_hash_canonical": str(intent.get("snapshot_hash_canonical") or ""),
        "snapshot_hash_raw": str(intent.get("snapshot_hash_raw") or ""),
        "snapshot_price": _as_float_or_none(intent.get("snapshot_price")),
        "consumption_price": _as_float_or_none(intent.get("consumption_price")),
        "price_delta_bps_vs_snapshot": _as_float_or_none(intent.get("price_delta_bps_vs_snapshot")),
        "price_source_latency_ms": _as_float_or_none(intent.get("price_source_latency_ms")),
        "market_data_quality": str(intent.get("market_data_quality") or ""),
        "regime_label_at_consumption": str(intent.get("regime_label_at_consumption") or ""),
        "created_at_utc": timestamp,
    }

    def _updater(payload: Any) -> Dict[str, Any]:
        current = payload if isinstance(payload, dict) else {}
        items = list(current.get("items", [])) if isinstance(current.get("items"), list) else []
        items.append(receipt)
        return {"updated_at_utc": timestamp, "items": items}

    update_json_locked(
        triage_receipts_path(cfg),
        _updater,
        default_factory=lambda: {"updated_at_utc": "", "items": []},
    )
    return receipt


def _intent_record_hash(intent: Dict[str, Any]) -> str:
    payload = {k: v for k, v in intent.items() if k != "record_hash"}
    return canonical_hash(payload)


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


def _as_utc(value: Optional[dt.datetime]) -> dt.datetime:
    if value is None:
        return dt.datetime.now(dt.timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(dt.timezone.utc)


def _as_float_or_none(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _price_delta_bps(snapshot_price: Optional[float], consumption_price: Optional[float]) -> Optional[float]:
    if snapshot_price is None or consumption_price is None:
        return None
    if snapshot_price <= 0:
        return None
    return float(round(((consumption_price - snapshot_price) / snapshot_price) * 10000.0, 4))


def _resolve_latency_ms(value: Any, symbol: str) -> Optional[float]:
    if isinstance(value, dict):
        raw = value.get(symbol)
    else:
        raw = value
    return _as_float_or_none(raw)
