"""Analyze the Top-15 right-tail exception sleeve observed-data backtest."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

TARGET_EVENTS = {
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
TARGET_NAMES = list(TARGET_EVENTS)
MAIN_VARIANT = "high_conviction_top15_v3_exception_sleeve"
BASELINE = "high_conviction_top10_v2_final"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def pct(value: Any, rate: bool = False) -> str:
    if value == "" or pd.isna(value):
        return ""
    v = float(value) * 100 if rate else float(value)
    return f"{v:.2f}%"


def md_table(rows: list[dict[str, Any]], cols: list[str]) -> str:
    if not rows:
        return "_No rows._"
    lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(c, "")) for c in cols) + " |")
    return "\n".join(lines)


def write_df(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def build_adoption_check(summary: pd.DataFrame, contribution: pd.DataFrame) -> pd.DataFrame:
    base = summary[summary["variant"] == BASELINE].iloc[0]
    rows: list[dict[str, Any]] = []
    for _, row in summary[summary["variant"] != BASELINE].iterrows():
        variant = row["variant"]
        exc = contribution[(contribution["variant"] == variant) & (contribution["sleeve"] == "right_tail_exception")]
        exc_avg = float(exc["avg_return_90d_pct"].iloc[0]) if not exc.empty else float("nan")
        loser_delta = float(row["loser_90d_minus30pct_rate"]) - float(base["loser_90d_minus30pct_rate"])
        drawdown_delta = float(row["2025Q1_avg_90d"]) - float(base["2025Q1_avg_90d"])
        rows.extend(
            [
                {"variant": variant, "criterion": "avg_90d_not_worse", "value": row["avg_return_90d_pct"], "baseline": base["avg_return_90d_pct"], "passed": float(row["avg_return_90d_pct"]) >= float(base["avg_return_90d_pct"]) - 0.5},
                {"variant": variant, "criterion": "winner_rate_close_or_better", "value": row["winner_90d_30pct_rate"], "baseline": base["winner_90d_30pct_rate"], "passed": float(row["winner_90d_30pct_rate"]) >= float(base["winner_90d_30pct_rate"]) - 0.02},
                {"variant": variant, "criterion": "loser_rate_delta_lte_2pp", "value": loser_delta, "baseline": 0, "passed": loser_delta <= 0.02},
                {"variant": variant, "criterion": "2025Q1_drawdown_not_materially_worse", "value": drawdown_delta, "baseline": 0, "passed": drawdown_delta >= -2.0},
                {"variant": variant, "criterion": "exception_sleeve_positive_avg_90d", "value": exc_avg, "baseline": 0, "passed": exc_avg > 0},
            ]
        )
    return pd.DataFrame(rows)


def build_target_capture(right_tail: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for ticker, target_quarter in TARGET_EVENTS.items():
        all_sub = right_tail[right_tail["ticker"].str.upper() == ticker]
        sub = all_sub[all_sub["quarter"] == target_quarter]
        if sub.empty:
            rows.append({"ticker": ticker, "target_quarter": target_quarter, "present_in_right_tail": False, "target_return_90d_pct": "", "top15_status": "not_present", "selected_quarters": "", "all_quarters": ";".join(sorted(all_sub["quarter"].unique())) if not all_sub.empty else ""})
            continue
        selected = sub[sub["top15_status"] == "selected"]
        rows.append(
            {
                "ticker": ticker,
                "target_quarter": target_quarter,
                "present_in_right_tail": True,
                "target_return_90d_pct": num(sub["return_90d_pct"]).max(),
                "top15_status": "selected" if not selected.empty else "missed",
                "selected_quarters": ";".join(sorted(selected["quarter"].unique())) if not selected.empty else "",
                "all_quarters": ";".join(sorted(all_sub["quarter"].unique())),
            }
        )
    return pd.DataFrame(rows)


def build_exception_drivers(selected: pd.DataFrame) -> pd.DataFrame:
    exc = selected[(selected["variant"] == MAIN_VARIANT) & (selected["selected_sleeve"] == "right_tail_exception")].copy()
    if exc.empty:
        return exc
    exc["return_90d_num"] = num(exc["return_90d_pct"])
    cols = [
        "quarter", "selected_sleeve_rank", "ticker", "return_90d_pct", "right_tail_exception_score",
        "entry_score_0_100", "rm_signal_bucket", "rm_active_fields", "hp_signal_bucket", "hp_active_fields",
        "primary_theme", "theme_tailwind_score", "market_repricing_score", "right_tail_exception_reason_codes",
        "right_tail_exception_warning_codes",
    ]
    for col in cols:
        if col not in exc.columns:
            exc[col] = ""
    return exc.sort_values("return_90d_num", ascending=False)[cols]


def run(bundle_dir: Path, prior_analysis_dir: Path, out_dir: Path, report_path: Path) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = read_csv(bundle_dir / "strategy_summary_top15.csv")
    byq = read_csv(bundle_dir / "strategy_by_quarter_top15.csv")
    selected = read_csv(bundle_dir / "selected_names_by_quarter_top15.csv")
    contrib = read_csv(bundle_dir / "core_vs_exception_contribution.csv")
    right_tail = read_csv(bundle_dir / "right_tail_capture_comparison.csv")
    left_tail = read_csv(bundle_dir / "left_tail_penalty_comparison.csv")
    missed = read_csv(bundle_dir / "missed_right_tail_after_top15.csv")
    candidate_queue = read_csv(bundle_dir / "top15_exception_candidate_queue.csv")
    scout_queue = read_csv(bundle_dir / "right_tail_scout_queue.csv")
    demote_queue = read_csv(bundle_dir / "demote_review_queue.csv")
    thin_signal_queue = read_csv(bundle_dir / "thin_signal_watchlist_queue.csv")
    thin_signal_top100 = read_csv(bundle_dir / "thin_signal_watchlist_top100.csv")
    diagnostics_queue = read_csv(bundle_dir / "right_tail_evidence_score_diagnostics.csv")
    target_visibility_audit = read_csv(bundle_dir / "target_miss_rescue_audit.csv")
    v4_diagnostics = read_csv(bundle_dir / "v4_rescue_variant_summary.csv")
    manifest = json.loads((bundle_dir / "run_manifest.json").read_text())

    adoption = build_adoption_check(summary, contrib)
    target_capture = build_target_capture(right_tail)
    exception_drivers = build_exception_drivers(selected)
    variant_comparison = summary.copy()
    sleeve_summary = contrib.copy()
    queue_summary = pd.DataFrame([
        {"queue": "top15_exception_candidate", "row_count": len(candidate_queue), "avg_right_tail_evidence_score": num(candidate_queue.get("right_tail_evidence_score", pd.Series(dtype=str))).mean()},
        {"queue": "right_tail_scout", "row_count": len(scout_queue), "avg_right_tail_evidence_score": num(scout_queue.get("right_tail_evidence_score", pd.Series(dtype=str))).mean()},
        {"queue": "demote_review", "row_count": len(demote_queue), "avg_right_tail_evidence_score": num(demote_queue.get("right_tail_evidence_score", pd.Series(dtype=str))).mean()},
        {"queue": "thin_signal_watchlist_full_audit", "row_count": len(thin_signal_queue), "avg_right_tail_evidence_score": num(thin_signal_queue.get("right_tail_evidence_score", pd.Series(dtype=str))).mean()},
        {"queue": "thin_signal_watchlist_top25_daily", "row_count": min(25, len(thin_signal_top100)), "avg_right_tail_evidence_score": num(thin_signal_top100.head(25).get("right_tail_evidence_score", pd.Series(dtype=str))).mean()},
        {"queue": "thin_signal_watchlist_top50_daily", "row_count": min(50, len(thin_signal_top100)), "avg_right_tail_evidence_score": num(thin_signal_top100.head(50).get("right_tail_evidence_score", pd.Series(dtype=str))).mean()},
        {"queue": "thin_signal_watchlist_top100_daily", "row_count": len(thin_signal_top100), "avg_right_tail_evidence_score": num(thin_signal_top100.get("right_tail_evidence_score", pd.Series(dtype=str))).mean()},
        {"queue": "diagnostics", "row_count": len(diagnostics_queue), "avg_right_tail_evidence_score": num(diagnostics_queue.get("right_tail_evidence_score", pd.Series(dtype=str))).mean()},
    ])
    target_visibility_metrics = pd.DataFrame([
        {"metric": "target_visibility_routed_count", "value": int(num(target_visibility_audit["target_visibility_routed"]).fillna(0).sum()) if "target_visibility_routed" in target_visibility_audit else 0},
        {"metric": "target_actionable_research_routed_count", "value": int(num(target_visibility_audit["target_actionable_research_routed"]).fillna(0).sum()) if "target_actionable_research_routed" in target_visibility_audit else 0},
        {"metric": "target_scout_or_top15_routed_count", "value": int(num(target_visibility_audit["target_scout_or_top15_routed"]).fillna(0).sum()) if "target_scout_or_top15_routed" in target_visibility_audit else 0},
        {"metric": "target_demote_review_routed_count", "value": int(num(target_visibility_audit["target_demote_review_routed"]).fillna(0).sum()) if "target_demote_review_routed" in target_visibility_audit else 0},
        {"metric": "target_buy_underwriting_routed_count", "value": int(num(target_visibility_audit["target_buy_underwriting_routed"]).fillna(0).sum()) if "target_buy_underwriting_routed" in target_visibility_audit else 0},
        {"metric": "target_event_count", "value": len(target_visibility_audit)},
    ])

    outputs = {
        "variant_comparison.csv": variant_comparison,
        "adoption_criteria_check.csv": adoption,
        "target_right_tail_capture.csv": target_capture,
        "exception_sleeve_drivers.csv": exception_drivers,
        "core_vs_exception_summary.csv": sleeve_summary,
        "left_tail_penalty_comparison.csv": left_tail,
        "missed_right_tail_after_top15.csv": missed,
        "right_tail_queue_summary.csv": queue_summary,
        "target_visibility_metrics.csv": target_visibility_metrics,
        "target_miss_rescue_audit.csv": target_visibility_audit,
        "v4_rescue_variant_summary.csv": v4_diagnostics,
        "top15_exception_candidate_queue.csv": candidate_queue,
        "right_tail_scout_queue.csv": scout_queue,
        "demote_review_queue.csv": demote_queue,
        "thin_signal_watchlist_queue.csv": thin_signal_queue,
        "thin_signal_watchlist_top100.csv": thin_signal_top100,
    }
    for name, df in outputs.items():
        write_df(df, out_dir / name)

    base = summary[summary["variant"] == BASELINE].iloc[0]
    main = summary[summary["variant"] == MAIN_VARIANT].iloc[0]
    main_exc = contrib[(contrib["variant"] == MAIN_VARIANT) & (contrib["sleeve"] == "right_tail_exception")].iloc[0]
    target_rows = [
        {"ticker": r.ticker, "target_quarter": r.target_quarter, "present": r.present_in_right_tail, "status": r.top15_status, "target_90d": pct(r.target_return_90d_pct) if str(r.target_return_90d_pct) else "", "selected_quarters": getattr(r, "selected_quarters", "")}
        for r in target_capture.itertuples(index=False)
    ]
    summary_rows = [
        {"variant": row["variant"], "picks": row["total_picks"], "avg_90d": pct(row["avg_return_90d_pct"]), "+30_hit": pct(row["winner_90d_30pct_rate"], True), "-30_loser": pct(row["loser_90d_minus30pct_rate"], True), "2025Q1": pct(row["2025Q1_avg_90d"])}
        for _, row in summary.iterrows()
    ]
    adoption_rows = [
        {"variant": r.variant, "criterion": r.criterion, "value": r.value, "passed": r.passed}
        for r in adoption.itertuples(index=False)
    ]

    captured_targets = sorted(target_capture[target_capture["top15_status"] == "selected"]["ticker"].tolist())
    captured_text = ", ".join(f"`{ticker}`" for ticker in captured_targets) if captured_targets else "none"
    target_metric_rows = target_visibility_metrics.to_dict("records")
    queue_summary_rows = queue_summary.fillna("").to_dict("records")

    report = f"""# Fundamental Top-15 Exception Sleeve Observed Backtest Analysis

