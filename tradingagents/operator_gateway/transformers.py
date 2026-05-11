"""Artifact-to-DTO transformers for operator UI read endpoints."""

from __future__ import annotations

import datetime as dt
import hashlib
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from tradingagents.dealflow.canonical_json import canonical_hash


VALIDITY_VALID = "VALID"
VALIDITY_STALE = "STALE"
VALIDITY_INVALID = "INVALID"


def build_snapshot_envelope(
    *,
    raw_payload: Any,
    artifact_path: Optional[Path],
    now: Optional[dt.datetime] = None,
) -> Dict[str, Any]:
    now_utc = _as_utc(now)
    payload = raw_payload if isinstance(raw_payload, dict) else {}
    run_id = str(payload.get("run_id") or "").strip()
    as_of_date = str(payload.get("date") or "").strip()
    tickers = payload.get("tickers", [])
    has_tickers = isinstance(tickers, list)
    stale_reasons: List[str] = []

    canonical_hash_value = canonical_hash(payload)
    raw_hash_value = ""
    generated_at_utc = ""
    if artifact_path and Path(artifact_path).exists():
        raw_hash_value = hashlib.sha256(Path(artifact_path).read_bytes()).hexdigest()
        generated_at_utc = dt.datetime.fromtimestamp(
            Path(artifact_path).stat().st_mtime,
            tz=dt.timezone.utc,
        ).isoformat()
    else:
        stale_reasons.append("Artifact file missing.")

    if not run_id:
        stale_reasons.append("Missing run_id.")
    if not as_of_date:
        stale_reasons.append("Missing date.")
    if not has_tickers:
        stale_reasons.append("Missing ticker list.")

    parsed_date = _parse_date(as_of_date)
    if parsed_date and parsed_date < now_utc.date():
        stale_reasons.append("Artifact date is older than current date.")

    validity = VALIDITY_VALID
    if any(reason.startswith("Missing") or reason.startswith("Artifact file") for reason in stale_reasons):
        validity = VALIDITY_INVALID
    elif stale_reasons:
        validity = VALIDITY_STALE

    snapshot_id = f"{run_id}:{canonical_hash_value[:12]}" if run_id else canonical_hash_value[:12]
    return {
        "snapshot_id": snapshot_id,
        "snapshot_hash_canonical": canonical_hash_value,
        "snapshot_hash_raw": raw_hash_value,
        "queue_run_id": run_id,
        "as_of_date": as_of_date,
        "generated_at_utc": generated_at_utc or now_utc.isoformat(),
        "validity": validity,
        "stale_reasons": stale_reasons,
        "triage_enabled": False,
    }


def transform_dealflow_feed(
    *,
    raw_queue: Any,
    snapshot: Dict[str, Any],
    thesis_summary_max_chars: int = 140,
) -> Dict[str, Any]:
    handoff = raw_queue if isinstance(raw_queue, dict) else {}
    tickers = handoff.get("tickers", [])
    metadata = handoff.get("metadata_by_ticker", {}) if isinstance(handoff.get("metadata_by_ticker"), dict) else {}
    rows = [
        {"symbol": str(symbol), **(metadata.get(str(symbol), {}) if isinstance(metadata, dict) else {})}
        for symbol in tickers
    ] if isinstance(tickers, list) else []
    cards = [
        transform_candidate_card(
            queue_item=item,
            snapshot_id=str(snapshot.get("snapshot_id") or ""),
            thesis_summary_max_chars=thesis_summary_max_chars,
        )
        for item in rows
        if isinstance(item, dict)
    ]

    summary = transform_dealflow_summary(raw_queue=handoff, cards=cards)
    return {
        "snapshot": snapshot,
        "summary": summary,
        "candidates": cards,
    }


