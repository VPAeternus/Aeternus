from __future__ import annotations

from pathlib import Path
from typing import Any

from tradingagents.research.fundamental.src.features.common import clean, to_float
from tradingagents.research.fundamental.src.storage import write_csv


def write_weekly_reports(
    candidates: list[dict[str, Any]],
    monitoring: list[dict[str, Any]],
    *,
    as_of: str,
    out_dir: Path = Path("outputs/weekly"),
) -> list[Path]:
    stamp = as_of.replace("-", "")
    new_entry = [
        row
        for row in candidates
        if clean(row.get("candidate_state")) in {"new_signal", "fundamental_review", "watchlist", "llm_pending"}
        and (to_float(row.get("entry_score_0_100")) or 0) >= 60
        and clean(row.get("monitoring_status")) != "kill_review"
    ]
    active = [row for row in monitoring if clean(row.get("candidate_state")) in {"active_position", "starter_position", "active_watchlist"}]
    dashboard = candidates + monitoring
    risk = [row for row in dashboard if clean(row.get("monitoring_status")) in {"kill_review", "early_stress", "midpoint_stress"} or clean(row.get("post_llm_demote_flag")) in {"1", "true", "True"}]
    return [
        write_csv(out_dir / f"{stamp}_new_entry_fundamental_review.csv", sorted(new_entry, key=lambda r: to_float(r.get("entry_score_0_100")) or 0, reverse=True)),
        write_csv(out_dir / f"{stamp}_active_monitoring_queue.csv", sorted(active, key=lambda r: to_float(r.get("active_monitoring_score_0_100")) or 0, reverse=True)),
        write_csv(out_dir / f"{stamp}_candidate_dashboard.csv", dashboard),
        write_csv(out_dir / f"{stamp}_risk_review.csv", risk),
    ]