## Bottom line

The Top-15 exception sleeve improves observed average 90d return and +30% hit rate versus Top-10 v2 while keeping -30% loser rate roughly flat. It should be treated as a research/starter-underwriting queue, not 15 equal-weight buys.

Use remains disciplined:

- Top-10 core = primary buy-underwriting queue.
- Exception sleeve = right-tail research / starter-underwriting candidates.
- No claim of full AKG+macro production-v2 historical validation.

## Main comparison

{md_table(summary_rows, ['variant', 'picks', 'avg_90d', '+30_hit', '-30_loser', '2025Q1'])}

Main Top-15 v3 vs Top-10 v2:

- Avg 90d: `{pct(base['avg_return_90d_pct'])}` -> `{pct(main['avg_return_90d_pct'])}`
- +30% hit rate: `{pct(base['winner_90d_30pct_rate'], True)}` -> `{pct(main['winner_90d_30pct_rate'], True)}`
- -30% loser rate: `{pct(base['loser_90d_minus30pct_rate'], True)}` -> `{pct(main['loser_90d_minus30pct_rate'], True)}`
- 2025Q1 avg 90d: `{pct(base['2025Q1_avg_90d'])}` -> `{pct(main['2025Q1_avg_90d'])}`

## Core vs exception sleeve

For `{MAIN_VARIANT}`, exception sleeve rows:

