"""Top-15 exception-sleeve PIT backtest exporter."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import defaultdict
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
    _validate_unique_ticker_quarter,
    _write_csv,
)
from tradingagents.research.fundamental.src.selection.high_conviction_top10 import (
    RightTailExceptionConfig,
    select_high_conviction_top15_exception_sleeve,
)

RUNNER_VERSION = "fundamental_high_conviction_top15_exception_sleeve_backtest_v1"
DEFAULT_OUTPUT_DIR = Path("outputs/fundamental_backtest/high_conviction_top15_exception_sleeve")
TARGET_RIGHT_TAIL_NAMES = ["CRNC", "CVNA", "SNDK", "AAOI", "BE", "AXTI", "AEHR", "ICHR", "CRDO"]
TOP15_VARIANTS: dict[str, RightTailExceptionConfig] = {
    "high_conviction_top15_v3_exception_sleeve": RightTailExceptionConfig(enabled=True, core_n=10, exception_slots=5),
    "top15_conservative_10_core_3_exception": RightTailExceptionConfig(enabled=True, core_n=10, exception_slots=3),
    "top15_rm1_priority_max2_rm2plus": RightTailExceptionConfig(enabled=True, core_n=10, exception_slots=5, max_rm2plus_slots=2),
}
BASELINE_VARIANT = "high_conviction_top10_v2_final"
OUTPUT_FILES = [
    "selected_names_by_quarter_top15.csv",
    "strategy_summary_top15.csv",
    "strategy_by_quarter_top15.csv",
    "core_vs_exception_contribution.csv",
    "exception_slot_diagnostics.csv",
    "right_tail_capture_comparison.csv",
    "left_tail_penalty_comparison.csv",
    "missed_right_tail_after_top15.csv",
    "README_ANALYSIS.md",
]
SAFE_SELECTOR_REQUIRED_COLUMNS = {
    "confidence",
    "cik",
    "cik_status",
    "document_status",
    "hard_reject_reason",
}


def _read_any_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        return list(reader), list(reader.fieldnames or [])


def _freeze(row: Mapping[str, Any], original: Mapping[str, Any], variant: str, quarter: str, rank: int) -> dict[str, Any]:
    out = dict(row)
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
    out = [dict(r, selected_sleeve="core", selected_sleeve_rank=r.get("selection_rank", "")) for r in rows if r.get("variant") == BASELINE_VARIANT]
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


def run_high_conviction_top15_exception_sleeve_backtest(pit_panel: str | Path, prior_selected: str | Path, out_dir: str | Path = DEFAULT_OUTPUT_DIR, run_id: str | None = None) -> dict[str, Any]:
    panel_path, prior_path, out = Path(pit_panel), Path(prior_selected), Path(out_dir)
    rows, headers = _read_csv(panel_path); _validate_unique_ticker_quarter(rows)
    baseline = _baseline_rows(prior_path)
    groups = _eligible_groups(rows); feature_cols = _feature_columns(headers)
    out.mkdir(parents=True, exist_ok=True)
    selected_rows: list[dict[str, Any]] = list(baseline)
    quarter_rows: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    status = _status_map(baseline)
    baseline_by_quarter: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in baseline:
        baseline_by_quarter[str(row.get("quarter"))].append(row)
    for qrows in baseline_by_quarter.values():
        qrows.sort(key=lambda r: int(_to_float(r.get("selection_rank")) or 999999))

    for q in sorted(groups):
        eligible = sorted(groups[q], key=lambda r: str(r.get("ticker", "")).upper())
        quarter_rows.append(_summarize_quarter(BASELINE_VARIANT, q, [r for r in baseline if r.get("quarter") == q], len(eligible), 10))
        safe_cols = list(dict.fromkeys([*feature_cols, *[c for c in headers if c in SAFE_SELECTOR_REQUIRED_COLUMNS and c not in FORBIDDEN_SELECTION_COLUMNS]]))
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

    _write_csv(out / "selected_names_by_quarter_top15.csv", selected_rows, ["variant", "quarter", "selection_rank", "selected_sleeve", "selected_sleeve_rank", "ticker", "right_tail_exception_score", *LABEL_COLUMNS])
    _write_csv(out / "strategy_summary_top15.csv", summary, ["variant", "quarter_count", "total_picks", "avg_picks_per_quarter"])
    _write_csv(out / "strategy_by_quarter_top15.csv", quarter_rows, ["variant", "quarter", "pick_count", "eligible_count", "shortfall"])
    _write_csv(out / "core_vs_exception_contribution.csv", _core_exception_rows(selected_rows), ["variant", "sleeve", "pick_count", "avg_return_90d_pct", "winner_90d_30pct_rate", "loser_90d_minus30pct_rate", "contribution_to_strategy_avg", "top_winners", "top_losers"])
    _write_csv(out / "exception_slot_diagnostics.csv", diagnostics, ["variant", "quarter", "selected_exception_count", "available_exception_candidate_count", "warning_codes", "selected_exception_tickers", "single_rm_exception_count", "rm2plus_exception_count", "no_theme_no_llm_exception_count"])
    _write_csv(out / "right_tail_capture_comparison.csv", comparison, ["ticker", "quarter", "return_90d_pct", "old_v2_status", "top15_status", "selected_sleeve", "selected_sleeve_rank", "right_tail_exception_score", "mechanical_exclusion_before", "mechanical_status_after"])
    _write_csv(out / "left_tail_penalty_comparison.csv", left_tail, ["variant", "loser_90d_minus30pct_rate", "avg_return_90d_pct", "2025Q1_avg_90d", "2025Q1_loser_rate", "delta_loser_rate_vs_top10"])
    _write_csv(out / "missed_right_tail_after_top15.csv", missed, ["ticker", "quarter", "return_90d_pct", "mechanical_status_after"])
    (out / "README_ANALYSIS.md").write_text(_readme(), encoding="utf-8")
    safe_cols_manifest = list(dict.fromkeys([*feature_cols, *[c for c in headers if c in SAFE_SELECTOR_REQUIRED_COLUMNS and c not in FORBIDDEN_SELECTION_COLUMNS]]))
    manifest = {"run_id": run_id or f"top15-exception-{uuid4()}", "runner_version": RUNNER_VERSION, "inputs": {"pit_panel": {"path": str(panel_path), "sha256": _file_sha256(panel_path), "row_count": len(rows)}, "prior_selected": {"path": str(prior_path), "sha256": _file_sha256(prior_path), "row_count": len(baseline)}}, "variant_configs": {k: cfg.__dict__ for k, cfg in TOP15_VARIANTS.items()}, "forbidden_selection_columns_removed_excluded": sorted(set(headers) & FORBIDDEN_SELECTION_COLUMNS), "feature_columns_used_for_selection": safe_cols_manifest, "columns_excluded_from_selection": sorted(set(headers) - set(safe_cols_manifest)), "no_leakage_statement": "Top15 selector receives only allowlisted selection-time fields plus safe hard-gate/confidence/coverage fields; labels/returns are attached after selection is frozen.", "manifest_hash_note": "run_manifest.json is excluded from output_hashes because hashing the manifest inside itself is unstable; all other files in this output directory are hashed after write.", "target_missed_name_capture_summary": {t: next((r["top15_status"] for r in comparison if r["ticker"] == t), "not_present") for t in TARGET_RIGHT_TAIL_NAMES}, "quarter_count": len(groups), "eligible_row_count": sum(len(v) for v in groups.values())}
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
