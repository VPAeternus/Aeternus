from __future__ import annotations

from pathlib import Path
from typing import Any

from tradingagents.research.fundamental.src.pipeline.run_on_new_filing import build_signal_tables

from .artifacts import write_csv, write_json_atomic
from .models import GateResult, GateStatus, RunMode


def build_final_scores(
    broad_rows: list[dict[str, Any]],
    *,
    as_of: str,
    post_llm_rows: list[dict[str, Any]] | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    signal_rows, tier_rows, pre_rows = build_signal_tables(broad_rows, as_of=as_of, post_llm_rows=post_llm_rows or [])
    summary = {
        "broad_rows": len(broad_rows),
        "post_llm_rows": len(post_llm_rows or []),
        "final_score_rows": len(signal_rows),
        "tier_rows": len(tier_rows),
        "pre_rows": len(pre_rows),
    }
    return signal_rows, summary


def validate_broad_final_scores(
    *,
    final_rows: list[dict[str, Any]],
    broad_universe_count: int,
    explicit_invalid_quarantine_count: int,
    run_mode: RunMode,
    artifacts: dict[str, str],
) -> GateResult:
    reconciled = len(final_rows) + int(explicit_invalid_quarantine_count)
    summary = {
        "final_score_rows": len(final_rows),
        "explicit_invalid_quarantine_count": int(explicit_invalid_quarantine_count),
        "reconciled_count": reconciled,
        "broad_universe_count": broad_universe_count,
    }
    if run_mode == RunMode.BROAD_MASTER_FINAL and reconciled != broad_universe_count:
        summary["reason"] = "final_scores_plus_quarantine_do_not_reconcile_to_broad_universe"
        return GateResult(9, "Final scoring, HP buckets, and RM buckets", GateStatus.HARD_STOP, summary, artifacts)
    return GateResult(9, "Final scoring, HP buckets, and RM buckets", GateStatus.PASS, summary, artifacts)


def write_final_scores_csv(path: Path, rows: list[dict[str, Any]], summary: dict[str, Any]) -> dict[str, str]:
    write_csv(path, rows)
    summary_path = path.with_name(path.stem + "_summary.json")
    write_json_atomic(summary_path, summary)
    return {"final_scores_csv": str(path), "final_scores_summary": str(summary_path)}


def publish_top15_and_shadow(
    *,
    scores_csv: Path,
    output_root: Path,
    as_of: str,
    broad_universe_count: int,
    coverage_manifest: Path | None = None,
) -> GateResult:
    import pandas as pd

    frame = pd.read_csv(scores_csv).fillna("")
    summary = {"input_rows": int(len(frame)), "broad_universe_count": broad_universe_count}
    if len(frame) != broad_universe_count:
        summary["reason"] = "top15_input_not_broad_final_scores"
        return GateResult(10, "Top10 + Plus5 + shadow refill publish", GateStatus.HARD_STOP, summary, {"scores_csv": str(scores_csv)})

    try:
        from tradingagents.research.fundamental.src.selection.high_conviction_top10 import (
            select_top15_core_deterioration_refill_shadow_from_csv,
            select_top15_from_csv,
        )

        top15 = select_top15_from_csv(
            scores_csv,
            output_root,
            {"selection_date": as_of, "enabled": True, "core_n": 10, "exception_slots": 5},
            coverage_manifest,
        )
        shadow = select_top15_core_deterioration_refill_shadow_from_csv(
            scores_csv,
            output_root,
            {
                "selection_date": as_of,
                "enabled": True,
                "core_n": 10,
                "exception_slots": 5,
                "core_deterioration_refill": {"enabled": True, "mode": "strict"},
            },
            coverage_manifest,
        )
    except Exception as exc:  # noqa: BLE001 - publish failure must stop official final output.
        summary["reason"] = "top15_publish_failed"
        summary["publish_error"] = str(exc)
        return GateResult(10, "Top10 + Plus5 + shadow refill publish", GateStatus.HARD_STOP, summary, {"scores_csv": str(scores_csv)})

    artifacts = {
        "scores_csv": str(scores_csv),
        **{f"top15_{key}": str(value) for key, value in top15.get("output_paths", {}).items()},
        **{f"shadow_{key}": str(value) for key, value in shadow.get("output_paths", {}).items()},
    }
    summary.update({
        "top15_selected_count": len(top15.get("selected_rows", [])),
        "shadow_selected_count": len(shadow.get("selected_rows", [])),
    })
    return GateResult(10, "Top10 + Plus5 + shadow refill publish", GateStatus.PASS, summary, artifacts)
