from __future__ import annotations

from pathlib import Path
from typing import Any

from tradingagents.research.fundamental.src.features.common import clean, prior_quarter, to_float
from tradingagents.research.fundamental.src.pipeline.run_on_new_filing import build_signal_tables
from tradingagents.research.fundamental.src.storage import read_rows

from .artifacts import write_csv, write_json_atomic
from .models import GateResult, GateStatus, RunMode


QOQ_REQUIRED_FIELDS = ("entry_qoq_pct", "score_change", "prior_pre_llm_fundamental_score")


def _row_key(row: dict[str, Any]) -> tuple[str, str]:
    return clean(row.get("ticker")).upper(), clean(row.get("quarter"))


def _expected_prior_quarter(quarter: str) -> str:
    try:
        return prior_quarter(quarter)
    except Exception:  # noqa: BLE001 - validation reports the bad value downstream.
        return ""


def _dedupe_prior_rows(rows: list[dict[str, Any]], *, expected_prior_quarter: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    duplicates: list[str] = []
    expected_rows: list[dict[str, Any]] = []
    for row in rows:
        key = _row_key(row)
        if key in by_key:
            duplicates.append(f"{key[0]}:{key[1]}")
            continue
        by_key[key] = row
        if key[1] == expected_prior_quarter:
            expected_rows.append(row)
    summary = {
        "prior_context_rows": len(rows),
        "expected_prior_quarter": expected_prior_quarter,
        "expected_prior_context_rows": len(expected_rows),
        "prior_duplicate_key_count": len(duplicates),
        "prior_duplicate_keys": sorted(set(duplicates))[:25],
    }
    return expected_rows, summary


def load_prior_context(path: Path | None, *, current_quarter: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    expected = _expected_prior_quarter(current_quarter)
    if path is None:
        return [], {"prior_context_loaded": False, "expected_prior_quarter": expected, "reason": "missing_prior_final_scores"}
    if not path.exists() or path.stat().st_size == 0:
        return [], {"prior_context_loaded": False, "prior_context_path": str(path), "expected_prior_quarter": expected, "reason": "prior_final_scores_missing_or_empty"}
    rows = read_rows(path)
    expected_rows, summary = _dedupe_prior_rows(rows, expected_prior_quarter=expected)
    summary.update({"prior_context_loaded": True, "prior_context_path": str(path)})
    if summary["prior_duplicate_key_count"]:
        summary["reason"] = "duplicate_prior_ticker_quarter_rows"
    elif not expected_rows:
        summary["reason"] = "no_rows_for_expected_prior_quarter"
    return expected_rows, summary


def add_qoq_context(rows: list[dict[str, Any]], prior_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    prior_by_key = {_row_key(row): row for row in prior_rows}
    enriched: list[dict[str, Any]] = []
    matched = 0
    for raw in rows:
        row = dict(raw)
        prior = prior_by_key.get((clean(row.get("ticker")).upper(), _expected_prior_quarter(clean(row.get("quarter"))))) or {}
        if prior:
            matched += 1
        current_entry = to_float(row.get("entry_open"))
        prior_entry = to_float(prior.get("entry_open"))
        if current_entry is not None and prior_entry is not None and prior_entry > 0:
            row["entry_qoq_pct"] = round((current_entry / prior_entry - 1) * 100, 4)
        else:
            row.setdefault("entry_qoq_pct", "")
        if clean(prior.get("entry_qoq_pct")):
            row["prior_entry_qoq_pct"] = prior.get("entry_qoq_pct")
        else:
            row.setdefault("prior_entry_qoq_pct", "")
        current_score = to_float(row.get("pre_llm_fundamental_score"))
        prior_score = to_float(prior.get("pre_llm_fundamental_score"))
        if current_score is not None and prior_score is not None:
            row["score_change"] = round(current_score - prior_score, 4)
        else:
            row.setdefault("score_change", "")
        if clean(prior.get("pre_llm_fundamental_score")):
            row["prior_pre_llm_fundamental_score"] = prior.get("pre_llm_fundamental_score")
        else:
            row.setdefault("prior_pre_llm_fundamental_score", "")
        enriched.append(row)
    return enriched, {"qoq_context_match_rows": matched, "qoq_context_input_rows": len(rows)}


def _qoq_presence_summary(final_rows: list[dict[str, Any]]) -> dict[str, Any]:
    llm_complete = [row for row in final_rows if clean(row.get("llm_status")) == "complete"]
    missing = [
        clean(row.get("ticker")).upper()
        for row in llm_complete
        if any(not clean(row.get(field)) for field in QOQ_REQUIRED_FIELDS)
    ]
    return {
        "llm_complete_rows": len(llm_complete),
        "llm_complete_qoq_ready_rows": len(llm_complete) - len(missing),
        "llm_complete_qoq_missing_rows": len(missing),
        "llm_complete_qoq_missing_tickers": missing[:50],
    }


def build_final_scores(
    broad_rows: list[dict[str, Any]],
    *,
    as_of: str,
    post_llm_rows: list[dict[str, Any]] | None,
    prior_context_rows: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows_for_scoring, qoq_summary = add_qoq_context(broad_rows, prior_context_rows or [])
    signal_rows, tier_rows, pre_rows = build_signal_tables(
        rows_for_scoring,
        as_of=as_of,
        post_llm_rows=post_llm_rows or [],
        prior_rows=prior_context_rows or [],
    )
    summary = {
        "broad_rows": len(broad_rows),
        "post_llm_rows": len(post_llm_rows or []),
        "prior_context_rows": len(prior_context_rows or []),
        "final_score_rows": len(signal_rows),
        "tier_rows": len(tier_rows),
        "pre_rows": len(pre_rows),
        **qoq_summary,
        **_qoq_presence_summary(signal_rows),
    }
    return signal_rows, summary


def validate_broad_final_scores(
    *,
    final_rows: list[dict[str, Any]],
    broad_universe_count: int,
    explicit_invalid_quarantine_count: int,
    run_mode: RunMode,
    artifacts: dict[str, str],
    prior_context_summary: dict[str, Any] | None = None,
) -> GateResult:
    reconciled = len(final_rows) + int(explicit_invalid_quarantine_count)
    qoq_summary = _qoq_presence_summary(final_rows)
    prior_summary = dict(prior_context_summary or {})
    summary = {
        "final_score_rows": len(final_rows),
        "explicit_invalid_quarantine_count": int(explicit_invalid_quarantine_count),
        "reconciled_count": reconciled,
        "broad_universe_count": broad_universe_count,
        **prior_summary,
        **qoq_summary,
    }
    if run_mode == RunMode.BROAD_MASTER_FINAL:
        if not prior_summary.get("prior_context_loaded"):
            summary.setdefault("reason", "missing_prior_final_scores")
            return GateResult(9, "Final scoring, HP buckets, RM buckets, and QoQ context", GateStatus.HARD_STOP, summary, artifacts)
        if prior_summary.get("prior_duplicate_key_count"):
            summary.setdefault("reason", "duplicate_prior_ticker_quarter_rows")
            return GateResult(9, "Final scoring, HP buckets, RM buckets, and QoQ context", GateStatus.HARD_STOP, summary, artifacts)
        if not prior_summary.get("expected_prior_context_rows"):
            summary.setdefault("reason", "no_rows_for_expected_prior_quarter")
            return GateResult(9, "Final scoring, HP buckets, RM buckets, and QoQ context", GateStatus.HARD_STOP, summary, artifacts)
        if qoq_summary["llm_complete_qoq_missing_rows"]:
            summary["reason"] = "llm_complete_rows_missing_qoq_context"
            return GateResult(9, "Final scoring, HP buckets, RM buckets, and QoQ context", GateStatus.HARD_STOP, summary, artifacts)
        if reconciled != broad_universe_count:
            summary["reason"] = "final_scores_plus_quarantine_do_not_reconcile_to_broad_universe"
            return GateResult(9, "Final scoring, HP buckets, RM buckets, and QoQ context", GateStatus.HARD_STOP, summary, artifacts)
    return GateResult(9, "Final scoring, HP buckets, RM buckets, and QoQ context", GateStatus.PASS, summary, artifacts)


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
    explicit_invalid_quarantine_count: int = 0,
    coverage_manifest: Path | None = None,
) -> GateResult:
    import pandas as pd

    frame = pd.read_csv(scores_csv).fillna("")
    reconciled = int(len(frame)) + int(explicit_invalid_quarantine_count)
    summary = {"input_rows": int(len(frame)), "explicit_invalid_quarantine_count": int(explicit_invalid_quarantine_count), "reconciled_count": reconciled, "broad_universe_count": broad_universe_count}
    if reconciled != broad_universe_count:
        summary["reason"] = "top15_input_plus_quarantine_not_broad_reconciled"
        return GateResult(10, "Top10 + Plus5 + shadow refill publish", GateStatus.HARD_STOP, summary, {"scores_csv": str(scores_csv)})

    try:
        from tradingagents.research.fundamental.src.selection.high_conviction_top10 import (
            select_top15_core_deterioration_refill_shadow_from_csv,
            select_top15_from_csv,
        )

        top15 = select_top15_from_csv(
            scores_csv,
            output_root,
            {
                "selection_date": as_of,
                "enabled": True,
                "core_n": 10,
                "exception_slots": 5,
                "coverage_gating": bool(coverage_manifest),
            },
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
                "coverage_gating": bool(coverage_manifest),
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
