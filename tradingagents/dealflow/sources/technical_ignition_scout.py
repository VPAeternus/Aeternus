"""Discovery-only technical ignition scout backed by cached KAMA/FVG state."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

from tradingagents.dealflow.technical_signal_store import SQLiteTechnicalSignalStore


DEFAULT_TECHNICAL_SIGNAL_DB_PATH = Path("eval_results") / "control" / "technical_signal_cache.db"
PROMOTED_STATUSES: tuple[str, ...] = ("BUY_TRIGGER", "BUY_ZONE")
STALE_STATUSES: tuple[str, ...] = ("TREND_UP_NOT_FRESH",)


def scan_technical_ignition_setups(
    *,
    as_of_date: str,
    db_path: str | Path | None = None,
    promoted_statuses: Sequence[str] = PROMOTED_STATUSES,
    stale_statuses: Sequence[str] = STALE_STATUSES,
) -> dict[str, Any]:
    effective_path = Path(db_path or DEFAULT_TECHNICAL_SIGNAL_DB_PATH)
    payload = {
        "date": str(as_of_date).strip(),
        "db_path": str(effective_path),
        "promoted_statuses": [str(value).upper().strip() for value in promoted_statuses],
        "stale_statuses": [str(value).upper().strip() for value in stale_statuses],
        "promoted_count": 0,
        "promoted_symbols": [],
        "promoted": [],
        "stale_count": 0,
        "stale_symbols": [],
        "stale": [],
        "signals": [],
    }
    if not effective_path.exists():
        return payload

    store = SQLiteTechnicalSignalStore(effective_path)
    store.initialize()
    promoted = _filter_rows_for_date(
        store.list_buy_zone_states(status_labels=promoted_statuses),
        as_of_date=as_of_date,
    )
    stale = _filter_rows_for_date(
        store.list_buy_zone_states(status_labels=stale_statuses),
        as_of_date=as_of_date,
    )

    promoted_rows = [_normalize_row(row) for row in promoted]
    stale_rows = [_normalize_row(row) for row in stale]
    promoted_rows.sort(key=_sort_key)
    stale_rows.sort(key=_sort_key)

    payload["promoted"] = promoted_rows
    payload["promoted_symbols"] = [str(row["ticker"]) for row in promoted_rows]
    payload["promoted_count"] = len(promoted_rows)
    payload["stale"] = stale_rows
    payload["stale_symbols"] = [str(row["ticker"]) for row in stale_rows]
    payload["stale_count"] = len(stale_rows)
    payload["signals"] = [_signal_row(row) for row in promoted_rows]
    return payload


def _filter_rows_for_date(rows: Sequence[dict[str, Any]], *, as_of_date: str) -> list[dict[str, Any]]:
    effective_date = str(as_of_date).strip()
    return [
        dict(row)
        for row in list(rows or [])
        if str(row.get("as_of_date", "")).strip() == effective_date
    ]


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "ticker": str(row.get("ticker", "")).upper().strip(),
        "status_label": str(row.get("status_label", "NOT_IN_BUY_ZONE")).upper().strip(),
        "reason": str(row.get("reason", "")).strip(),
        "last_cross_up_date": str(row.get("last_cross_up_date", "")).strip() or None,
        "bullish_fvg_regime_active": int(row.get("bullish_fvg_regime_active", 0) or 0),
        "bullish_fvg_streak": int(row.get("bullish_fvg_streak", 0) or 0),
        "bullish_fvg_regime_age_bars": int(row.get("bullish_fvg_regime_age_bars", 0) or 0),
        "score": float(row.get("score", 0.0) or 0.0),
        "as_of_date": str(row.get("as_of_date", "")).strip(),
    }


def _signal_row(row: dict[str, Any]) -> dict[str, Any]:
    status_label = str(row.get("status_label", "BUY_ZONE")).upper().strip()
    confidence = 0.85 if status_label == "BUY_TRIGGER" else 0.75
    raw_strength = min(1.0, max(0.0, float(row.get("score", 0.0) or 0.0) / 100.0))
    return {
        "symbol": str(row.get("ticker", "")).upper().strip(),
        "source": "technical_ignition",
        "delta_kind": "technical_ignition",
        "direction": "BULLISH",
        "raw_strength": raw_strength,
        "confidence_score": confidence,
        "tags": [status_label.lower(), "technical_ignition"],
    }


def _sort_key(row: dict[str, Any]) -> tuple[int, float, str]:
    status = str(row.get("status_label", "")).upper().strip()
    priority = 0 if status == "BUY_TRIGGER" else 1 if status == "BUY_ZONE" else 2
    return (priority, -float(row.get("score", 0.0) or 0.0), str(row.get("ticker", "")))
