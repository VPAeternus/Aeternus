"""Top-15 exception-sleeve PIT backtest exporter."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence
from uuid import uuid4

from tradingagents.research.fundamental.backtests.high_conviction_top10 import (
    FORBIDDEN_SELECTION_COLUMNS,
    LABEL_COLUMNS,
    OUTCOME_COLUMNS,
    _avg,
    _eligible_groups,
    _feature_columns,
    _file_sha256,
    _rate,
    _read_csv,
    _to_float,
    _truthy,
    _v2_candidates,
    _validate_unique_ticker_quarter,
    _write_csv,
)
from tradingagents.research.fundamental.src.selection.high_conviction_top10 import (
    CORE_DETERIORATION_FIELDS,
    CORE_DETERIORATION_REFILL_FIELDS,
    RightTailExceptionConfig,
    _select_exception_sleeve,
    build_core_deterioration_review_rows,
    core_deterioration_flags,
    select_high_conviction_top15_exception_sleeve,
    should_refill_demote_core_row,
)
from tradingagents.research.fundamental.src.selection.right_tail_queues import (
    FORBIDDEN_RIGHT_TAIL_ROUTING_COLUMNS,
    QUEUE_CSV_FIELDS,
    RIGHT_TAIL_SCORING_COLUMNS,
    TARGET_AUDIT_FIELDS,
    build_right_tail_queues,
    build_target_visibility_audit,
    is_forbidden_right_tail_routing_column,
    rank_thin_signal_watchlist,
    split_demote_review_priority,
)

RUNNER_VERSION = "fundamental_high_conviction_top15_exception_sleeve_backtest_v1"
DEFAULT_OUTPUT_DIR = Path("outputs/fundamental_backtest/high_conviction_top15_exception_sleeve")
TARGET_RIGHT_TAIL_EVENTS = {
    "CRNC": "2024Q4",
    "CVNA": "2023Q2",
    "SNDK": "2025Q3",
    "AAOI": "2023Q2",
    "BE": "2025Q3",
    "AXTI": "2026Q1",
    "AEHR": "2026Q1",
    "ICHR": "2026Q1",
    "CRDO": "2024Q3",
}
TARGET_RIGHT_TAIL_NAMES = list(TARGET_RIGHT_TAIL_EVENTS)
TOP15_VARIANTS: dict[str, RightTailExceptionConfig] = {
    "high_conviction_top15_v3_exception_sleeve": RightTailExceptionConfig(enabled=True, core_n=10, exception_slots=5),
    "top15_conservative_10_core_3_exception": RightTailExceptionConfig(enabled=True, core_n=10, exception_slots=3),
    "top15_rm1_priority_max2_rm2plus": RightTailExceptionConfig(enabled=True, core_n=10, exception_slots=5, max_rm2plus_slots=2),
}
CORE_DETERIORATION_REFILL_SHADOW_VARIANTS = {
    "top15_v4_core_deterioration_refill_strict": "strict",
    "top15_v4_core_deterioration_refill_downgrade": "downgrade",
}
CORE_DETERIORATION_REFILL_SELECTED_FIELDS = [
    "variant", "quarter", "selection_rank", "selected_sleeve", "selected_sleeve_rank", "ticker",
    "core_refill_source", "demoted_replacement_for", "right_tail_exception_score", *LABEL_COLUMNS,
]
CORE_DETERIORATION_REFILL_HISTORICAL_FIELDS = [
    *CORE_DETERIORATION_REFILL_FIELDS,
    "demoted_return_90d_pct", "replacement_return_90d_pct", "replacement_delta_90d_pct",
]
CORE_DETERIORATION_REFILL_SUMMARY_FIELDS = [
    "variant", "quarter_count", "core_count", "exception_count", "total_picks", "avg_picks_per_quarter",
    "avg_return_90d_pct", "winner_90d_30pct_rate", "loser_90d_minus30pct_rate",
]
BASELINE_VARIANT = "high_conviction_top10_v2_final"
OUTPUT_FILES = [
    "selected_names_by_quarter_top15.csv",
    "strategy_summary_top15.csv",
    "strategy_by_quarter_top15.csv",
    "core_vs_exception_contribution.csv",
    "exception_slot_diagnostics.csv",
    "core_deterioration_review_queue.csv",
    "core_deterioration_refill_shadow_selected.csv",
    "core_deterioration_refill_shadow_replacements.csv",
    "core_deterioration_refill_shadow_summary.csv",
    "right_tail_capture_comparison.csv",
    "left_tail_penalty_comparison.csv",
    "missed_right_tail_after_top15.csv",
    "top15_exception_candidate_queue.csv",
    "right_tail_scout_queue.csv",
    "demote_review_queue.csv",
    "demote_review_priority_1.csv",
    "demote_review_priority_2.csv",
    "demote_review_low_priority.csv",
    "thin_signal_watchlist_queue.csv",
    "thin_signal_watchlist_top100.csv",
    "right_tail_evidence_score_diagnostics.csv",
    "pit_feature_lineage_audit.csv",
    "target_miss_rescue_audit.csv",
    "v4_rescue_variant_summary.csv",
    "README_ANALYSIS.md",
]
SAFE_SELECTOR_REQUIRED_COLUMNS = {
    "confidence",
    "cik",
    "cik_status",
    "document_status",
    "hard_reject_reason",
}
PIT_AUDIT_FIELDS = ["field", "layer", "present_in_input", "pit_provenance_field", "pit_status", "notes"]


def _is_forbidden_selection_column(column: str) -> bool:
    name = str(column or "").strip().lower()
    return name in FORBIDDEN_SELECTION_COLUMNS or is_forbidden_right_tail_routing_column(name)


def _is_forbidden_output_extra_column(column: str) -> bool:
    return _is_forbidden_selection_column(column) and column not in OUTCOME_COLUMNS


def _pit_family(field: str) -> str:
    name = field.lower()
    if name == "akg_universe_tier" or name.startswith("akg_"):
        return "akg"
    if name.startswith("macro_"):
        return "macro"
    if name.startswith("theme_") or name.startswith("filing_theme_") or name in {"primary_theme", "secondary_themes"}:
        return "theme"
    if name.startswith("rm") or name.startswith("repricing_") or name == "market_repricing_score":
        return "rm"
    if name.startswith("hp"):
        return "hp"
    if name.startswith("tier_") or name == "tier_structure_score":
        return "tier"
    if "score" in name or name.startswith("post_llm_"):
        return "scoring"
    return "source"


def _pit_provenance_candidates(field: str) -> tuple[str, ...]:
    family = _pit_family(field)
    return {
        "akg": ("akg_pit_snapshot_id", "akg_rule_version", "source_file_hash"),
        "macro": ("macro_rule_version", "source_file_hash"),
        "theme": ("theme_rule_version", "source_file_hash"),
        "rm": ("rm_rule_version", "source_file_hash"),
        "hp": ("hp_rule_version", "source_file_hash"),
        "tier": ("tier_rule_version", "source_file_hash"),
        "scoring": ("scoring_formula_version", "source_file_hash"),
        "source": ("source_file_hash", "pipeline_run_id"),
    }[family]


def _build_pit_feature_lineage_audit(headers: Sequence[str], selection_fields: Sequence[str], right_tail_fields: Sequence[str]) -> list[dict[str, Any]]:
    header_set = set(headers)
    selection_set = set(selection_fields)
    right_tail_set = set(right_tail_fields)
    rows: list[dict[str, Any]] = []
    for field in sorted(selection_set | right_tail_set):
        in_selection = field in selection_set
        in_right_tail = field in right_tail_set
        layer = "both" if in_selection and in_right_tail else "top15_selection" if in_selection else "right_tail_routing"
        family = _pit_family(field)
        candidates = _pit_provenance_candidates(field)
        present_provenance = [candidate for candidate in candidates if candidate in header_set]
        present = field in header_set
        if not present:
            status = "field_missing_unavailable_or_neutral"
            notes = "Field absent from PIT panel; treated as unavailable/neutral by existing scoring where applicable."
        elif family == "akg" and not any(c.startswith("akg_") for c in present_provenance):
            status = "not_full_production_v2_validated_missing_pit_provenance"
            notes = "AKG/T5_RESCAN field present but no dedicated AKG PIT snapshot provenance; audit only, not full production-v2 validated."
        elif family in {"theme", "macro"}:
            status = "not_full_production_v2_validated"
            notes = f"{family} field present; rule/source provenance is documented but full historical PIT {family} provenance remains a production-v2 dependency."
        elif present_provenance and set(present_provenance) <= {"source_file_hash", "pipeline_run_id"}:
            status = "source_only_not_field_validated"
            notes = "Input source/run provenance is present, but field-level PIT/as-of provenance is not separately validated."
        elif present_provenance:
            status = "pit_documented"
            notes = "PIT lineage has source/rule provenance column in input manifest."
        else:
            status = "pit_provenance_unavailable"
            notes = "No PIT provenance column found in input; audit-only until provenance is added."
        rows.append({
            "field": field,
            "layer": layer,
            "present_in_input": int(present),
            "pit_provenance_field": ";".join(present_provenance) if present_provenance else ";".join(candidates),
            "pit_status": status,
            "notes": notes,
        })
    return rows


def _read_any_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        return list(reader), list(reader.fieldnames or [])


def _freeze(row: Mapping[str, Any], original: Mapping[str, Any], variant: str, quarter: str, rank: int) -> dict[str, Any]:
    out = {k: v for k, v in dict(row).items() if not _is_forbidden_output_extra_column(str(k))}
    out.update({c: original.get(c, "") for c in OUTCOME_COLUMNS if c in original})
    out.update({"variant": variant, "quarter": quarter, "snapshot_date": original.get("tradable_date", ""), "tradable_date": original.get("tradable_date", ""), "selection_rank": rank, "ticker": str(original.get("ticker", row.get("ticker", ""))).upper()})
    out.setdefault("selected_sleeve", "core")
    out.setdefault("selected_sleeve_rank", rank)
    return out


def _summarize_quarter(variant: str, quarter: str, picks: Sequence[Mapping[str, Any]], eligible_count: int, capacity: int) -> dict[str, Any]:
    row: dict[str, Any] = {"variant": variant, "quarter": quarter, "pick_count": len(picks), "eligible_count": eligible_count, "shortfall": len(picks) < capacity}
    for col in LABEL_COLUMNS:
        row[f"avg_{col}"] = _avg(picks, col)
    row["winner_90d_30pct_rate"] = _rate(picks, "winner_90d_30pct")
    row["loser_90d_minus30pct_rate"] = _rate(picks, "loser_90d_minus30pct")
    return row


def _aggregate(variant: str, picks: Sequence[Mapping[str, Any]], quarters: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    qrows = [r for r in quarters if r["variant"] == variant]
    row: dict[str, Any] = {"variant": variant, "quarter_count": len(qrows), "total_picks": len(picks), "avg_picks_per_quarter": f"{len(picks) / len(qrows):.6f}" if qrows else ""}
    for col in LABEL_COLUMNS:
        row[f"avg_{col}"] = _avg(qrows, f"avg_{col}")
    row["winner_90d_30pct_rate"] = _avg(qrows, "winner_90d_30pct_rate")
    row["loser_90d_minus30pct_rate"] = _avg(qrows, "loser_90d_minus30pct_rate")
    nums = [(str(r["quarter"]), _to_float(r.get("avg_return_90d_pct"))) for r in qrows]
    nums = [(q, v) for q, v in nums if v is not None]
    row["worst_quarter_avg_90d"] = f"{min(v for _, v in nums):.6f}" if nums else ""
    row["best_quarter_avg_90d"] = f"{max(v for _, v in nums):.6f}" if nums else ""
    q1 = [r for r in qrows if r["quarter"] == "2025Q1"]
    row["2025Q1_avg_90d"] = q1[0].get("avg_return_90d_pct", "") if q1 else ""
    row["2025Q1_loser_rate"] = q1[0].get("loser_90d_minus30pct_rate", "") if q1 else ""
    return row


def _baseline_rows(prior_path: Path) -> list[dict[str, Any]]:
    rows, _ = _read_any_csv(prior_path)
    out = [
        {**{k: v for k, v in r.items() if not _is_forbidden_output_extra_column(str(k))}, "selected_sleeve": "core", "selected_sleeve_rank": r.get("selection_rank", "")}
        for r in rows
        if r.get("variant") == BASELINE_VARIANT
    ]
    return out


def _top_names(rows: Sequence[Mapping[str, Any]], reverse: bool) -> str:
    ranked = sorted(rows, key=lambda r: (_to_float(r.get("return_90d_pct")) if _to_float(r.get("return_90d_pct")) is not None else float("-inf")), reverse=reverse)[:5]
    return ";".join(f"{r.get('ticker')}:{r.get('return_90d_pct')}" for r in ranked)


def _core_exception_rows(picks: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    by_variant: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for r in picks:
        groups[(str(r["variant"]), str(r.get("selected_sleeve", "core")))].append(r); by_variant[str(r["variant"])].append(r)
    rows = []
    for (variant, sleeve), rs in sorted(groups.items()):
        total = len(by_variant[variant]) or 1
        rows.append({"variant": variant, "sleeve": sleeve, "pick_count": len(rs), "avg_return_90d_pct": _avg(rs, "return_90d_pct"), "winner_90d_30pct_rate": _rate(rs, "winner_90d_30pct"), "loser_90d_minus30pct_rate": _rate(rs, "loser_90d_minus30pct"), "contribution_to_strategy_avg": f"{len(rs) / total * (_to_float(_avg(rs, 'return_90d_pct')) or 0):.6f}", "top_winners": _top_names(rs, True), "top_losers": _top_names(rs, False)})
    return rows


def _status_map(rows: Sequence[Mapping[str, Any]]) -> dict[tuple[str, str, str], Mapping[str, Any]]:
    return {(str(r.get("variant")), str(r.get("quarter")), str(r.get("ticker", "")).upper()): r for r in rows}


def _mechanical(row: Mapping[str, Any], selected: Mapping[str, Any] | None) -> str:
    if selected:
        return "SELECTED"
    score = _to_float(row.get("entry_score_0_100"))
    if score is None or score < 20:
        return "ENTRY_SCORE_BELOW_EXCEPTION_MIN"
    if _truthy(row.get("post_llm_demote_flag")):
        return "POST_LLM_DEMOTE"
    return "NOT_RANKED_IN_SELECTED_SLOTS"


def _validate_selected(rows: Sequence[Mapping[str, Any]]) -> None:
    seen_ticker: set[tuple[str, str, str]] = set(); seen_rank: set[tuple[str, str, str, str]] = set()
    for r in rows:
        kt = (str(r["variant"]), str(r["quarter"]), str(r["ticker"]))
        kr = (str(r["variant"]), str(r["quarter"]), str(r.get("selected_sleeve", "")), str(r.get("selected_sleeve_rank", "")))
        if kt in seen_ticker:
            raise ValueError(f"duplicate (variant,quarter,ticker): {kt}")
        if kr in seen_rank:
            raise ValueError(f"duplicate sleeve rank: {kr}")
        seen_ticker.add(kt); seen_rank.add(kr)


def _core_refill_flag_row(row: Mapping[str, Any], rank: int) -> dict[str, Any]:
    return {**dict(row), "selected_sleeve": "core", "selected_sleeve_rank": rank, "selection_rank": rank}


def _build_refill_replacement_row(variant: str, quarter: str, mode: str, demoted: Mapping[str, Any], replacement: Mapping[str, Any], by_ticker: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    demoted_ticker = str(demoted.get("ticker", "")).upper()
    replacement_ticker = str(replacement.get("ticker", "")).upper()
    d_original = by_ticker.get(demoted_ticker, {})
    r_original = by_ticker.get(replacement_ticker, {})
    d_ret = _to_float(d_original.get("return_90d_pct"))
    r_ret = _to_float(r_original.get("return_90d_pct"))
    flags = core_deterioration_flags(_core_refill_flag_row(demoted, int(_to_float(demoted.get("core_candidate_rank")) or 999999)))
    return {
        "variant": variant,
        "quarter": quarter,
        "mode": mode,
        "demoted_ticker": demoted_ticker,
        "replacement_ticker": replacement_ticker,
        "demoted_core_candidate_rank": demoted.get("core_candidate_rank", ""),
        "replacement_core_candidate_rank": replacement.get("core_candidate_rank", ""),
        "demoted_entry_score_0_100": demoted.get("entry_score_0_100", ""),
        "replacement_entry_score_0_100": replacement.get("entry_score_0_100", ""),
        "demoted_score_change": demoted.get("score_change", ""),
        "demoted_negative_revision_risk": demoted.get("negative_revision_risk", ""),
        "demoted_pre_llm_fundamental_bucket": demoted.get("pre_llm_fundamental_bucket", ""),
        "demoted_primary_theme": demoted.get("primary_theme", ""),
        "demoted_rm_count": flags.get("core_deterioration_rm_count", ""),
        "demoted_hp_count": flags.get("core_deterioration_hp_count", ""),
        "demoted_market_repricing_score": flags.get("demoted_market_repricing_score", ""),
        "high_score_deterioration_flag": flags.get("high_score_deterioration_flag", ""),
        "weak_no_theme_repricing_stack_flag": flags.get("weak_no_theme_repricing_stack_flag", ""),
        "core_deterioration_review_flag": flags.get("core_deterioration_review_flag", ""),
        "core_deterioration_downgrade_flag": flags.get("core_deterioration_downgrade_flag", ""),
        "core_deterioration_strict_override_required": flags.get("core_deterioration_strict_override_required", ""),
        "core_deterioration_reason_codes": flags.get("core_deterioration_reason_codes", ""),
        "demoted_return_90d_pct": d_original.get("return_90d_pct", ""),
        "replacement_return_90d_pct": r_original.get("return_90d_pct", ""),
        "replacement_delta_90d_pct": f"{(r_ret - d_ret):.6f}" if r_ret is not None and d_ret is not None else "",
    }


def _build_core_deterioration_refill_shadow(variant: str, mode: str, quarter: str, eligible: Sequence[Mapping[str, Any]], selection_safe_cols: Sequence[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    identity_cols = ["ticker", "quarter", "tradable_date", "entry_open", "eligible_for_backtest"]
    cols = list(dict.fromkeys([*identity_cols, *selection_safe_cols]))
    safe_rows = [{c: r.get(c, "") for c in cols} for r in eligible]
    by_ticker = {str(r.get("ticker", "")).upper(): r for r in eligible}
    ranked = _v2_candidates(safe_rows)
    blocked_tickers: set[str] = set()
    for row in safe_rows:
        ticker = str(row.get("ticker", "")).upper()
        if ticker and should_refill_demote_core_row(_core_refill_flag_row(row, 999999), mode):
            blocked_tickers.add(ticker)
    selected_core_raw: list[dict[str, Any]] = []
    demoted_raw: list[dict[str, Any]] = []
    for candidate in ranked:
        ticker = str(candidate.get("ticker", "")).upper()
        rank = int(_to_float(candidate.get("core_candidate_rank")) or 999999)
        if ticker in blocked_tickers:
            if rank <= 10:
                demoted_raw.append(candidate)
            continue
        selected_core_raw.append(candidate)
        if len(selected_core_raw) >= 10:
            break
    selected: list[dict[str, Any]] = []
    replacements_raw = [r for r in selected_core_raw if (_to_float(r.get("core_candidate_rank")) or 0) > 10]
    replacement_by_ticker: dict[str, str] = {}
    replacement_rows: list[dict[str, Any]] = []
    for demoted, replacement in zip(demoted_raw, replacements_raw):
        replacement_by_ticker[str(replacement.get("ticker", "")).upper()] = str(demoted.get("ticker", "")).upper()
        replacement_rows.append(_build_refill_replacement_row(variant, quarter, mode, demoted, replacement, by_ticker))
    for rank, row in enumerate(selected_core_raw, 1):
        ticker = str(row.get("ticker", "")).upper()
        frozen = _freeze({**row, "selected_sleeve": "core", "selected_sleeve_rank": rank}, by_ticker[ticker], variant, quarter, rank)
        frozen["core_refill_source"] = "original_top10" if (_to_float(row.get("core_candidate_rank")) or 999999) <= 10 else "next_ranked_core_candidate"
        frozen["demoted_replacement_for"] = replacement_by_ticker.get(ticker, "")
        selected.append(frozen)
    exceptions, _warnings = _select_exception_sleeve(selected_core_raw, safe_rows, RightTailExceptionConfig(enabled=True, core_n=10, exception_slots=5), blocked_tickers=blocked_tickers)
    for row in exceptions:
        ticker = str(row.get("ticker", "")).upper()
        if ticker not in by_ticker:
            continue
        frozen = _freeze(row, by_ticker[ticker], variant, quarter, len(selected) + 1)
        frozen["selected_sleeve"] = "right_tail_exception"
        frozen["selected_sleeve_rank"] = row.get("selected_sleeve_rank", "")
        frozen["core_refill_source"] = ""
        frozen["demoted_replacement_for"] = ""
        selected.append(frozen)
    return selected, replacement_rows


def _refill_shadow_summary_rows(selected_rows: Sequence[Mapping[str, Any]], quarter_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for variant in CORE_DETERIORATION_REFILL_SHADOW_VARIANTS:
        picks = [r for r in selected_rows if r.get("variant") == variant]
        qrows = [r for r in quarter_rows if r.get("variant") == variant]
        rows.append({
            "variant": variant,
            "quarter_count": len(qrows),
            "core_count": sum(1 for r in picks if r.get("selected_sleeve") == "core"),
            "exception_count": sum(1 for r in picks if r.get("selected_sleeve") == "right_tail_exception"),
            "total_picks": len(picks),
            "avg_picks_per_quarter": f"{len(picks) / len(qrows):.6f}" if qrows else "",
            "avg_return_90d_pct": _avg(qrows, "avg_return_90d_pct"),
            "winner_90d_30pct_rate": _avg(qrows, "winner_90d_30pct_rate"),
            "loser_90d_minus30pct_rate": _avg(qrows, "loser_90d_minus30pct_rate"),
        })
    return rows


def run_high_conviction_top15_exception_sleeve_backtest(pit_panel: str | Path, prior_selected: str | Path, out_dir: str | Path = DEFAULT_OUTPUT_DIR, run_id: str | None = None) -> dict[str, Any]:
    panel_path, prior_path, out = Path(pit_panel), Path(prior_selected), Path(out_dir)
    rows, headers = _read_csv(panel_path); _validate_unique_ticker_quarter(rows)
    baseline = _baseline_rows(prior_path)
    groups = _eligible_groups(rows); feature_cols = _feature_columns(headers)
    out.mkdir(parents=True, exist_ok=True)
    selected_rows: list[dict[str, Any]] = list(baseline)
    quarter_rows: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    refill_selected_rows: list[dict[str, Any]] = []
    refill_replacement_rows: list[dict[str, Any]] = []
    refill_quarter_rows: list[dict[str, Any]] = []
    status = _status_map(baseline)
    baseline_by_quarter: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in baseline:
        baseline_by_quarter[str(row.get("quarter"))].append(row)
    for qrows in baseline_by_quarter.values():
        qrows.sort(key=lambda r: int(_to_float(r.get("selection_rank")) or 999999))

    for q in sorted(groups):
        eligible = sorted(groups[q], key=lambda r: str(r.get("ticker", "")).upper())
        quarter_rows.append(_summarize_quarter(BASELINE_VARIANT, q, [r for r in baseline if r.get("quarter") == q], len(eligible), 10))
        safe_cols = list(dict.fromkeys([*feature_cols, *[c for c in headers if c in SAFE_SELECTOR_REQUIRED_COLUMNS and not _is_forbidden_selection_column(c)]]))
        safe = [{c: r.get(c, "") for c in safe_cols} for r in eligible]
        by_ticker = {str(r.get("ticker", "")).upper(): r for r in eligible}
        for variant, cfg in TOP15_VARIANTS.items():
            result = select_high_conviction_top15_exception_sleeve(safe, cfg)
            frozen = []
            core_tickers: set[str] = set()
            for rank, baseline_core in enumerate(baseline_by_quarter.get(q, [])[: cfg.core_n], 1):
                ticker = str(baseline_core.get("ticker", "")).upper()
                if ticker not in by_ticker:
                    continue
                core_tickers.add(ticker)
                frozen.append(_freeze({**baseline_core, "selected_sleeve": "core", "selected_sleeve_rank": rank}, by_ticker[ticker], variant, q, rank))
            exception_rank = 0
            for r in result["selected_rows"]:
                ticker = str(r.get("ticker", "")).upper()
                if ticker in core_tickers or r.get("selected_sleeve") != "right_tail_exception":
                    continue
                exception_rank += 1
                frozen.append(_freeze(r, by_ticker[ticker], variant, q, len(frozen) + 1))
                frozen[-1]["selected_sleeve_rank"] = exception_rank
            selected_rows.extend(frozen); quarter_rows.append(_summarize_quarter(variant, q, frozen, len(eligible), cfg.core_n + cfg.exception_slots))
            status.update(_status_map(frozen))
            exception_rows = [r for r in frozen if r.get("selected_sleeve") == "right_tail_exception"]
            available = [r for r in result.get("rejected_rows", []) if r.get("right_tail_exception_score")]
            diagnostics.append({"variant": variant, "quarter": q, "selected_exception_count": len(exception_rows), "available_exception_candidate_count": len(exception_rows) + len(available), "warning_codes": ";".join(result.get("summary", {}).get("warnings", [])), "selected_exception_tickers": ";".join(r["ticker"] for r in exception_rows), "single_rm_exception_count": sum(str(r.get("rm_signal_bucket")) == "1" for r in exception_rows), "rm2plus_exception_count": sum(str(r.get("rm_signal_bucket")) == "2+" for r in exception_rows), "no_theme_no_llm_exception_count": sum(not (str(r.get("primary_theme", "")).strip() or _truthy(r.get("hp_LLM_best"))) for r in exception_rows)})
        for refill_variant, mode in CORE_DETERIORATION_REFILL_SHADOW_VARIANTS.items():
            refill_selected, refill_replacements = _build_core_deterioration_refill_shadow(refill_variant, mode, q, eligible, safe_cols)
            refill_selected_rows.extend(refill_selected)
            refill_replacement_rows.extend(refill_replacements)
            refill_quarter_rows.append(_summarize_quarter(refill_variant, q, refill_selected, len(eligible), 15))

    _validate_selected([r for r in selected_rows if r["variant"] != BASELINE_VARIANT] + baseline)
    variants = [BASELINE_VARIANT, *TOP15_VARIANTS.keys()]
    summary = [_aggregate(v, [r for r in selected_rows if r["variant"] == v], quarter_rows) for v in variants]
    right_tail = [r for r in rows if _truthy(r.get("eligible_for_backtest")) and (_to_float(r.get("return_90d_pct")) or -999) >= 100]
    comparison = []
    main_top15_variant = "high_conviction_top15_v3_exception_sleeve"
    for r in right_tail:
        q, t = str(r.get("quarter")), str(r.get("ticker", "")).upper(); top15_hit = status.get((main_top15_variant, q, t))
        comparison.append({"ticker": t, "quarter": q, "return_90d_pct": r.get("return_90d_pct"), "old_v2_status": "selected" if status.get((BASELINE_VARIANT, q, t)) else "missed", "top15_status": "selected" if top15_hit else "missed", "selected_sleeve": top15_hit.get("selected_sleeve", "") if top15_hit else "", "selected_sleeve_rank": top15_hit.get("selected_sleeve_rank", "") if top15_hit else "", "right_tail_exception_score": top15_hit.get("right_tail_exception_score", "") if top15_hit else "", "mechanical_exclusion_before": _mechanical(r, status.get((BASELINE_VARIANT, q, t))), "mechanical_status_after": _mechanical(r, top15_hit)})
    for t in TARGET_RIGHT_TAIL_NAMES:
        if not any(r["ticker"] == t for r in comparison):
            comparison.append({"ticker": t, "quarter": "NOT_PRESENT_AS_2X_ELIGIBLE", "return_90d_pct": "", "old_v2_status": "not_present", "top15_status": "not_present", "selected_sleeve": "", "selected_sleeve_rank": "", "right_tail_exception_score": "", "mechanical_exclusion_before": "NOT_PRESENT", "mechanical_status_after": "NOT_PRESENT"})
    missed = [r for r in comparison if r["top15_status"] != "selected" and r["quarter"] != "NOT_PRESENT_AS_2X_ELIGIBLE"]
    base_summary = next((r for r in summary if r["variant"] == BASELINE_VARIANT), {})
    left_tail = [{"variant": r["variant"], "loser_90d_minus30pct_rate": r.get("loser_90d_minus30pct_rate", ""), "avg_return_90d_pct": r.get("avg_return_90d_pct", ""), "2025Q1_avg_90d": r.get("2025Q1_avg_90d", ""), "2025Q1_loser_rate": r.get("2025Q1_loser_rate", ""), "delta_loser_rate_vs_top10": f"{((_to_float(r.get('loser_90d_minus30pct_rate')) or 0) - (_to_float(base_summary.get('loser_90d_minus30pct_rate')) or 0)):.6f}"} for r in summary]
    prior_selected_output = out / "selected_names_by_quarter_top15.csv"
    prior_selected_hash = _file_sha256(prior_selected_output) if prior_selected_output.exists() else ""

    _write_csv(out / "selected_names_by_quarter_top15.csv", selected_rows, ["variant", "quarter", "selection_rank", "selected_sleeve", "selected_sleeve_rank", "ticker", "right_tail_exception_score", *LABEL_COLUMNS])
    _write_csv(out / "strategy_summary_top15.csv", summary, ["variant", "quarter_count", "total_picks", "avg_picks_per_quarter"])
    _write_csv(out / "strategy_by_quarter_top15.csv", quarter_rows, ["variant", "quarter", "pick_count", "eligible_count", "shortfall"])
    _write_csv(out / "core_vs_exception_contribution.csv", _core_exception_rows(selected_rows), ["variant", "sleeve", "pick_count", "avg_return_90d_pct", "winner_90d_30pct_rate", "loser_90d_minus30pct_rate", "contribution_to_strategy_avg", "top_winners", "top_losers"])
    _write_csv(out / "exception_slot_diagnostics.csv", diagnostics, ["variant", "quarter", "selected_exception_count", "available_exception_candidate_count", "warning_codes", "selected_exception_tickers", "single_rm_exception_count", "rm2plus_exception_count", "no_theme_no_llm_exception_count"])
    core_deterioration_rows = build_core_deterioration_review_rows([row for row in selected_rows if row.get("variant") == main_top15_variant])
    _write_csv(out / "core_deterioration_review_queue.csv", core_deterioration_rows, CORE_DETERIORATION_FIELDS)
    _write_csv(out / "core_deterioration_refill_shadow_selected.csv", refill_selected_rows, CORE_DETERIORATION_REFILL_SELECTED_FIELDS)
    _write_csv(out / "core_deterioration_refill_shadow_replacements.csv", refill_replacement_rows, CORE_DETERIORATION_REFILL_HISTORICAL_FIELDS)
    _write_csv(out / "core_deterioration_refill_shadow_summary.csv", _refill_shadow_summary_rows(refill_selected_rows, refill_quarter_rows), CORE_DETERIORATION_REFILL_SUMMARY_FIELDS)
    _write_csv(out / "right_tail_capture_comparison.csv", comparison, ["ticker", "quarter", "return_90d_pct", "old_v2_status", "top15_status", "selected_sleeve", "selected_sleeve_rank", "right_tail_exception_score", "mechanical_exclusion_before", "mechanical_status_after"])
    _write_csv(out / "left_tail_penalty_comparison.csv", left_tail, ["variant", "loser_90d_minus30pct_rate", "avg_return_90d_pct", "2025Q1_avg_90d", "2025Q1_loser_rate", "delta_loser_rate_vs_top10"])
    top15_selected_keys = {
        (str(row.get("ticker", "")).upper(), str(row.get("quarter", "")))
        for row in selected_rows
        if row.get("variant") == main_top15_variant
    }
    queue_input = [
        {k: v for k, v in row.items() if not is_forbidden_right_tail_routing_column(str(k))}
        for row in rows
        if _truthy(row.get("eligible_for_backtest"))
    ]
    queues = build_right_tail_queues(queue_input, top15_selected_keys)
    target_audit = build_target_visibility_audit(queue_input, queues["right_tail_evidence_score_diagnostics"], list(TARGET_RIGHT_TAIL_EVENTS.items()))
    for audit_row in target_audit:
        selected_hit = status.get((main_top15_variant, str(audit_row.get("target_quarter")), str(audit_row.get("ticker", "")).upper()))
        if selected_hit:
            audit_row["selected_in_top15_v3"] = 1
            audit_row["selected_sleeve"] = selected_hit.get("selected_sleeve", "")
            audit_row["target_buy_underwriting_routed"] = 1
            audit_row["target_visibility_routed"] = 1
            audit_row["target_actionable_research_routed"] = 1
            audit_row["target_scout_or_top15_routed"] = 1
    visibility_count = sum(str(r.get("target_visibility_routed")) == "1" for r in target_audit)
    actionable_count = sum(str(r.get("target_actionable_research_routed")) == "1" for r in target_audit)
    scout_or_top15_count = sum(str(r.get("target_scout_or_top15_routed")) == "1" for r in target_audit)
    demote_review_count = sum(str(r.get("target_demote_review_routed")) == "1" for r in target_audit)
    buy_count = sum(str(r.get("target_buy_underwriting_routed")) == "1" for r in target_audit)
    soft_demote_routed_count = sum(
        str(r.get("target_actionable_research_routed")) == "1"
        for r in target_audit
        if r.get("miss_failure_mode") == "POST_LLM_DEMOTE"
    )
    supplier_routed_count = sum(
        str(r.get("target_visibility_routed")) == "1"
        for r in target_audit
        if r.get("miss_failure_mode") == "ENTRY_SCORE_BELOW_EXCEPTION_MIN"
    )
    v4_rows = [
        {"variant": "top15_v4_exception_plus_scout", "routed_target_count": visibility_count, "visibility_routed_count": visibility_count, "actionable_research_routed_count": actionable_count, "scout_or_top15_routed_count": scout_or_top15_count, "demote_review_routed_count": demote_review_count, "buy_underwriting_routed_count": buy_count, "description": "Top15 selected plus scout/demote/watchlist visibility routes; visibility diagnostic, not a buy list."},
        {"variant": "top15_v4_soft_demote_override", "routed_target_count": soft_demote_routed_count, "visibility_routed_count": visibility_count, "actionable_research_routed_count": actionable_count, "scout_or_top15_routed_count": scout_or_top15_count, "demote_review_routed_count": demote_review_count, "buy_underwriting_routed_count": buy_count, "description": "Soft/unknown demote visibility diagnostic; demote review is actionable only with positive evidence, never buy underwriting."},
        {"variant": "top15_v4_theme_akg_supplier_rescue", "routed_target_count": supplier_routed_count, "visibility_routed_count": visibility_count, "actionable_research_routed_count": actionable_count, "scout_or_top15_routed_count": scout_or_top15_count, "demote_review_routed_count": demote_review_count, "buy_underwriting_routed_count": buy_count, "description": "Low-entry theme supplier/AKG-style visibility diagnostic, not selected buy underwriting."},
    ]

    safe_cols_manifest = list(dict.fromkeys([*feature_cols, *[c for c in headers if c in SAFE_SELECTOR_REQUIRED_COLUMNS and not _is_forbidden_selection_column(c)]]))
    _write_csv(out / "missed_right_tail_after_top15.csv", missed, ["ticker", "quarter", "return_90d_pct", "mechanical_status_after"])
    _write_csv(out / "top15_exception_candidate_queue.csv", queues["top15_exception_candidate_queue"], QUEUE_CSV_FIELDS)
    _write_csv(out / "right_tail_scout_queue.csv", queues["right_tail_scout_queue"], QUEUE_CSV_FIELDS)
    _write_csv(out / "demote_review_queue.csv", queues["demote_review_queue"], QUEUE_CSV_FIELDS)
    thin_signal_top100 = rank_thin_signal_watchlist(queues["thin_signal_watchlist_queue"], 100)
    demote_priority = split_demote_review_priority(queues["demote_review_queue"])
    _write_csv(out / "demote_review_priority_1.csv", demote_priority["priority_1"], QUEUE_CSV_FIELDS)
    _write_csv(out / "demote_review_priority_2.csv", demote_priority["priority_2"], QUEUE_CSV_FIELDS)
    _write_csv(out / "demote_review_low_priority.csv", demote_priority["low_priority"], QUEUE_CSV_FIELDS)
    _write_csv(out / "thin_signal_watchlist_queue.csv", queues["thin_signal_watchlist_queue"], QUEUE_CSV_FIELDS)
    _write_csv(out / "thin_signal_watchlist_top100.csv", thin_signal_top100, QUEUE_CSV_FIELDS)
    _write_csv(out / "right_tail_evidence_score_diagnostics.csv", queues["right_tail_evidence_score_diagnostics"], QUEUE_CSV_FIELDS)
    pit_audit_rows = _build_pit_feature_lineage_audit(headers, safe_cols_manifest, RIGHT_TAIL_SCORING_COLUMNS)
    _write_csv(out / "pit_feature_lineage_audit.csv", pit_audit_rows, PIT_AUDIT_FIELDS)
    _write_csv(out / "target_miss_rescue_audit.csv", target_audit, TARGET_AUDIT_FIELDS)
    _write_csv(out / "v4_rescue_variant_summary.csv", v4_rows, ["variant", "routed_target_count", "visibility_routed_count", "actionable_research_routed_count", "scout_or_top15_routed_count", "demote_review_routed_count", "buy_underwriting_routed_count", "description"])
    (out / "README_ANALYSIS.md").write_text(_readme(), encoding="utf-8")
    right_tail_input_columns = sorted({key for row in queue_input for key in row})
    right_tail_scoring_columns = list(RIGHT_TAIL_SCORING_COLUMNS)
    forbidden_selection_input_columns = sorted({h for h in headers if _is_forbidden_selection_column(h)})
    forbidden_right_tail_input_columns = sorted({h for h in headers if is_forbidden_right_tail_routing_column(h)})
    if any(_is_forbidden_selection_column(c) for c in safe_cols_manifest):
        raise ValueError("forbidden forward-looking column reached Top15 selector inputs")
    if any(is_forbidden_right_tail_routing_column(c) for c in right_tail_input_columns):
        raise ValueError("forbidden forward-looking column reached right-tail routing inputs")
    pit_audit_status_counts = dict(sorted(Counter(r["pit_status"] for r in pit_audit_rows).items()))
    new_selected_hash = _file_sha256(out / "selected_names_by_quarter_top15.csv")
    selected_hash_guard_available = bool(prior_selected_hash)
    selected_hash_warning = "" if selected_hash_guard_available else "prior selected_names_by_quarter_top15.csv absent before run; unchanged guard unavailable"
    target_summary = {
        ticker: next((r["top15_status"] for r in comparison if r["ticker"] == ticker and r["quarter"] == quarter), "not_present")
        for ticker, quarter in TARGET_RIGHT_TAIL_EVENTS.items()
    }
    manifest = {
        "run_id": run_id or f"top15-exception-{uuid4()}",
        "runner_version": RUNNER_VERSION,
        "inputs": {
            "pit_panel": {"path": str(panel_path), "sha256": _file_sha256(panel_path), "row_count": len(rows)},
            "prior_selected": {"path": str(prior_path), "sha256": _file_sha256(prior_path), "row_count": len(baseline)},
        },
        "variant_configs": {k: cfg.__dict__ for k, cfg in TOP15_VARIANTS.items()},
        "forbidden_selection_columns_removed_excluded": forbidden_selection_input_columns,
        "feature_columns_used_for_selection": safe_cols_manifest,
        "columns_excluded_from_selection": sorted(set(headers) - set(safe_cols_manifest)),
        "no_leakage_statement": "Top15 selector receives only allowlisted selection-time fields plus safe hard-gate/confidence/coverage fields; labels/returns are attached after selection is frozen.",
        "right_tail_queue_outputs": {
            "top15_exception_candidate_queue": "top15_exception_candidate_queue.csv",
            "core_deterioration_review_queue": "core_deterioration_review_queue.csv",
            "right_tail_scout_queue": "right_tail_scout_queue.csv",
            "demote_review_queue": "demote_review_queue.csv",
            "demote_review_priority_1": "demote_review_priority_1.csv",
            "demote_review_priority_2": "demote_review_priority_2.csv",
            "demote_review_low_priority": "demote_review_low_priority.csv",
            "thin_signal_watchlist_queue": "thin_signal_watchlist_queue.csv",
            "thin_signal_watchlist_top100": "thin_signal_watchlist_top100.csv",
            "right_tail_evidence_score_diagnostics": "right_tail_evidence_score_diagnostics.csv",
            "pit_feature_lineage_audit": "pit_feature_lineage_audit.csv",
            "target_miss_rescue_audit": "target_miss_rescue_audit.csv",
            "v4_rescue_variant_summary": "v4_rescue_variant_summary.csv",
        },
        "core_deterioration_review_count": len(core_deterioration_rows),
        "core_deterioration_strict_override_count": sum(str(row.get("core_deterioration_strict_override_required")) == "1" for row in core_deterioration_rows),
        "core_deterioration_refill_shadow_outputs": {
            "selected": "core_deterioration_refill_shadow_selected.csv",
            "replacements": "core_deterioration_refill_shadow_replacements.csv",
            "summary": "core_deterioration_refill_shadow_summary.csv",
        },
        "core_deterioration_refill_shadow_variants": CORE_DETERIORATION_REFILL_SHADOW_VARIANTS,
        "core_deterioration_refill_shadow_no_leakage_statement": "Selection/refill uses PIT feature columns only; return labels are attached after selection is frozen for diagnostics.",
        "right_tail_queue_forbidden_columns": sorted(set(FORBIDDEN_RIGHT_TAIL_ROUTING_COLUMNS) | set(forbidden_right_tail_input_columns)),
        "right_tail_queue_input_columns": right_tail_input_columns,
        "right_tail_queue_scoring_columns": right_tail_scoring_columns,
        "right_tail_queue_no_leakage_statement": "Forbidden return/monitoring/final-rank/current-return/return_since/target/label/winner/loser fields are removed before scoring/routing; input columns include pass-through fields, scoring columns are the right-tail fields actually referenced by scoring/routing.",
        "pit_feature_lineage_audit_output": "pit_feature_lineage_audit.csv",
        "pit_feature_lineage_status_counts": pit_audit_status_counts,
        "prior_selected_names_by_quarter_top15_sha256": prior_selected_hash,
        "new_selected_names_by_quarter_top15_sha256": new_selected_hash,
        "top15_selected_rows_unchanged_from_prior_hash": (prior_selected_hash == new_selected_hash) if selected_hash_guard_available else None,
        "top15_selected_rows_hash_guard_warning": selected_hash_warning,
        "target_visibility_routed_count": visibility_count,
        "target_actionable_research_routed_count": actionable_count,
        "target_scout_or_top15_count": scout_or_top15_count,
        "target_demote_review_count": demote_review_count,
        "target_buy_underwriting_routed_count": buy_count,
        "manifest_hash_note": "run_manifest.json is excluded from output_hashes because hashing the manifest inside itself is unstable; all other files in this output directory are hashed after write.",
        "target_right_tail_events": TARGET_RIGHT_TAIL_EVENTS,
        "target_missed_name_capture_summary": target_summary,
        "demote_review_priority_1_count": len(demote_priority["priority_1"]),
        "demote_review_priority_2_count": len(demote_priority["priority_2"]),
        "demote_review_low_priority_count": len(demote_priority["low_priority"]),
        "thin_signal_watchlist_count": len(queues["thin_signal_watchlist_queue"]),
        "thin_signal_watchlist_top100_count": len(thin_signal_top100),
        "target_event_count": len(target_audit),
        "target_event_top15_status": target_summary,
        "quarter_count": len(groups),
        "eligible_row_count": sum(len(v) for v in groups.values()),
        "output_dir": str(out),
    }
    manifest["output_hashes"] = {name: _file_sha256(out / name) for name in OUTPUT_FILES}
    (out / "run_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def _readme() -> str:
    return """# Top-15 observed-data exception-sleeve backtest

Scope label: Top-15 observed-data exception-sleeve backtest.

This is a research/starter-underwriting queue, not 15 equal-weight buys. The first ten names represent the core high-conviction sleeve; exception rows are right-tail research / starter-underwriting candidates.

Do not claim full AKG+macro production v2 validation from these artifacts. Selection-time fields are PIT allowlisted and return labels are attached only after selection freezes.
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Top-15 exception-sleeve backtest")
    parser.add_argument("--pit-panel", required=True)
    parser.add_argument("--prior-selected", required=True)
    parser.add_argument("--out-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--run-id", default=None)
    args = parser.parse_args(argv)
    try:
        manifest = run_high_conviction_top15_exception_sleeve_backtest(args.pit_panel, args.prior_selected, args.out_dir, args.run_id)
    except (ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr); return 2
    print(json.dumps({"quarter_count": manifest["quarter_count"], "eligible_row_count": manifest["eligible_row_count"], "output_dir": args.out_dir}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