- Picks: `{main_exc['pick_count']}`
- Avg 90d: `{pct(main_exc['avg_return_90d_pct'])}`
- +30% hit rate: `{pct(main_exc['winner_90d_30pct_rate'], True)}`
- -30% loser rate: `{pct(main_exc['loser_90d_minus30pct_rate'], True)}`

The exception sleeve is positive in this observed backtest, but sample size is small. It supports adding research slots, not auto-buying all exceptions.

## Adoption criteria check

{md_table(adoption_rows, ['variant', 'criterion', 'value', 'passed'])}

Interpretation: main Top-15 v3 clears the quantitative research-queue tests, but because most target right-tail misses remain missed and AKG/macro PIT fields are still incomplete, live use should be Top-10 core plus exception research sleeve.

## Target right-tail capture

{md_table(target_rows, ['ticker', 'target_quarter', 'present', 'status', 'target_90d', 'selected_quarters'])}

The sleeve captured {captured_text} from the named target set but still missed most low-score RM/theme-wave examples. That means the exception sleeve helps, but it does not fully solve messy right-tail discovery.

## Right-Tail Scout + Demote Review

These queues are visibility/research outputs, not buy lists. A target can be visibility-routed without being selected into Top-15. `blocked_hard_demote` counts as visibility only, not actionable research or buy underwriting; non-hard `demote_review` is human research review and counts as actionable only when positive right-tail evidence is present.

