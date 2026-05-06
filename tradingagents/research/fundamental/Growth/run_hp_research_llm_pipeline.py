from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
GROWTH = Path(__file__).resolve().parent
if str(GROWTH) not in sys.path:
    sys.path.insert(0, str(GROWTH))

from build_hp_research_llm_packets import build_records, write_packet_outputs
from build_rank_scores import build_rank_scores
from build_tier3_llm_packets import write_evaluation, write_post_llm_scores
from spec_convex_llm_testset import output_path
from src.features.hp_subtiers import add_hp_subtiers
from src.features.post_llm_subtiers import add_post_llm_subtiers
from src.features.pre_llm_scores import REVENUE_BUCKETS
from src.features.repricing_momentum import add_repricing_momentum


BASE = ROOT / "Growth" / "earnings_8k_sec_parser"

DEFAULT_INPUT = BASE / "combined_all_tiers_hp_extensions_llm_rank_scores_2021Q4_2026Q1_partial.csv"
DEFAULT_PRE_LLM = BASE / "pre_llm_fundamental_score_2021Q4_2026Q1_partial.csv"
DEFAULT_POST_TIER = BASE / "post_llm_tier1_tier2_tier3_tier4_2021Q4_2026Q1_partial_gpt55_mixed_combined.csv"
DEFAULT_HP_POST = BASE / "post_llm_hp1_hp4_2021Q4_2026Q1_partial_gpt55_medium_scores.csv"
DEFAULT_HP_POST_SUMMARY = BASE / "post_llm_hp1_hp4_2021Q4_2026Q1_partial_gpt55_medium_summary.csv"
DEFAULT_COMBINED = BASE / "combined_tier0_tier1_tier2_tier3_tier4_hp1_hp4_2021Q4_2026Q1_partial_gpt55_mixed.csv"
DEFAULT_COMBINED_SUMMARY = BASE / "combined_tier0_tier1_tier2_tier3_tier4_hp1_hp4_2021Q4_2026Q1_partial_gpt55_mixed_summary.csv"
DEFAULT_RANK = BASE / "rank_scored_tier0_tier1_tier2_tier3_tier4_hp1_hp4_2021Q4_2026Q1_partial_gpt55_mixed.csv"
DEFAULT_RANK_SUMMARY = BASE / "rank_scored_tier0_tier1_tier2_tier3_tier4_hp1_hp4_2021Q4_2026Q1_partial_gpt55_mixed_summary.csv"
DEFAULT_COMBINED_ALL = BASE / "combined_all_tiers_hp_extensions_llm_rank_scores_2021Q4_2026Q1_partial.csv"
DEFAULT_COMBINED_ALL_SUMMARY = BASE / "combined_all_tiers_hp_extensions_llm_rank_scores_2021Q4_2026Q1_partial_summary.csv"