def transform_dealflow_summary(*, raw_queue: Any, cards: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    handoff = raw_queue if isinstance(raw_queue, dict) else {}
    card_rows = list(cards)
    total = len(card_rows)
    return {
        "run_id": str(handoff.get("run_id") or ""),
        "date": str(handoff.get("date") or ""),
        "total_candidates": total,
        "handoff_count": total,
        "lane_counts": {
            "SCOUT": total,
        },
        "top_symbols": [str(row.get("symbol") or "") for row in card_rows[:5]],
    }


def transform_candidate_card(
    *,
    queue_item: Dict[str, Any],
    snapshot_id: str,
    thesis_summary_max_chars: int = 140,
) -> Dict[str, Any]:
    symbol = str(queue_item.get("symbol") or "UNKNOWN").upper().strip() or "UNKNOWN"
    lane = "SCOUT"
    scouts = list(queue_item.get("scouts", []) or [])
    thesis_summary = _truncate(
        "Scout handoff: " + (", ".join(str(s) for s in scouts) if scouts else "source unknown"),
        int(thesis_summary_max_chars),
    )
    return {
        "symbol": symbol,
        "lane": lane,
        "score": None,
        "confidence": None,
        "thesis_summary": thesis_summary,
        "risk_flags": [],
        "quality_tier": "UNSCORED",
        "snapshot_id": snapshot_id,
        "queue_id": "",
        "research_playbook": "",
    }


def transform_candidate_detail(
    *,
    symbol: str,
    queue_item: Optional[Dict[str, Any]],
    analysis_report: Optional[Dict[str, Any]],
    snapshot: Dict[str, Any],
    detail_summary_max_chars: int = 320,
) -> Dict[str, Any]:
    item = queue_item if isinstance(queue_item, dict) else {}
    report = analysis_report if isinstance(analysis_report, dict) else {}
    card = transform_candidate_card(
        queue_item={
            "symbol": symbol,
            **item,
        },
        snapshot_id=str(snapshot.get("snapshot_id") or ""),
    )

    top_signals = [{"family": str(name)} for name in list(item.get("scouts", []) or [])[:3]]

    aeternus = report.get("aeternus_score") if isinstance(report.get("aeternus_score"), dict) else {}
    thesis = report.get("thesis_check") if isinstance(report.get("thesis_check"), dict) else {}
    final_trade = str(report.get("final_trade_decision") or report.get("trader_investment_plan") or "")

    recommendation = _extract_recommendation(final_trade)
    summary_text = _truncate(_squash_whitespace(final_trade) or "Data Unavailable", detail_summary_max_chars)

    return {
        "snapshot": snapshot,
        "candidate": card,
        "found": bool(item),
        "analysis_available": bool(report),
        "analysis": {
            "rating": str(aeternus.get("rating") or "Data Unavailable"),
            "aeternus_score": _to_float(aeternus.get("aeternus_score"), None),
            "confidence": _to_int_or_none(aeternus.get("confidence")),
            "recommendation": recommendation or "Data Unavailable",
            "thesis_change": str(thesis.get("thesis_change") or "Data Unavailable"),
            "summary": summary_text,
        },
        "evidence": {
            "active_families": _to_float(_nested(item, "evidence", "active_families"), None),
            "evidence_count": _to_float(_nested(item, "evidence", "evidence_count"), None),
            "freshness_hours": _to_float(_nested(item, "evidence", "freshness_hours"), None),
            "top_signals": top_signals,
            "thesis_tags": list(item.get("thesis_tags", [])) if isinstance(item.get("thesis_tags"), list) else [],
        },
    }


def _derive_confidence(item: Dict[str, Any]) -> int:
    confidence = 3
    active_families = _to_float(_nested(item, "evidence", "active_families"), 0.0)
    evidence_count = _to_float(_nested(item, "evidence", "evidence_count"), 0.0)
    freshness_hours = _to_float(_nested(item, "evidence", "freshness_hours"), 9999.0)
    if active_families >= 3:
        confidence += 1
    if evidence_count >= 200:
        confidence += 1
    if freshness_hours > 48:
        confidence -= 1
    return _clamp_int(confidence, 1, 5)


def _sanitize_risk_flags(raw: Any) -> List[str]:
    values = raw if isinstance(raw, list) else []
    out: List[str] = []
    for row in values:
        text = str(row or "").strip()
        if not text:
            continue
        token = re.sub(r"[^A-Z0-9]+", "_", text.upper()).strip("_")
        if not token:
            continue
        out.append(token[:40])
    return out[:4]


def _extract_recommendation(text: str) -> str:
    raw = str(text or "")
    for pattern in [
        r"\*\*(BUY|HOLD|SELL)\*\*",
        r"RECOMMENDATION:\s*(BUY|HOLD|SELL)",
        r"FINAL TRANSACTION PROPOSAL:\s*\*\*(BUY|HOLD|SELL)\*\*",
    ]:
        match = re.search(pattern, raw, flags=re.IGNORECASE)
        if match:
            return str(match.group(1)).upper()
    return ""


def _truncate(text: str, max_chars: int) -> str:
    clean = _squash_whitespace(text)
    if len(clean) <= max_chars:
        return clean
    return clean[: max(0, max_chars - 1)].rstrip() + "…"


def _squash_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _to_float(value: Any, default: Optional[float]) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int_or_none(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _clamp_int(value: float, lower: int, upper: int) -> int:
    return int(max(lower, min(upper, int(round(value)))))


def _nested(obj: Any, *path: str) -> Any:
    current = obj
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _as_utc(value: Optional[dt.datetime]) -> dt.datetime:
    if value is None:
        return dt.datetime.now(dt.timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(dt.timezone.utc)


def _parse_date(value: str) -> Optional[dt.date]:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return dt.date.fromisoformat(raw)
    except ValueError:
        return None
