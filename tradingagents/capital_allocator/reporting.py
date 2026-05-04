"""Allocator reporting helpers for Alpha protocol and operator dashboard."""

from __future__ import annotations

import datetime as dt
from typing import Any, Dict, List

from .contracts import IntentStatus
from .repository import SQLiteAllocatorRepository


PENDING_STATUSES = {
    IntentStatus.PROPOSED.value,
    IntentStatus.VALIDATED.value,
    IntentStatus.VALIDATED_WAIT_FUNDING.value,
    IntentStatus.SUBMITTED.value,
}

VALIDATED_STATUSES = {
    IntentStatus.VALIDATED.value,
    IntentStatus.VALIDATED_WAIT_FUNDING.value,
    IntentStatus.SUBMITTED.value,
    IntentStatus.FILLED.value,
}


def build_allocator_report_card(
    *,
    repo: SQLiteAllocatorRepository,
    lookback_days: int = 7,
    now_utc: dt.datetime | None = None,
) -> Dict[str, Any]:
    """Build aggregated allocator audit/report-card payload."""
    lookback = max(1, int(lookback_days))
    as_of = _as_utc(now_utc)
    from_utc = as_of - dt.timedelta(days=lookback)
    cutoff_iso = from_utc.isoformat()

    with repo.connection() as conn:
        status_rows = conn.execute(
            """
            SELECT status, COUNT(*) AS c
            FROM allocator_intents
            WHERE created_at_utc >= ?
            GROUP BY status
            ORDER BY status
            """,
            (cutoff_iso,),
        ).fetchall()
        lane_status_rows = conn.execute(
            """
            SELECT lane, status, COUNT(*) AS c, AVG(target_notional_usd) AS avg_notional
            FROM allocator_intents
            WHERE created_at_utc >= ?
            GROUP BY lane, status
            ORDER BY lane, status
            """,
            (cutoff_iso,),
        ).fetchall()
        rejection_rows = conn.execute(
            """
            SELECT
              CASE
                WHEN reason_code IS NULL OR reason_code = '' THEN 'UNSPECIFIED'
                ELSE reason_code
              END AS code,
              COUNT(*) AS c
            FROM allocator_intents
            WHERE created_at_utc >= ?
              AND status LIKE 'REJECTED_%'
            GROUP BY code
            ORDER BY c DESC, code ASC
            LIMIT 10
            """,
            (cutoff_iso,),
        ).fetchall()
        mode_rows = conn.execute(
            """
            SELECT execution_mode, COUNT(*) AS c
            FROM allocator_intents
            WHERE created_at_utc >= ?
            GROUP BY execution_mode
            ORDER BY execution_mode
            """,
            (cutoff_iso,),
        ).fetchall()
        veto_rows = conn.execute(
            """
            SELECT
              intent_id,
              symbol,
              lane,
              side,
              status,
              reason_code,
              reason,
              updated_at_utc
            FROM allocator_intents
            WHERE created_at_utc >= ?
              AND status LIKE 'REJECTED_%'
            ORDER BY updated_at_utc DESC
            LIMIT 20
            """,
            (cutoff_iso,),
        ).fetchall()
        pending_funding = conn.execute(
            """
            SELECT COUNT(*) AS c
            FROM allocator_intents
            WHERE created_at_utc >= ?
              AND (
                    status = 'VALIDATED_WAIT_FUNDING'
                    OR (
                      funding_source_status = 'PENDING_SALE_PROCEEDS'
                      AND status IN ('PROPOSED', 'VALIDATED', 'VALIDATED_WAIT_FUNDING', 'SUBMITTED')
                    )
                  )
            """,
            (cutoff_iso,),
        ).fetchone()

    status_counts: Dict[str, int] = {
        str(row["status"]): int(row["c"])
        for row in status_rows
    }
    total_intents = int(sum(status_counts.values()))
    pending_count = int(sum(count for status, count in status_counts.items() if status in PENDING_STATUSES))
    terminal_count = int(max(0, total_intents - pending_count))
    validated_count = int(sum(count for status, count in status_counts.items() if status in VALIDATED_STATUSES))
    rejected_count = int(sum(count for status, count in status_counts.items() if status.startswith("REJECTED_")))
    veto_rate_pct = float((rejected_count / total_intents) * 100.0) if total_intents > 0 else 0.0
    validation_rate_pct = float((validated_count / total_intents) * 100.0) if total_intents > 0 else 0.0

    return {
        "as_of_utc": as_of.isoformat(),
        "lookback_days": lookback,
        "from_utc": from_utc.isoformat(),
        "total_intents": total_intents,
        "pending_count": pending_count,
        "terminal_count": terminal_count,
        "validated_count": validated_count,
        "rejected_count": rejected_count,
        "validation_rate_pct": round(validation_rate_pct, 4),
        "veto_rate_pct": round(veto_rate_pct, 4),
        "status_counts": status_counts,
        "lane_status_counts": [
            {
                "lane": str(row["lane"] or ""),
                "status": str(row["status"] or ""),
                "count": int(row["c"]),
                "avg_target_notional_usd": round(float(row["avg_notional"] or 0.0), 2),
            }
            for row in lane_status_rows
        ],
        "rejection_reason_counts": [
            {
                "reason_code": str(row["code"] or ""),
                "count": int(row["c"]),
            }
            for row in rejection_rows
        ],
        "recent_vetoes": [
            {
                "intent_id": str(row["intent_id"] or ""),
                "symbol": str(row["symbol"] or ""),
                "lane": str(row["lane"] or ""),
                "side": str(row["side"] or ""),
                "status": str(row["status"] or ""),
                "reason_code": str(row["reason_code"] or ""),
                "reason": str(row["reason"] or ""),
                "updated_at_utc": str(row["updated_at_utc"] or ""),
            }
            for row in veto_rows
        ],
        "pending_funding_count": int((pending_funding or {"c": 0})["c"]),
        "by_execution_mode": {
            str(row["execution_mode"] or ""): int(row["c"])
            for row in mode_rows
        },
    }


def _as_utc(value: dt.datetime | None) -> dt.datetime:
    if value is None:
        return dt.datetime.now(dt.timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(dt.timezone.utc)
