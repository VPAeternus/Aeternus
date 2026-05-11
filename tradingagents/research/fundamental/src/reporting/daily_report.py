from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from src.features.common import clean, to_float
from src.storage import write_csv


def _score(row: dict[str, Any], key: str) -> float:
    return to_float(row.get(key)) or 0


REPRICING_COLUMNS = [
    "ticker",
    "quarter",
    "entry_open",
    "entry_qoq_pct",
    "prior_entry_qoq_pct",
    "pre_llm_fundamental_score",
    "pre_llm_fundamental_bucket",
    "rm1_low_price_dislocation_momentum",
    "rm2_weak_acceleration",
    "rm3_mid_price_dislocation_momentum",
    "rm4_persistent_repricing_wave",
    "primary_theme",
    "theme_tags",
    "theme_role",
    "theme_confidence",
    "theme_cohort_strength",
    "theme_tailwind_score",
    "theme_evidence_summary",
    "entry_score_0_100",
    "market_repricing_score",
    "rm_buy_review_flag",
    "llm_status",
    "positive_repricing_status",
    "monitoring_status",
]


def _project(rows: list[dict[str, Any]], columns: list[str]) -> list[dict[str, Any]]:
    return [{column: row.get(column, "") for column in columns} for row in rows]


def _write_projected_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return path


def write_daily_reports(rows: list[dict[str, Any]], *, as_of: str, out_dir: Path = Path("outputs/daily")) -> list[Path]:
    stamp = as_of.replace("-", "")
    new_candidates = [row for row in rows if clean(row.get("candidate_state")) in {"new_signal", "fundamental_review", "watchlist", "llm_pending"}]
    research = [row for row in new_candidates if _score(row, "entry_score_0_100") >= 70 and clean(row.get("monitoring_status")) != "kill_review"]
    active = [
        row
        for row in rows
        if clean(row.get("candidate_state")) in {"active_position", "starter_position", "active_watchlist"}
        and clean(row.get("monitoring_status")) != "kill_review"
        and _score(row, "active_monitoring_score_0_100") >= 70
    ]
    kill = [row for row in rows if clean(row.get("monitoring_status")) == "kill_review"]
    buy_decision = [
        row
        for row in new_candidates
        if (
            _score(row, "force_pm_underwriting_flag") == 1
            or _score(row, "rm_buy_review_flag") == 1
            or (
                _score(row, "entry_score_0_100") >= 75
                and clean(row.get("post_llm_candidate_flag")) in {"1", "true", "True"}
                and clean(row.get("causal_change")) == "3"
                and (_score(row, "negative_revision_risk") <= 2)
            )
        )
        and clean(row.get("monitoring_status")) not in {"kill_review", "expired_signal"}
    ]
    aging = [
        row
        for row in rows
        if _score(row, "entry_score_0_100") >= 70
        and clean(row.get("signal_freshness_status")) in {"aging_signal", "stale_signal"}
        and clean(row.get("decision_type")) not in {"buy", "starter", "pass", "approved_buy"}
    ]
    score_changes = [row for row in rows if _score(row, "applied_monitoring_delta") != 0]
    repricing = [
        row
        for row in rows
        if clean(row.get("repricing_momentum_extension"))
        and clean(row.get("monitoring_status")) != "kill_review"
    ]
    persistent = [
        row
        for row in rows
        if clean(row.get("rm4_persistent_repricing_wave"))
        and clean(row.get("monitoring_status")) != "kill_review"
    ]
    positive_repricing = [
        row
        for row in rows
        if clean(row.get("positive_repricing_status")) in {"repricing_started", "repricing_confirmed"}
        and clean(row.get("monitoring_status")) != "kill_review"
    ]
    repricing_priority_queue = [
        row
        for row in rows
        if _score(row, "rm_buy_review_flag") == 1
        and clean(row.get("monitoring_status")) != "kill_review"
    ]
    outputs = [
        write_csv(out_dir / f"{stamp}_new_candidates.csv", new_candidates),
        write_csv(out_dir / f"{stamp}_new_entry_fundamental_review.csv", sorted(research, key=lambda r: _score(r, "entry_score_0_100"), reverse=True)),
        write_csv(out_dir / f"{stamp}_top_active_positions.csv", sorted(active, key=lambda r: _score(r, "active_monitoring_score_0_100"), reverse=True)),
        write_csv(out_dir / f"{stamp}_kill_review.csv", sorted(kill, key=lambda r: _score(r, "current_return_pct"))),
        write_csv(out_dir / f"{stamp}_score_changes.csv", sorted(score_changes, key=lambda r: _score(r, "applied_monitoring_delta"))),
        write_csv(out_dir / f"{stamp}_buy_decision_candidates.csv", sorted(buy_decision, key=lambda r: _score(r, "entry_score_0_100"), reverse=True)),
        write_csv(out_dir / f"{stamp}_aging_high_scoring_candidates.csv", aging),
        _write_projected_csv(
            out_dir / f"{stamp}_repricing_momentum_candidates.csv",
            _project(sorted(repricing, key=lambda r: _score(r, "market_repricing_score"), reverse=True), REPRICING_COLUMNS),
            REPRICING_COLUMNS,
        ),
        _write_projected_csv(
            out_dir / f"{stamp}_persistent_repricing_wave_candidates.csv",
            _project(sorted(persistent, key=lambda r: _score(r, "market_repricing_score"), reverse=True), REPRICING_COLUMNS),
            REPRICING_COLUMNS,
        ),
        _write_projected_csv(
            out_dir / f"{stamp}_positive_repricing_promotion_candidates.csv",
            _project(sorted(positive_repricing, key=lambda r: _score(r, "market_repricing_score"), reverse=True), REPRICING_COLUMNS),
            REPRICING_COLUMNS,
        ),
        _write_projected_csv(
            out_dir / f"{stamp}_repricing_momentum_priority_queue.csv",
            _project(
                sorted(
                    repricing_priority_queue,
                    key=lambda r: (
                        _score(r, "market_repricing_score"),
                        _score(r, "entry_qoq_pct"),
                        _score(r, "entry_score_0_100"),
                    ),
                    reverse=True,
                ),
                REPRICING_COLUMNS,
            ),
            REPRICING_COLUMNS,
        ),
    ]
    return outputs
