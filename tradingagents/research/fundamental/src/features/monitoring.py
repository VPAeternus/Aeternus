from __future__ import annotations

from typing import Any

from src.features.common import clamp, to_float
from src.features.scoring import score_label


CHECKPOINT_COLUMNS = ["return_10d_pct", "return_20d_pct", "return_30d_pct", "return_60d_pct"]


def compute_monitoring_status(row: dict[str, Any]) -> str:
    return_60d = to_float(row.get("return_60d_pct"))
    return_30d = to_float(row.get("return_30d_pct"))
    return_20d = to_float(row.get("return_20d_pct"))
    return_10d = to_float(row.get("return_10d_pct"))
    if return_60d is not None and return_60d <= -10:
        return "kill_review"
    if return_30d is not None and return_30d <= -15:
        return "midpoint_stress"
    if return_20d is not None and return_20d <= -20:
        return "early_stress"
    if return_10d is not None and return_10d <= -20:
        return "early_stress"
    if any(to_float(row.get(col)) is not None for col in CHECKPOINT_COLUMNS):
        return "active_ok"
    return "pre_checkpoint"


def compute_active_monitoring_score(row: dict[str, Any]) -> dict[str, Any]:
    entry_score = int(to_float(row.get("entry_score_0_100")) or 0)
    status = compute_monitoring_status(row)
    return_20d = to_float(row.get("return_20d_pct"))
    return_30d = to_float(row.get("return_30d_pct"))
    return_60d = to_float(row.get("return_60d_pct"))
    repricing_started = int(
        status != "kill_review"
        and (
            (return_20d is not None and return_20d >= 20)
            or (return_30d is not None and return_30d >= 20)
        )
    )
    repricing_confirmed = int(status != "kill_review" and return_60d is not None and return_60d >= 30)
    positive_repricing_status = "none"
    if repricing_started:
        positive_repricing_status = "repricing_started"
    if repricing_confirmed:
        positive_repricing_status = "repricing_confirmed"
    if status == "kill_review":
        active = min(entry_score, 20)
    elif status == "midpoint_stress":
        active = clamp(entry_score - 12)
    elif status == "early_stress":
        active = clamp(entry_score - 10)
    else:
        active = entry_score
    return {
        "active_monitoring_score_0_100": active,
        "dashboard_score_0_100": active if status != "pre_checkpoint" else entry_score,
        "score_label": score_label(active, status),
        "monitoring_status": status,
        "applied_monitoring_delta": active - entry_score,
        "repricing_started": repricing_started,
        "repricing_confirmed": repricing_confirmed,
        "positive_repricing_status": positive_repricing_status,
    }