def _run(cmd: list[str]) -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{ROOT}{os.pathsep}{env.get('PYTHONPATH', '')}".rstrip(os.pathsep)
    print(" ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=ROOT, check=True, env=env)


def _read(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False) if path.exists() else pd.DataFrame()


def _append_hp_scores(new_scores: Path, hp_master: Path, hp_summary: Path) -> None:
    new = _read(new_scores)
    if new.empty:
        return
    hp = add_hp_subtiers(new.copy())
    for col in ["hp1_LLM_best", "hp2_LLM_best", "hp2_watch_LLM_best", "hp3_theme_confirmed", "hp4_LLM_supported", "hp_LLM_best"]:
        new[col] = hp[col].map(lambda value: int(bool(value)))
    for col, label in {
        "hp_production_extension": "HP production extension",
        "hp_research_extension": "HP research extension",
        "hp0_high_price_broad": "HP0 - High-price broad watchlist",
    }.items():
        new[col] = hp[col].map(lambda value: label if bool(value) else "")
    new["has_post_llm"] = "1"
    new["in_hp1_hp4_post_llm_file"] = "1"
    new["hp_structure_score"] = hp["hp_structure_score"]
    for col in ["tier_0_bucket", "tier_1_bucket", "tier_2_bucket", "tier_3_bucket", "tier_4_bucket"]:
        if col not in new.columns:
            new[col] = ""

    old = _read(hp_master)
    all_cols = list(dict.fromkeys([*(old.columns if not old.empty else []), *new.columns]))
    old = old.reindex(columns=all_cols, fill_value="") if not old.empty else pd.DataFrame(columns=all_cols)
    new = new.reindex(columns=all_cols, fill_value="")
    combined = pd.concat([old, new], ignore_index=True).drop_duplicates(["quarter", "ticker"], keep="last")
    combined.to_csv(hp_master, index=False)

    summary: list[dict[str, Any]] = [{"metric": "post_llm_rows", "bucket": "", "value": len(combined)}]
    for col in [
        "post_llm_candidate_flag",
        "post_llm_high_priority_flag",
        "post_llm_demote_flag",
        "hp1_LLM_best",
        "hp2_LLM_best",
        "hp2_watch_LLM_best",
        "hp3_theme_confirmed",
        "hp4_LLM_supported",
        "hp_LLM_best",
    ]:
        if col in combined.columns:
            summary.append(
                {
                    "metric": "flag_count",
                    "bucket": col,
                    "value": int(pd.to_numeric(combined[col], errors="coerce").fillna(0).astype(int).sum()),
                }
            )
    if "post_llm_fundamental_bucket" in combined.columns:
        for bucket, count in combined["post_llm_fundamental_bucket"].value_counts().items():
            summary.append({"metric": "post_llm_fundamental_bucket", "bucket": bucket, "value": int(count)})
    pd.DataFrame(summary).to_csv(hp_summary, index=False)


def _recompute_tier0_bucket(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    scored = out.get("pre_llm_fundamental_bucket", pd.Series([""] * len(out), index=out.index)).astype(str).str.strip().ne("not_scored")
    entry_open = pd.to_numeric(out.get("entry_open", pd.Series([None] * len(out), index=out.index)), errors="coerce")
    revenue_ok = out.get("revenue_bucket", pd.Series([""] * len(out), index=out.index)).isin(REVENUE_BUCKETS)
    tier0 = scored & entry_open.lt(25) & revenue_ok
    out["tier_0_bucket"] = tier0.map(lambda value: "Tier 0 - Broad right-tail scouting universe" if bool(value) else "")
    return out


def _merge_and_rank(
    *,
    pre_llm: Path,
    post_tier: Path,
    hp_post: Path,
    combined_path: Path,
    combined_summary: Path,
    rank_path: Path,
    rank_summary: Path,
    combined_all: Path,
    combined_all_summary: Path,
) -> None:
    pre = _read(pre_llm)
    post = _read(post_tier)
    hp = _read(hp_post)
    post_by = {(r["quarter"], r["ticker"]): r.to_dict() for _, r in post.iterrows()} if not post.empty else {}
    hp_by = {(r["quarter"], r["ticker"]): r.to_dict() for _, r in hp.iterrows()} if not hp.empty else {}
    all_cols = list(dict.fromkeys([*pre.columns, *(post.columns if not post.empty else []), *(hp.columns if not hp.empty else [])]))

    rows = []
    for _, base in pre.iterrows():
        key = (base["quarter"], base["ticker"])
        row = {col: "" for col in all_cols}
        row.update(base.to_dict())
        for source in [post_by.get(key), hp_by.get(key)]:
            if not source:
                continue
            for col, value in source.items():
                if col.startswith("tier_") and row.get(col):
                    continue
                if value != "":
                    row[col] = value
            row["has_post_llm"] = "1"
        if key in hp_by:
            row["in_hp1_hp4_post_llm_file"] = "1"
        rows.append(row)

    df = _recompute_tier0_bucket(add_post_llm_subtiers(pd.DataFrame(rows)).copy())
    hp_calc = add_hp_subtiers(df.copy())
    rm_calc = add_repricing_momentum(hp_calc.copy())
    for col, label in {
        "hp0_high_price_broad": "HP0 - High-price broad watchlist",
        "hp1_quality_pullback": "HP1 - Quality pullback re-rater",
        "hp2_dislocation_momentum_priority": "HP2 - Dislocation momentum re-rater",
        "hp2_dislocation_momentum_watch": "HP2 - Dislocation momentum watch",
        "hp3_large_quality_theme_exception": "HP3 - Large-revenue theme-leader exception",
        "hp4_score_reacceleration_watch": "HP4 - Fundamental reacceleration watch tag",
        "hp_production_extension": "HP production extension",
        "hp_research_extension": "HP research extension",
    }.items():
        df[col] = hp_calc[col].map(lambda value: label if bool(value) else "")
    for col, label in {
        "rm1_low_price_dislocation_momentum": "RM1 - Low-price dislocation momentum",
        "rm2_weak_acceleration": "RM2 - Weak-bucket acceleration",
        "rm3_mid_price_dislocation_momentum": "RM3 - Mid-price dislocation momentum",
        "rm4_persistent_repricing_wave": "RM4 - Persistent repricing wave",
        "repricing_momentum_priority": "Repricing momentum priority",
        "repricing_momentum_extension": "Repricing momentum extension",
    }.items():
        df[col] = rm_calc[col].map(lambda value: label if bool(value) else "")
    for col in [
        "prior_entry_qoq_pct",
        "prior_entry_open",
        "market_repricing_score",
        "force_llm_extraction",
        "repricing_started",
        "repricing_confirmed",
        "positive_repricing_status",
        "theme_ai_data_center",
        "theme_ai_optical_networking",
        "theme_semiconductor_materials",
        "theme_compound_semiconductor",
        "theme_photonics",
        "theme_critical_materials",
        "theme_driver_summary",
        "theme_semicap_datacenter_confirmed",
        "theme_score",
        "theme_confidence",
        "primary_theme",
        "secondary_themes",
        "theme_tags",
        "theme_role",
        "theme_driver_type",
        "theme_momentum",
        "theme_evidence",
        "theme_tailwind_score",
        "theme_evidence_summary",
    ]:
        if col in rm_calc.columns:
            df[col] = rm_calc[col]
    tier0 = (
        df.get("tier_0_bucket", pd.Series([""] * len(df), index=df.index)).astype(str).str.strip().ne("")
        | df.get("tier_bucket", pd.Series([""] * len(df), index=df.index)).astype(str).str.strip().ne("")
    )
    tier1 = df.get("tier_1_bucket", pd.Series([""] * len(df), index=df.index)).astype(str).str.strip().ne("")
    tier2 = df.get("tier_2_bucket", pd.Series([""] * len(df), index=df.index)).astype(str).str.strip().ne("")
    tier3 = df.get("tier_3_bucket", pd.Series([""] * len(df), index=df.index)).astype(str).str.strip().ne("")
    tier4 = df.get("tier_4_bucket", pd.Series([""] * len(df), index=df.index)).astype(str).str.strip().ne("")
    hp_research = df["hp_research_extension"].astype(str).str.strip().ne("")
    rm_research = df["repricing_momentum_extension"].astype(str).str.strip().ne("")
    hp_prod = df["hp_production_extension"].astype(str).str.strip().ne("")
    repricing_started = pd.to_numeric(df["repricing_started"], errors="coerce").fillna(0).astype(int).eq(1)
    repricing_confirmed = pd.to_numeric(df["repricing_confirmed"], errors="coerce").fillna(0).astype(int).eq(1)
    df["force_llm_extraction"] = (tier1 | tier2 | tier3 | tier4 | hp_prod | hp_research | rm_research | repricing_started | repricing_confirmed).map(lambda value: 1 if bool(value) else 0)
    df["extended_candidate_universe"] = (tier0 | hp_prod).map(lambda value: "Extended candidate universe" if bool(value) else "")
    df["extended_research_universe"] = (tier0 | hp_research).map(lambda value: "Extended research universe" if bool(value) else "")
    for col in ["hp1_LLM_best", "hp2_LLM_best", "hp2_watch_LLM_best", "hp3_theme_confirmed", "hp4_LLM_supported", "hp_LLM_best"]:
        df[col] = hp_calc[col].map(lambda value: int(bool(value)))
    df["hp_structure_score"] = hp_calc["hp_structure_score"]
    if "has_post_llm" not in df.columns:
        df["has_post_llm"] = ""
    df["has_post_llm"] = df["has_post_llm"].map(lambda value: "1" if str(value).strip() == "1" else "")
    df.to_csv(combined_path, index=False)

    summary = [{"metric": "combined_rows", "bucket": "", "value": len(df)}]
    for col in ["has_post_llm", "in_hp1_hp4_post_llm_file", "hp_research_extension", "hp_LLM_best"]:
        if col in df.columns:
            if col in {"has_post_llm", "in_hp1_hp4_post_llm_file", "hp_LLM_best"}:
                value = int(pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int).sum())
            else:
                value = int(df[col].astype(str).str.strip().ne("").sum())
            summary.append({"metric": "flag_count", "bucket": col, "value": value})
    pd.DataFrame(summary).to_csv(combined_summary, index=False)

    build_rank_scores(combined_path, rank_path, rank_summary, None)
    ranked = _read(rank_path)
    ranked.to_csv(combined_all, index=False)

    summary_all = [{"metric": "rows", "bucket": "", "value": len(ranked)}]
    for col in ["has_post_llm", "in_hp1_hp4_post_llm_file", "hp_research_extension", "hp_LLM_best", "extended_research_universe"]:
        if col in ranked.columns:
            if col in {"has_post_llm", "in_hp1_hp4_post_llm_file", "hp_LLM_best"}:
                value = int(pd.to_numeric(ranked[col], errors="coerce").fillna(0).astype(int).sum())
            else:
                value = int(ranked[col].astype(str).str.strip().ne("").sum())
            summary_all.append({"metric": "flag_count", "bucket": col, "value": value})
    pd.DataFrame(summary_all).to_csv(combined_all_summary, index=False)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run HP research LLM extraction and rebuild rank files")
    parser.add_argument("--input-csv", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-prefix", type=Path, required=True)
    parser.add_argument("--tickers", default="")
    parser.add_argument("--model", default="gpt-5.5")
    parser.add_argument("--reasoning-effort", default="medium")
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--max-attempts", type=int, default=2)
    parser.add_argument("--skip-llm", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    tickers = {ticker.strip().upper() for ticker in args.tickers.split(",") if ticker.strip()}
    records = build_records(
        args.input_csv,
        base_dir=BASE,
        tickers=tickers,
        sample_prefix="HPX",
        max_snippets=18,
    )
    if not records:
        print("hp_llm_records=0 no pending HP research rows missing LLM")
        return
    write_packet_outputs(records, args.output_prefix)
    packets = output_path(args.output_prefix, "_packets.jsonl")
    extractions = output_path(args.output_prefix, "_extractions.csv")
    if not args.skip_llm and records:
        _run(
            [
                str(ROOT / ".venv" / "bin" / "python"),
                "Growth/run_spec_convex_llm_extraction.py",
                "--packets",
                str(packets),
                "--output-dir",
                str(output_path(args.output_prefix, "_llm")),
                "--output-csv",
                str(extractions),
                "--model",
                args.model,
                "--reasoning-effort",
                args.reasoning_effort,
                "--batch-size",
                str(args.batch_size),
                "--max-attempts",
                str(args.max_attempts),
            ]
        )
    if not extractions.exists():
        raise SystemExit(f"missing_extractions:{extractions}")

    write_evaluation(output_path(args.output_prefix, "_selection.csv"), extractions, args.output_prefix)
    scores = output_path(args.output_prefix, "_post_llm_scores.csv")
    write_post_llm_scores(output_path(args.output_prefix, "_joined.csv"), scores, output_path(args.output_prefix, "_post_llm_summary.csv"))
    _append_hp_scores(scores, DEFAULT_HP_POST, DEFAULT_HP_POST_SUMMARY)
    _merge_and_rank(
        pre_llm=DEFAULT_PRE_LLM,
        post_tier=DEFAULT_POST_TIER,
        hp_post=DEFAULT_HP_POST,
        combined_path=DEFAULT_COMBINED,
        combined_summary=DEFAULT_COMBINED_SUMMARY,
        rank_path=DEFAULT_RANK,
        rank_summary=DEFAULT_RANK_SUMMARY,
        combined_all=DEFAULT_COMBINED_ALL,
        combined_all_summary=DEFAULT_COMBINED_ALL_SUMMARY,
    )
    print(f"hp_llm_records={len(records)}")


if __name__ == "__main__":
    main()
