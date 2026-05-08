"""Generate observed-data analysis for the fundamental High-Conviction Top-10 bundle.

This script reads the committed handoff artifacts under outputs/fundamental_backtest
and writes analyst-facing companion tables plus a narrative report. It does not
regenerate the core PIT panel or Top-10 backtest bundle.
"""

from __future__ import annotations

import hashlib
import itertools
import json
from pathlib import Path
from typing import Any

import pandas as pd

from tradingagents.research.fundamental.backtests.high_conviction_top10 import (
    VARIANTS,
    _bucket_count,
    _entry_score,
    _macro_blocks_v2,
    _to_float,
    _truthy,
    _v1_score,
    _v2_score,
)

BASE = Path("outputs/fundamental_backtest")
TOP10 = BASE / "high_conviction_top10"
ANALYSIS = BASE / "analysis"
REPORT = Path("docs/research/fundamental_top10_observed_backtest_analysis.md")

PIT = BASE / "pit_fundamental_panel.csv"
SELECTED = TOP10 / "selected_names_by_quarter.csv"
STRATEGY_SUMMARY = TOP10 / "strategy_summary.csv"
STRATEGY_BY_QUARTER = TOP10 / "strategy_by_quarter.csv"
CONTRIB = TOP10 / "rm_hp_tier_contribution.csv"
THEME = TOP10 / "theme_bucket_summary.csv"
HANDOFF_MANIFEST = BASE / "HANDOFF_MANIFEST.json"
RUN_MANIFEST = TOP10 / "run_manifest.json"
FEATURE_SCHEMA = BASE / "feature_schema.json"
LABEL_SCHEMA = BASE / "label_schema.json"

MISSING_AKG_MACRO_FIELDS = [
    "theme_acceleration_score",
    "theme_acceleration_research_visibility",
    "theme_acceleration_rescan_flag",
    "akg_universe_tier",
    "macro_mode",
    "macro_spy",
    "macro_entry_action",
    "macro_position_size_multiplier",
]

OUTCOME_LABELS = [
    "return_10d_pct",
    "return_20d_pct",
    "return_30d_pct",
    "return_60d_pct",
    "return_90d_pct",
    "winner_90d_30pct",
    "loser_90d_minus30pct",
]

HP_FLAGS = [
    "hp0_high_price_broad",
    "hp1_quality_pullback",
    "hp2_dislocation_momentum_priority",
    "hp2_dislocation_momentum_watch",
    "hp3_large_quality_theme_exception",
    "hp4_score_reacceleration_watch",
    "hp_production_extension",
    "hp_research_extension",
    "hp_LLM_best",
]

RM_FLAGS = [
    "rm1_low_price_dislocation_momentum",
    "rm2_weak_acceleration",
    "rm3_mid_price_dislocation_momentum",
    "rm4_persistent_repricing_wave",
    "rm_buy_review_flag",
]

BLANKS = {"", "none", "null", "nan", "na", "n/a"}


def read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def nonblank(value: Any) -> bool:
    return str(value).strip().lower() not in BLANKS


def available_count(df: pd.DataFrame, field: str) -> int:
    if field not in df.columns:
        return 0
    return int(df[field].map(nonblank).sum())


def to_numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def pct_decimal(value: Any) -> str:
    if value == "" or pd.isna(value):
        return ""
    return f"{float(value) * 100:.2f}%"


def pct_points(value: Any) -> str:
    if value == "" or pd.isna(value):
        return ""
    return f"{float(value):.2f}%"


def md_table(rows: list[dict[str, Any]], columns: list[str]) -> str:
    if not rows:
        return "_No rows._"
    out = ["| " + " | ".join(columns) + " |", "| " + " | ".join(["---"] * len(columns)) + " |"]
    for row in rows:
        out.append("| " + " | ".join(str(row.get(col, "")) for col in columns) + " |")
    return "\n".join(out)