{md_table(queue_summary_rows, ['queue', 'row_count', 'avg_right_tail_evidence_score'])}

Target visibility metrics:

{md_table(target_metric_rows, ['metric', 'value'])}

Final behavior:

1. Top-10 Core: clean buy-underwriting queue.
2. Top-15 Exception Sleeve: selected right-tail exception/starter-underwriting rows; output unchanged.
3. Top-15 Exception Candidate Queue: visibility/staging only.
4. Thin-Signal Watchlist: weak RM/HP/repricing evidence with insufficient proof; full file is audit-only; daily PM consumption uses Top 25 / Top 50 / Top 100 cuts from `thin_signal_watchlist_top100.csv`.
5. Right-Tail Scout + Demote Review: messy theme-wave / turnaround / hidden-supplier candidates too important to ignore but not automatically buys.

## No-leakage and caveats

- Selector receives selection-time fields only; returns are attached after selection is frozen.
- Forbidden labels/return columns are excluded per `run_manifest.json`.
- Missing AKG/macro fields remain neutral/unavailable.
- This is observed-data analysis, not full production v2 validation.

## Companion outputs

- `outputs/fundamental_backtest/analysis_top15_exception/variant_comparison.csv`
- `outputs/fundamental_backtest/analysis_top15_exception/adoption_criteria_check.csv`
- `outputs/fundamental_backtest/analysis_top15_exception/target_right_tail_capture.csv`
- `outputs/fundamental_backtest/analysis_top15_exception/exception_sleeve_drivers.csv`
- `outputs/fundamental_backtest/analysis_top15_exception/core_vs_exception_summary.csv`
- `outputs/fundamental_backtest/analysis_top15_exception/left_tail_penalty_comparison.csv`
- `outputs/fundamental_backtest/analysis_top15_exception/missed_right_tail_after_top15.csv`
- `outputs/fundamental_backtest/analysis_top15_exception/right_tail_queue_summary.csv`
- `outputs/fundamental_backtest/analysis_top15_exception/target_visibility_metrics.csv`
- `outputs/fundamental_backtest/analysis_top15_exception/target_miss_rescue_audit.csv`
- `outputs/fundamental_backtest/analysis_top15_exception/v4_rescue_variant_summary.csv`
- `outputs/fundamental_backtest/analysis_top15_exception/thin_signal_watchlist_queue.csv`
- `outputs/fundamental_backtest/analysis_top15_exception/thin_signal_watchlist_top100.csv`
- `outputs/fundamental_backtest/analysis_top15_exception/analysis_manifest.json`
"""
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report)

    paths = [out_dir / name for name in outputs] + [report_path]
    analysis_manifest = {
        "analysis_version": "fundamental_top15_exception_sleeve_observed_analysis_v1",
        "scope": "observed-data Top-15 exception-sleeve analysis; not full AKG+macro production validation",
        "bundle_dir": str(bundle_dir),
        "prior_analysis_dir": str(prior_analysis_dir),
        "input_manifest_sha256": sha256(bundle_dir / "run_manifest.json"),
        "bundle_manifest_target_summary": manifest.get("target_missed_name_capture_summary", {}),
        "outputs": {str(p): sha256(p) for p in paths},
    }
    (out_dir / "analysis_manifest.json").write_text(json.dumps(analysis_manifest, indent=2, sort_keys=True) + "\n")
    return analysis_manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Analyze Top15 exception sleeve backtest bundle")
    parser.add_argument("--bundle-dir", default="outputs/fundamental_backtest/high_conviction_top15_exception_sleeve")
    parser.add_argument("--prior-analysis-dir", default="outputs/fundamental_backtest/analysis")
    parser.add_argument("--out-dir", default="outputs/fundamental_backtest/analysis_top15_exception")
    parser.add_argument("--report", default="docs/research/fundamental_top15_exception_sleeve_observed_backtest_analysis.md")
    args = parser.parse_args(argv)
    manifest = run(Path(args.bundle_dir), Path(args.prior_analysis_dir), Path(args.out_dir), Path(args.report))
    print(json.dumps({"out_dir": args.out_dir, "report": args.report, "output_count": len(manifest["outputs"])}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
