from __future__ import annotations

import datetime as dt
import json
import math
import sqlite3
from pathlib import Path
from typing import Any, Dict, List


DEFAULT_DB_PATH = Path("eval_results/deal_flow/hindsight.db")
DEFAULT_OUTPUT_PATH = Path("eval_results/control/ic_signal_weights.json")


def _load_recent_family_ic_rows(
    db_path: Path,
    lookback_cycles: int,
) -> List[dict]:
    if not db_path.exists():
        return []
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            WITH recent_cycles AS (
                SELECT DISTINCT source_date
                FROM signal_family_ic
                ORDER BY source_date DESC
                LIMIT ?
            )
            SELECT s.source_date, s.signal_family, s.ic, s.t_stat, s.n
            FROM signal_family_ic s
            INNER JOIN recent_cycles rc
                ON rc.source_date = s.source_date
            ORDER BY s.source_date DESC, s.signal_family ASC
            """,
            (int(lookback_cycles),),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _bounded_delta(avg_ic: float) -> float:
    if not math.isfinite(avg_ic):
        return 0.0
    delta = avg_ic * 20.0
    return round(max(-4.0, min(4.0, delta)), 2)


def write_signal_weight_adjustments(
    *,
    db_path: Path | str = DEFAULT_DB_PATH,
    output_path: Path | str = DEFAULT_OUTPUT_PATH,
    lookback_cycles: int = 20,
    min_cycles: int = 3,
    min_avg_n: int = 20,
    ttl_days: int = 14,
) -> Dict[str, Any]:
    db_path = Path(db_path)
    output_path = Path(output_path)
    rows = _load_recent_family_ic_rows(db_path=db_path, lookback_cycles=lookback_cycles)
    if not rows:
        return {
            "status": "SKIPPED_INSUFFICIENT_DATA",
            "reason": "no_signal_family_ic_rows",
            "output_path": "",
        }

    grouped: Dict[str, List[dict]] = {}
    for row in rows:
        grouped.setdefault(str(row.get("signal_family") or ""), []).append(row)

    adjustments: Dict[str, float] = {}
    family_summary: Dict[str, dict] = {}
    for family, family_rows in grouped.items():
        unique_cycles = {str(row.get("source_date") or "") for row in family_rows if str(row.get("source_date") or "")}
        avg_n = sum(int(row.get("n") or 0) for row in family_rows) / max(1, len(family_rows))
        finite_ics = [float(row.get("ic")) for row in family_rows if row.get("ic") is not None and math.isfinite(float(row.get("ic")))]
        if len(unique_cycles) < int(min_cycles) or avg_n < float(min_avg_n) or not finite_ics:
            family_summary[family] = {
                "cycles": len(unique_cycles),
                "avg_n": round(avg_n, 2),
                "avg_ic": round(sum(finite_ics) / len(finite_ics), 4) if finite_ics else None,
                "eligible": False,
            }
            continue
        avg_ic = sum(finite_ics) / len(finite_ics)
        delta = _bounded_delta(avg_ic)
        if abs(delta) < 0.01:
            family_summary[family] = {
                "cycles": len(unique_cycles),
                "avg_n": round(avg_n, 2),
                "avg_ic": round(avg_ic, 4),
                "eligible": True,
                "delta": 0.0,
            }
            continue
        adjustments[family] = delta
        family_summary[family] = {
            "cycles": len(unique_cycles),
            "avg_n": round(avg_n, 2),
            "avg_ic": round(avg_ic, 4),
            "eligible": True,
            "delta": delta,
        }

    if not adjustments:
        return {
            "status": "SKIPPED_INSUFFICIENT_DATA",
            "reason": "no_eligible_families",
            "family_summary": family_summary,
            "output_path": "",
        }

    now = dt.datetime.now(dt.timezone.utc)
    payload = {
        "generated_at": now.isoformat(),
        "expires_at": (now + dt.timedelta(days=int(ttl_days))).isoformat(),
        "generated_by": "learning_loop",
        "lookback_cycles": int(lookback_cycles),
        "adjustments": adjustments,
        "family_summary": family_summary,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2))
    return {
        "status": "UPDATED",
        "output_path": str(output_path),
        "payload": payload,
    }