def write_df(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def signal_bucket(row: pd.Series, prefix: str) -> str:
    return _bucket_count(row.to_dict(), prefix)


def active_flags(row: pd.Series, fields: list[str]) -> str:
    flags = [field for field in fields if field in row.index and _truthy(row.get(field, ""))]
    return ";".join(flags)


def candidate_info(variant: str, row: dict[str, Any]) -> tuple[bool, float, str]:
    entry = _entry_score(row)
    hp_override = _truthy(row.get("hp_production_extension")) and _truthy(row.get("hp_LLM_best")) and entry >= 60

    if variant == "entry_score_top10":
        eligible = entry >= 70
        reason = "entry_score_ge_70" if eligible else "entry_score_below_70"
        return eligible, entry, reason

    if variant == "high_conviction_top10_v1":
        eligible = entry >= 70 or hp_override
        reason = "entry_or_hp_override" if eligible else "no_entry_or_hp_override"
        return eligible, _v1_score(row), reason

    if variant == "high_conviction_top10_v2_final":
        if _macro_blocks_v2(row):
            return False, _v2_score(row), "macro_blocked"
        rm_override = _truthy(row.get("repricing_momentum_priority")) and ((_to_float(row.get("market_repricing_score")) or 0.0) >= 14 or _truthy(row.get("rm_buy_review_flag")))
        theme_or_t5 = _truthy(row.get("theme_acceleration_research_visibility")) or str(row.get("akg_universe_tier", "")).strip() == "T5_RESCAN"
        eligible = entry >= 70 or hp_override or rm_override or theme_or_t5
        reason = "entry_hp_rm_theme_or_t5" if eligible else "no_entry_hp_rm_theme_t5_override"
        return eligible, _v2_score(row), reason

    raise ValueError(f"unknown variant {variant}")


def candidate_ranks(variant: str, rows: pd.DataFrame) -> dict[str, tuple[int, float, str]]:
    candidates: list[tuple[str, float, float, str]] = []
    for _, row in rows.iterrows():
        row_dict = row.to_dict()
        is_candidate, score, reason = candidate_info(variant, row_dict)
        if is_candidate:
            candidates.append((str(row_dict.get("ticker", "")).upper(), score, _entry_score(row_dict), reason))
    if variant == "entry_score_top10":
        candidates.sort(key=lambda x: (-x[1], x[0]))
    else:
        candidates.sort(key=lambda x: (-x[1], -x[2], x[0]))
    return {ticker: (rank, score, reason) for rank, (ticker, score, _entry, reason) in enumerate(candidates, start=1)}


def make_field_availability(pit: pd.DataFrame, run_manifest: dict[str, Any], feature_schema: dict[str, Any], label_schema: dict[str, Any]) -> pd.DataFrame:
    row_count = len(pit)
    feature_cols = set(run_manifest.get("feature_columns_used_for_selection", []))
    forbidden_cols = set(run_manifest.get("selection_forbidden_columns", [])) | set(feature_schema.get("forbidden_selection_columns", []))
    label_cols = set(label_schema.get("columns", []))
    fields = list(dict.fromkeys(list(pit.columns) + sorted(forbidden_cols - set(pit.columns))))

    rows: list[dict[str, Any]] = []
    for field in fields:
        available = available_count(pit, field)
        missing = row_count - available
        if field in feature_cols and available == 0:
            used_in_selection = "allowlisted_but_unavailable"
        elif field in feature_cols:
            used_in_selection = "yes"
        elif field == "eligible_for_backtest":
            used_in_selection = "filter_only"
        elif field in forbidden_cols:
            used_in_selection = "no_forbidden"
        else:
            used_in_selection = "no"

        if field == "eligible_for_backtest":
            used_as_label = "filter_label"
        elif field in label_cols:
            used_as_label = "yes"
        else:
            used_as_label = "no"

        if field in MISSING_AKG_MACRO_FIELDS:
            interpretation = "Source-missing PIT field; retained blank/unavailable, not valid positive or negative evidence in this bundle."
        elif field in OUTCOME_LABELS:
            interpretation = "Outcome label; diagnostic only and attached after selection."
        elif field in forbidden_cols:
            interpretation = "Explicitly excluded/forbidden from selection."
        elif field == "eligible_for_backtest":
            interpretation = "Filtering label only; not a ranking feature."
        elif field in feature_cols:
            interpretation = "Selection-time feature from PIT panel."
        else:
            interpretation = "Metadata or diagnostic field."

        rows.append(
            {
                "field": field,
                "available_count": available,
                "missing_count": missing,
                "used_in_selection": used_in_selection,
                "used_as_label": used_as_label,
                "interpretation": interpretation,
            }
        )
    return pd.DataFrame(rows)


def make_variant_matrix(summary: pd.DataFrame) -> pd.DataFrame:
    by_variant = {row["variant"]: row for _, row in summary.iterrows()}
    descriptions = {
        "entry_score_top10": {
            "what_it_tests": "Raw entry-score Top-10 among eligible rows with entry_score_0_100 >= 70.",
            "what_it_does_not_test": "HP override, RM override, AKG theme acceleration override, T5_RESCAN override, and macro blocking.",
            "key_incremental_mechanism": "Baseline ranking by entry_score_0_100.",
            "main_caveat": "Baseline comparator only; not a high-conviction overlay.",
        },
        "high_conviction_top10_v1": {
            "what_it_tests": "Entry-score baseline plus HP production+LLM override and HP/risk-penalty high-conviction score adjustments.",
            "what_it_does_not_test": "RM override, AKG theme acceleration/T5_RESCAN override, and macro blocking.",
            "key_incremental_mechanism": "HP production extension + HP_LLM_best boost; risk penalty adjustment.",
            "main_caveat": "Captures HP right tail but raises left-tail exposure in this observed panel.",
        },
        "high_conviction_top10_v2_final": {
            "what_it_tests": "Observed v2 columns: v1 plus RM/repricing priority and market repricing boosts, post-LLM demote penalty, and macro-block logic if populated.",
            "what_it_does_not_test": "Full live AKG+macro production v2, because theme acceleration, AKG tier, and macro fields are blank/missing in this PIT panel.",
            "key_incremental_mechanism": "RM/repricing override and scoring boost over v1 using available observed columns.",
            "main_caveat": "Valid observed-data v2 result, not full production v2 validation.",
        },
    }
    rows = []
    for variant in VARIANTS:
        s = by_variant[variant]
        rows.append(
            {
                "variant": variant,
                **descriptions[variant],
                "avg_90d_return": f"{float(s['avg_return_90d_pct']):.6f}",
                "winner_30_rate": f"{float(s['winner_90d_30pct_rate']):.6f}",
                "loser_minus30_rate": f"{float(s['loser_90d_minus30pct_rate']):.6f}",
            }
        )
    return pd.DataFrame(rows)


def make_rm_drivers(selected: pd.DataFrame) -> pd.DataFrame:
    df = selected[selected["variant"] == "high_conviction_top10_v2_final"].copy()
    df["rm_signal_bucket"] = df.apply(lambda r: signal_bucket(r, "rm"), axis=1)
    df["hp_signal_bucket"] = df.apply(lambda r: signal_bucket(r, "hp"), axis=1)
    df["rm_flags_active"] = df.apply(lambda r: active_flags(r, RM_FLAGS), axis=1)
    df["return_90d_pct_num"] = to_numeric(df["return_90d_pct"])
    focus = df[df["rm_signal_bucket"].isin(["1", "2+"])].copy()
    bucket_stats = (
        df.groupby("rm_signal_bucket")
        .agg(
            bucket_pick_count=("ticker", "count"),
            bucket_avg_return_90d_pct=("return_90d_pct_num", "mean"),
            bucket_winner_30_rate=("winner_90d_30pct", lambda s: sum(_truthy(v) for v in s) / len(s)),
            bucket_loser_minus30_rate=("loser_90d_minus30pct", lambda s: sum(_truthy(v) for v in s) / len(s)),
        )
        .reset_index()
    )
    focus = focus.merge(bucket_stats, on="rm_signal_bucket", how="left")
    cols = [
        "variant",
        "quarter",
        "selection_rank",
        "ticker",
        "rm_signal_bucket",
        "rm_flags_active",
        "hp_signal_bucket",
        "entry_score_0_100",
        "hc_score",
        "market_repricing_score",
        "repricing_momentum_priority",
        "risk_penalty_score",
        "return_90d_pct",
        "winner_90d_30pct",
        "loser_90d_minus30pct",
        "bucket_pick_count",
        "bucket_avg_return_90d_pct",
        "bucket_winner_30_rate",
        "bucket_loser_minus30_rate",
        "primary_theme",
    ]
    focus = focus.sort_values(["rm_signal_bucket", "return_90d_pct_num"], ascending=[True, False])
    return focus[cols]


def make_hp_tail(selected: pd.DataFrame) -> pd.DataFrame:
    df = selected.copy()
    df["hp_signal_bucket"] = df.apply(lambda r: signal_bucket(r, "hp"), axis=1)
    df["hp_flags_active"] = df.apply(lambda r: active_flags(r, HP_FLAGS), axis=1)
    df["return_90d_pct_num"] = to_numeric(df["return_90d_pct"])
    rows: list[dict[str, Any]] = []
    for (variant, bucket), group in df.groupby(["variant", "hp_signal_bucket"]):
        ordered = group.sort_values("return_90d_pct_num")
        rows.append(
            {
                "variant": variant,
                "hp_signal_bucket": bucket,
                "pick_count": len(group),
                "avg_return_90d_pct": group["return_90d_pct_num"].mean(),
                "winner_90d_30pct_rate": sum(_truthy(v) for v in group["winner_90d_30pct"]) / len(group),
                "loser_90d_minus30pct_rate": sum(_truthy(v) for v in group["loser_90d_minus30pct"]) / len(group),
                "worst_5_tickers": ";".join(f"{r.ticker}:{float(r.return_90d_pct_num):.1f}%" for r in ordered.head(5).itertuples()),
                "best_5_tickers": ";".join(f"{r.ticker}:{float(r.return_90d_pct_num):.1f}%" for r in ordered.tail(5).sort_values("return_90d_pct_num", ascending=False).itertuples()),
                "active_hp_flags_sample": ";".join(sorted(set(x for x in group["hp_flags_active"] if x)))[:500],
            }
        )
    return pd.DataFrame(rows).sort_values(["variant", "hp_signal_bucket"])


def make_variant_overlap(selected: pd.DataFrame) -> pd.DataFrame:
    df = selected.copy()
    df["return_90d_pct_num"] = to_numeric(df["return_90d_pct"])
    rows: list[dict[str, Any]] = []
    variants = list(VARIANTS)
    for quarter in sorted(df["quarter"].unique()):
        q = df[df["quarter"] == quarter]
        for a, b in [(variants[0], variants[1]), (variants[1], variants[2]), (variants[0], variants[2])]:
            qa = q[q["variant"] == a]
            qb = q[q["variant"] == b]
            set_a = set(qa["ticker"])
            set_b = set(qb["ticker"])
            common = sorted(set_a & set_b)
            a_only = sorted(set_a - set_b)
            b_only = sorted(set_b - set_a)
            avg_a = qa["return_90d_pct_num"].mean()
            avg_b = qb["return_90d_pct_num"].mean()
            rows.append(
                {
                    "quarter": quarter,
                    "variant_a": a,
                    "variant_b": b,
                    "overlap_count": len(common),
                    "a_only_count": len(a_only),
                    "b_only_count": len(b_only),
                    "avg_return_90d_a": avg_a,
                    "avg_return_90d_b": avg_b,
                    "avg_return_90d_delta_b_minus_a": avg_b - avg_a,
                    "common_tickers": ";".join(common),
                    "a_only_tickers": ";".join(a_only),
                    "b_only_tickers": ";".join(b_only),
                }
            )
    return pd.DataFrame(rows)


def make_ticker_contribution(selected: pd.DataFrame) -> pd.DataFrame:
    df = selected.copy()
    df["return_90d_pct_num"] = to_numeric(df["return_90d_pct"])
    rows: list[dict[str, Any]] = []
    for (variant, ticker), group in df.groupby(["variant", "ticker"]):
        ordered = group.sort_values("return_90d_pct_num")
        rows.append(
            {
                "variant": variant,
                "ticker": ticker,
                "pick_count": len(group),
                "quarters_selected": ";".join(sorted(group["quarter"].unique())),
                "avg_return_90d_pct": group["return_90d_pct_num"].mean(),
                "total_return_90d_pct_points": group["return_90d_pct_num"].sum(),
                "winner_30_count": sum(_truthy(v) for v in group["winner_90d_30pct"]),
                "loser_minus30_count": sum(_truthy(v) for v in group["loser_90d_minus30pct"]),
                "best_quarter": ordered.tail(1)["quarter"].iloc[0],
                "best_return_90d_pct": ordered["return_90d_pct_num"].max(),
                "worst_quarter": ordered.head(1)["quarter"].iloc[0],
                "worst_return_90d_pct": ordered["return_90d_pct_num"].min(),
                "primary_themes_seen": ";".join(sorted(t for t in group["primary_theme"].unique() if nonblank(t))),
            }
        )
    out = pd.DataFrame(rows)
    out["positive_contribution_rank"] = out.groupby("variant")["total_return_90d_pct_points"].rank(method="first", ascending=False).astype(int)
    out["negative_contribution_rank"] = out.groupby("variant")["total_return_90d_pct_points"].rank(method="first", ascending=True).astype(int)
    return out.sort_values(["variant", "positive_contribution_rank"])


def make_2025q1_attribution(selected: pd.DataFrame, strategy_by_quarter: pd.DataFrame) -> pd.DataFrame:
    df = selected[selected["quarter"] == "2025Q1"].copy()
    df["return_90d_pct_num"] = to_numeric(df["return_90d_pct"])
    df["rm_signal_bucket"] = df.apply(lambda r: signal_bucket(r, "rm"), axis=1)
    df["hp_signal_bucket"] = df.apply(lambda r: signal_bucket(r, "hp"), axis=1)
    df["rm_flags_active"] = df.apply(lambda r: active_flags(r, RM_FLAGS), axis=1)
    df["hp_flags_active"] = df.apply(lambda r: active_flags(r, HP_FLAGS), axis=1)
    qstats = strategy_by_quarter[strategy_by_quarter["quarter"] == "2025Q1"].set_index("variant")
    df["quarter_avg_return_90d_pct"] = df["variant"].map(qstats["avg_return_90d_pct"].astype(float))
    df["quarter_pick_count"] = df["variant"].map(qstats["pick_count"].astype(int))
    df["contribution_to_quarter_avg_pct_points"] = df["return_90d_pct_num"] / df["quarter_pick_count"]
    cols = [
        "variant",
        "quarter",
        "selection_rank",
        "ticker",
        "return_90d_pct",
        "contribution_to_quarter_avg_pct_points",
        "quarter_avg_return_90d_pct",
        "rm_signal_bucket",
        "rm_flags_active",
        "hp_signal_bucket",
        "hp_flags_active",
        "entry_score_0_100",
        "hc_score",
        "market_repricing_score",
        "repricing_momentum_priority",
        "risk_penalty_score",
        "winner_90d_30pct",
        "loser_90d_minus30pct",
        "primary_theme",
    ]
    return df[cols].sort_values(["variant", "selection_rank"])


def make_missed_right_tail(pit: pd.DataFrame, selected: pd.DataFrame) -> pd.DataFrame:
    eligible = pit[pit["eligible_for_backtest"].map(_truthy)].copy()
    eligible["return_90d_pct_num"] = to_numeric(eligible["return_90d_pct"])
    right_tail = eligible[eligible["return_90d_pct_num"] >= 100].copy()
    selected_sets = {
        (variant, quarter): set(group["ticker"].str.upper())
        for (variant, quarter), group in selected.groupby(["variant", "quarter"])
    }
    rows: list[dict[str, Any]] = []
    for variant in VARIANTS:
        for quarter, qrows in eligible.groupby("quarter"):
            ranks = candidate_ranks(variant, qrows)
            top_selected = selected_sets.get((variant, quarter), set())
            qtail = right_tail[right_tail["quarter"] == quarter]
            for _, row in qtail.iterrows():
                ticker = str(row["ticker"]).upper()
                if ticker in top_selected:
                    continue
                row_dict = row.to_dict()
                is_candidate, score, reason_detail = candidate_info(variant, row_dict)
                rank = ranks.get(ticker, (None, score, reason_detail))[0]
                if not is_candidate:
                    mechanical = "not_variant_eligible"
                elif rank and rank > 10:
                    mechanical = "eligible_but_ranked_below_top10"
                else:
                    mechanical = "not_selected_other_mechanical"
                ret = float(row["return_90d_pct_num"])
                if ret >= 900:
                    bucket = "10x_plus"
                elif ret >= 400:
                    bucket = "5x_to_10x"
                else:
                    bucket = "2x_to_5x"
                rows.append(
                    {
                        "variant": variant,
                        "quarter": quarter,
                        "ticker": ticker,
                        "return_90d_pct": ret,
                        "right_tail_bucket": bucket,
                        "mechanical_exclusion_category": mechanical,
                        "mechanical_detail": reason_detail,
                        "candidate_rank_if_eligible": rank if rank is not None else "",
                        "candidate_hc_score_if_eligible": f"{score:.6f}" if is_candidate else "",
                        "entry_score_0_100": row.get("entry_score_0_100", ""),
                        "rm_signal_bucket": signal_bucket(row, "rm"),
                        "hp_signal_bucket": signal_bucket(row, "hp"),
                        "rm_flags_active": active_flags(row, RM_FLAGS),
                        "hp_flags_active": active_flags(row, HP_FLAGS),
                        "primary_theme": row.get("primary_theme", ""),
                    }
                )
    return pd.DataFrame(rows).sort_values(["variant", "return_90d_pct"], ascending=[True, False])


def make_qa(pit: pd.DataFrame, selected: pd.DataFrame, strategy_by_quarter: pd.DataFrame, field_audit: pd.DataFrame, run_manifest: dict[str, Any], handoff: dict[str, Any]) -> dict[str, Any]:
    ret90 = to_numeric(pit["return_90d_pct"])
    with_ret90 = ret90.notna()
    winner_expected = ret90 >= 30
    loser_expected = ret90 <= -30
    winner_actual = pit["winner_90d_30pct"].map(_truthy)
    loser_actual = pit["loser_90d_minus30pct"].map(_truthy)

    hash_failures = []
    for item in handoff.get("output_files", []):
        path = Path(item["path"])
        if not path.exists():
            hash_failures.append({"path": str(path), "error": "missing"})
            continue
        actual = file_sha256(path)
        if actual != item.get("sha256"):
            hash_failures.append({"path": str(path), "expected": item.get("sha256"), "actual": actual})

    duplicate_ticker_quarter = int(pit.duplicated(["quarter", "ticker"]).sum())
    selected_header = SELECTED.read_text(encoding="utf-8").splitlines()[0].split(",")
    duplicate_selected_headers = sorted({h for h in selected_header if selected_header.count(h) > 1})
    feature_cols = set(run_manifest.get("feature_columns_used_for_selection", []))
    forbidden_cols = set(run_manifest.get("selection_forbidden_columns", []))

    q2026q1 = pit[pit["quarter"] == "2026Q1"]
    q2026q2 = pit[pit["quarter"] == "2026Q2"]
    picks_2026q1 = strategy_by_quarter[strategy_by_quarter["quarter"] == "2026Q1"]
    picks_2026q2 = strategy_by_quarter[strategy_by_quarter["quarter"] == "2026Q2"]

    monitoring_final_rank_fields = {
        "monitoring_score_0_100",
        "active_monitoring_score_0_100",
        "final_rank_score_0_100",
        "rank_score_0_100",
        "current_return_pct",
        "return_since_signal_pct",
        "return_since_purchase_pct",
    }

    qa = {
        "pit_row_count": len(pit),
        "ticker_count": int(pit["ticker"].nunique()),
        "quarter_count": int(pit["quarter"].nunique()),
        "observed_quarter_min": str(pit["quarter"].min()),
        "observed_quarter_max": str(pit["quarter"].max()),
        "eligible_row_count": int(pit["eligible_for_backtest"].map(_truthy).sum()),
        "non_empty_return_90d_pct_count": int(pit["return_90d_pct"].map(nonblank).sum()),
        "selected_row_count": len(selected),
        "variant_pick_counts": selected.groupby("variant").size().to_dict(),
        "duplicate_ticker_quarter_count": duplicate_ticker_quarter,
        "winner_90d_label_mismatch_count": int(((winner_expected != winner_actual) & with_ret90).sum()),
        "loser_90d_label_mismatch_count": int(((loser_expected != loser_actual) & with_ret90).sum()),
        "forbidden_selection_overlap": sorted(feature_cols & forbidden_cols),
        "outcome_labels_in_selection_features": sorted(feature_cols & set(OUTCOME_LABELS)),
        "monitoring_final_rank_fields_forbidden": sorted(monitoring_final_rank_fields),
        "monitoring_final_rank_fields_in_selection_features": sorted(feature_cols & monitoring_final_rank_fields),
        "duplicate_selected_headers": duplicate_selected_headers,
        "missing_akg_macro_available_counts": field_audit[field_audit["field"].isin(MISSING_AKG_MACRO_FIELDS)].set_index("field")["available_count"].to_dict(),
        "manifest_hash_failure_count": len(hash_failures),
        "manifest_hash_failures": hash_failures,
        "partial_periods": {
            "2026Q1": {
                "rows": len(q2026q1),
                "eligible_rows": int(q2026q1["eligible_for_backtest"].map(_truthy).sum()),
                "selected_pick_counts": picks_2026q1.set_index("variant")["pick_count"].astype(int).to_dict(),
                "shortfall_by_variant": picks_2026q1.set_index("variant")["shortfall"].astype(str).to_dict(),
            },
            "2026Q2": {
                "rows": len(q2026q2),
                "eligible_rows": int(q2026q2["eligible_for_backtest"].map(_truthy).sum()),
                "selected_pick_counts": picks_2026q2.set_index("variant")["pick_count"].astype(int).to_dict() if not picks_2026q2.empty else {},
            },
        },
    }
    qa["passed"] = (
        qa["pit_row_count"] == 22304
        and qa["ticker_count"] == 1279
        and qa["quarter_count"] == 19
        and qa["eligible_row_count"] == 21182
        and qa["selected_row_count"] == 519
        and duplicate_ticker_quarter == 0
        and qa["winner_90d_label_mismatch_count"] == 0
        and qa["loser_90d_label_mismatch_count"] == 0
        and not qa["forbidden_selection_overlap"]
        and not qa["outcome_labels_in_selection_features"]
        and not qa["monitoring_final_rank_fields_in_selection_features"]
        and not duplicate_selected_headers
        and all(v == 0 for v in qa["missing_akg_macro_available_counts"].values())
        and len(hash_failures) == 0
    )
    return qa


def write_report(
    pit: pd.DataFrame,
    selected: pd.DataFrame,
    summary: pd.DataFrame,
    by_quarter: pd.DataFrame,
    contrib: pd.DataFrame,
    theme: pd.DataFrame,
    qa: dict[str, Any],
    field_audit: pd.DataFrame,
    variant_matrix: pd.DataFrame,
    missed: pd.DataFrame,
) -> None:
    summary_rows = []
    for _, row in summary.iterrows():
        summary_rows.append(
            {
                "variant": row["variant"],
                "picks": row["total_picks"],
                "avg_90d": pct_points(row["avg_return_90d_pct"]),
                "+30_hit": pct_decimal(row["winner_90d_30pct_rate"]),
                "-30_loser": pct_decimal(row["loser_90d_minus30pct_rate"]),
            }
        )

    v2q = by_quarter[by_quarter["variant"] == "high_conviction_top10_v2_final"].copy()
    v2q["avg_return_90d_pct_num"] = to_numeric(v2q["avg_return_90d_pct"])
    strong = v2q.sort_values("avg_return_90d_pct_num", ascending=False).head(4)
    weak = v2q.sort_values("avg_return_90d_pct_num").head(3)
    strong_rows = [{"quarter": r.quarter, "avg_90d": pct_points(r.avg_return_90d_pct), "+30_hit": pct_decimal(r.winner_90d_30pct_rate)} for r in strong.itertuples()]
    weak_rows = [{"quarter": r.quarter, "avg_90d": pct_points(r.avg_return_90d_pct), "-30_loser": pct_decimal(r.loser_90d_minus30pct_rate)} for r in weak.itertuples()]

    rm_v2 = contrib[(contrib["variant"] == "high_conviction_top10_v2_final") & (contrib["dimension"] == "rm")].copy()
    rm_rows = [
        {
            "rm_signal_bucket": row["bucket"],
            "picks": row["pick_count"],
            "avg_90d": pct_points(row["avg_return_90d_pct"]),
            "+30_hit": pct_decimal(row["winner_90d_30pct_rate"]),
            "-30_loser": pct_decimal(row["loser_90d_minus30pct_rate"]),
        }
        for _, row in rm_v2.iterrows()
    ]
    hp_v2 = contrib[(contrib["variant"] == "high_conviction_top10_v2_final") & (contrib["dimension"] == "hp")].copy()
    hp_rows = [
        {
            "hp_bucket": row["bucket"],
            "picks": row["pick_count"],
            "avg_90d": pct_points(row["avg_return_90d_pct"]),
            "+30_hit": pct_decimal(row["winner_90d_30pct_rate"]),
            "-30_loser": pct_decimal(row["loser_90d_minus30pct_rate"]),
        }
        for _, row in hp_v2.iterrows()
    ]

    v2_theme = theme[theme["variant"] == "high_conviction_top10_v2_final"].copy()
    unknown = v2_theme[v2_theme["primary_theme"].str.upper().eq("UNKNOWN")]
    unknown_picks = int(unknown["pick_count"].astype(int).sum()) if not unknown.empty else 0
    top_named_theme = v2_theme[~v2_theme["primary_theme"].str.upper().eq("UNKNOWN")].copy()
    top_named_theme["avg_return_num"] = to_numeric(top_named_theme["avg_return_90d_pct"])
    top_named_rows = [
        {"theme": r.primary_theme, "picks": r.pick_count, "avg_90d": pct_points(r.avg_return_90d_pct)}
        for r in top_named_theme.sort_values("avg_return_num", ascending=False).head(5).itertuples()
    ]

    missed_v2 = missed[missed["variant"] == "high_conviction_top10_v2_final"]
    missed_counts = missed_v2.groupby(["right_tail_bucket", "mechanical_exclusion_category"]).size().reset_index(name="count")
    missed_rows = [r._asdict() for r in missed_counts.itertuples(index=False)]

    missing_field_rows = [
        {
            "field": row["field"],
            "available": row["available_count"],
            "used_in_selection": row["used_in_selection"],
            "interpretation": row["interpretation"],
        }
        for _, row in field_audit[field_audit["field"].isin(MISSING_AKG_MACRO_FIELDS)].iterrows()
    ]

    variant_rows = [
        {
            "variant": row["variant"],
            "tests": row["what_it_tests"],
            "does_not_test": row["what_it_does_not_test"],
        }
        for _, row in variant_matrix.iterrows()
    ]

    text = f"""# High-Conviction Top-10 Observed-Data Backtest

## Bottom line

The committed bundle is valid for a better observed-data Top-10 backtest analysis. It is not a full live AKG+macro production v2 validation because AKG theme acceleration and macro fields are blank/missing in the PIT panel.

Core counts reconciled from the committed artifacts:

- PIT panel rows: `{qa['pit_row_count']:,}`
- Eligible backtest rows: `{qa['eligible_row_count']:,}`
- Selected rows: `{qa['selected_row_count']:,}`
- Variants: `{len(qa['variant_pick_counts'])}`
- Picks per variant: `{qa['variant_pick_counts']}`
- Observed quarters: `{qa['observed_quarter_min']}` through `{qa['observed_quarter_max']}`

## QA / leakage verification

QA status: `{'PASS' if qa['passed'] else 'FAIL'}`.

- Outcome labels are diagnostic only: `forbidden_selection_overlap={qa['forbidden_selection_overlap']}` and `outcome_labels_in_selection_features={qa['outcome_labels_in_selection_features']}`.
- Monitoring/final-rank/current-return fields are excluded from selection: `monitoring_final_rank_fields_in_selection_features={qa['monitoring_final_rank_fields_in_selection_features']}`; forbidden set `{qa['monitoring_final_rank_fields_forbidden']}`.
- Winner/loser labels reconcile to `return_90d_pct`: winner mismatches `{qa['winner_90d_label_mismatch_count']}`, loser mismatches `{qa['loser_90d_label_mismatch_count']}`.
- Duplicate ticker-quarter rows: `{qa['duplicate_ticker_quarter_count']}`.
- Manifest hash failures: `{qa['manifest_hash_failure_count']}`.
- `selected_names_by_quarter.csv` duplicate headers: `{qa['duplicate_selected_headers']}`.
- `2026Q1` is partial/shortfall: `{qa['partial_periods']['2026Q1']}`.
- `2026Q2` is present in the source but not eligible for 90d backtest selection: `{qa['partial_periods']['2026Q2']}`.

Missing AKG/macro field availability:

{md_table(missing_field_rows, ['field', 'available', 'used_in_selection', 'interpretation'])}

## Variant interpretation matrix

{md_table(variant_rows, ['variant', 'tests', 'does_not_test'])}

## Main strategy result

{md_table(summary_rows, ['variant', 'picks', 'avg_90d', '+30_hit', '-30_loser'])}

Read-through: high-conviction v1/v2 improve the +30% hit rate versus raw entry-score Top-10, but with a higher -30% loser rate. v2 does not materially beat v1 in this bundle because the fields that make v2 uniquely AKG/macro-aware are unavailable.

## Quarter-by-quarter read

Strong v2 quarters:

{md_table(strong_rows, ['quarter', 'avg_90d', '+30_hit'])}

Weak v2 quarters:

{md_table(weak_rows, ['quarter', 'avg_90d', '-30_loser'])}

The 2025Q1 drawdown remains the clearest case for macro permission / risk-on filtering. This bundle cannot measure that protection because macro fields are blank.

## RM contribution

{md_table(rm_rows, ['rm_signal_bucket', 'picks', 'avg_90d', '+30_hit', '-30_loser'])}

Observed result: the strongest bucket is the single-RM-signal bucket, labeled `rm_signal_bucket=1`. This is not necessarily the literal `rm1_low_price_dislocation_momentum` rule; it means exactly one RM-related signal was active. The `rm_signal_bucket=2+` multi-RM-signal bucket is weaker and has higher left-tail risk than the single-signal bucket. Treat this as a routing/manual-underwriting signal, not proof that one causal mechanism explains returns.

## HP contribution

{md_table(hp_rows, ['hp_bucket', 'picks', 'avg_90d', '+30_hit', '-30_loser'])}

HP improves +30% capture in v2, but also increases the -30% loser rate. HP candidates need valuation/current-price and risk discipline.

## Theme caveat

For `high_conviction_top10_v2_final`, `UNKNOWN` accounts for `{unknown_picks}` of `173` picks. Named-theme rows are small-sample and directional only:

{md_table(top_named_rows, ['theme', 'picks', 'avg_90d'])}

The real theme acceleration module still needs PIT-populated fields before production claims are justified.

## Missed right-tail mechanical exclusions

These rows are mechanical exclusions, not proof of why the stock moved or proof the framework should have bought them.

{md_table(missed_rows, ['right_tail_bucket', 'mechanical_exclusion_category', 'count'])}

See `outputs/fundamental_backtest/analysis/missed_right_tail_mechanical_exclusions.csv` for ticker-level rows.

## Live-use recommendation from observed data

Use the observed v2 / high-conviction framework as the current operating setting, but prioritize `rm_signal_bucket=1` candidates for manual underwriting. Read that as the single-RM-signal bucket, not necessarily the literal RM1 rule. Be more cautious with `rm_signal_bucket=2+` multi-RM-signal candidates unless LLM/theme/valuation evidence is unusually strong. Keep source Top-30 -> deep analysis -> max 10 portfolio plan rather than relying on raw source Top-10.

## Future validation required before claiming full v2

Before claiming full live AKG+macro production v2 validation, populate or forward-test these PIT fields: `theme_acceleration_score`, `theme_acceleration_research_visibility`, `theme_acceleration_rescan_flag`, `akg_universe_tier`, `macro_mode`, `macro_spy`, `macro_entry_action`, and `macro_position_size_multiplier`.

## Companion outputs

- `outputs/fundamental_backtest/analysis/field_availability_audit.csv`
- `outputs/fundamental_backtest/analysis/variant_interpretation_matrix.csv`
- `outputs/fundamental_backtest/analysis/rm1_vs_rm2plus_drivers.csv` (legacy filename; rows use `rm_signal_bucket`, where `1` means one RM-related signal active, not necessarily the literal RM1 rule)
- `outputs/fundamental_backtest/analysis/hp_bucket_tail_risk_analysis.csv`
- `outputs/fundamental_backtest/analysis/variant_overlap_delta_by_quarter.csv`
- `outputs/fundamental_backtest/analysis/top_winners_losers_repeat_ticker_contribution.csv`
- `outputs/fundamental_backtest/analysis/2025Q1_drawdown_attribution.csv`
- `outputs/fundamental_backtest/analysis/missed_right_tail_mechanical_exclusions.csv`
- `outputs/fundamental_backtest/analysis/qa_leakage_verification.json`
- `outputs/fundamental_backtest/analysis/analysis_manifest.json`
"""
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(text, encoding="utf-8")


def main() -> int:
    ANALYSIS.mkdir(parents=True, exist_ok=True)
    pit = read_csv(PIT)
    selected = read_csv(SELECTED)
    summary = read_csv(STRATEGY_SUMMARY)
    by_quarter = read_csv(STRATEGY_BY_QUARTER)
    contrib = read_csv(CONTRIB)
    theme = read_csv(THEME)
    handoff = read_json(HANDOFF_MANIFEST)
    run_manifest = read_json(RUN_MANIFEST)
    feature_schema = read_json(FEATURE_SCHEMA)
    label_schema = read_json(LABEL_SCHEMA)

    field_audit = make_field_availability(pit, run_manifest, feature_schema, label_schema)
    variant_matrix = make_variant_matrix(summary)
    rm_drivers = make_rm_drivers(selected)
    hp_tail = make_hp_tail(selected)
    overlap = make_variant_overlap(selected)
    ticker_contribution = make_ticker_contribution(selected)
    q2025 = make_2025q1_attribution(selected, by_quarter)
    missed = make_missed_right_tail(pit, selected)
    qa = make_qa(pit, selected, by_quarter, field_audit, run_manifest, handoff)

    outputs = {
        "field_availability_audit.csv": field_audit,
        "variant_interpretation_matrix.csv": variant_matrix,
        "rm1_vs_rm2plus_drivers.csv": rm_drivers,
        "hp_bucket_tail_risk_analysis.csv": hp_tail,
        "variant_overlap_delta_by_quarter.csv": overlap,
        "top_winners_losers_repeat_ticker_contribution.csv": ticker_contribution,
        "2025Q1_drawdown_attribution.csv": q2025,
        "missed_right_tail_mechanical_exclusions.csv": missed,
    }
    for name, df in outputs.items():
        write_df(df, ANALYSIS / name)

    (ANALYSIS / "qa_leakage_verification.json").write_text(json.dumps(qa, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_report(pit, selected, summary, by_quarter, contrib, theme, qa, field_audit, variant_matrix, missed)

    manifest_paths = [ANALYSIS / name for name in outputs] + [ANALYSIS / "qa_leakage_verification.json", REPORT]
    analysis_manifest = {
        "analysis_version": "fundamental_top10_observed_backtest_analysis_v1",
        "source_bundle": str(BASE),
        "core_handoff_manifest": str(HANDOFF_MANIFEST),
        "scope_label": "High-Conviction Top-10 Observed-Data Backtest",
        "not_a_full_production_v2_validation_reason": "AKG theme acceleration and macro fields are blank/missing in the PIT panel.",
        "qa_passed": qa["passed"],
        "outputs": {str(path): file_sha256(path) for path in manifest_paths},
    }
    manifest_path = ANALYSIS / "analysis_manifest.json"
    manifest_path.write_text(json.dumps(analysis_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(json.dumps({"qa_passed": qa["passed"], "analysis_dir": str(ANALYSIS), "report": str(REPORT)}, sort_keys=True))
    return 0 if qa["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
