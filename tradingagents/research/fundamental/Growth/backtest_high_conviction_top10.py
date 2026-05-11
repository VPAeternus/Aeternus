#!/usr/bin/env python3
"""Backtest high-conviction top-10 mode on ranked fundamental CSV data.

This is an offline proxy for the live high-conviction workflow:
discover broadly, deep-select 12 names, then choose up to 10 PM-grade names.

No realized return columns are used for ranking or selection. Return columns are
labels only.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


DEFAULT_INPUT = Path(
    "Growth/earnings_8k_sec_parser/"
    "combined_all_tiers_hp_extensions_llm_rank_scores_2021Q4_2026Q1_partial.csv"
)
DEFAULT_OUTPUT_DIR = Path("Growth/earnings_8k_sec_parser/backtests/high_conviction_top10")


BOOL_TRUE_STRINGS = {"1", "true", "yes", "y"}
CONFIDENCE_MAP = {
    "very high": 5,
    "high": 4,
    "medium": 3,
    "med": 3,
    "low": 2,
    "none": 0,
    "": 0,
}


def _num(df: pd.DataFrame, col: str, default: float = 0.0) -> pd.Series:
    if col not in df.columns:
        return pd.Series(default, index=df.index, dtype="float64")
    return pd.to_numeric(df[col], errors="coerce").fillna(default)


def _bool(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series(False, index=df.index)
    series = df[col]
    if series.dtype == bool:
        return series.fillna(False)
    if pd.api.types.is_numeric_dtype(series):
        return pd.to_numeric(series, errors="coerce").fillna(0).ne(0)
    return series.fillna("").astype(str).str.strip().str.lower().isin(BOOL_TRUE_STRINGS)


def _confidence_score(df: pd.DataFrame) -> pd.Series:
    if "confidence" not in df.columns:
        return pd.Series(0, index=df.index, dtype="int64")
    raw = df["confidence"]
    numeric = pd.to_numeric(raw, errors="coerce")
    text = raw.fillna("").astype(str).str.strip().str.lower().map(CONFIDENCE_MAP)
    return numeric.fillna(text).fillna(0).clip(0, 5).astype(int)


def _any_flag(df: pd.DataFrame, cols: Iterable[str]) -> pd.Series:
    result = pd.Series(False, index=df.index)
    for col in cols:
        result = result | _bool(df, col)
    return result


def add_high_conviction_fields(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()

    score = _num(out, "entry_score_0_100")
    market_repricing = _num(out, "market_repricing_score")
    structure = _num(out, "total_structure_score")
    llm = _num(out, "llm_business_improvement_score")
    confidence_score = _confidence_score(out)

    tier_core = _any_flag(
        out,
        [
            "tier_1_bucket",
            "tier_2_bucket",
            "post_llm_tier_1_3_flag",
            "post_llm_tier_2_3_flag",
            "hp1_LLM_best",
            "hp3_theme_confirmed",
        ],
    )
    momentum = _any_flag(
        out,
        [
            "repricing_momentum_priority",
            "rm2_weak_acceleration",
            "rm3_mid_price_dislocation_momentum",
            "rm4_persistent_repricing_wave",
            "hp2_LLM_best",
            "hp2_dislocation_momentum_priority",
            "hp4_LLM_supported",
        ],
    ) | market_repricing.ge(14)
    hp_production = _bool(out, "hp_production_extension")
    llm_best = (
        _bool(out, "post_llm_candidate_flag")
        & _num(out, "causal_change").eq(3)
        & _num(out, "negative_revision_risk", default=99).le(2)
    )
    severe_risk = _bool(out, "post_llm_demote_flag") | _num(out, "negative_revision_risk").ge(4)

    scored = (
        out.get("pre_llm_fundamental_bucket", pd.Series("", index=out.index))
        .fillna("")
        .astype(str)
        .ne("not_scored")
        & _num(out, "entry_open", default=np.nan).notna()
    )

    classic_path = score.ge(70) & confidence_score.ge(3)
    override_path = (
        momentum
        | _bool(out, "hp_LLM_best")
        | _bool(out, "hp3_theme_confirmed")
        | _bool(out, "post_llm_tier_1_3_flag")
        | _bool(out, "post_llm_tier_2_3_flag")
    ) & (llm_best | market_repricing.ge(14) | _bool(out, "hp_LLM_best"))

    out["hc_confidence_score"] = confidence_score
    out["hc_core_lane"] = tier_core & ~momentum
    out["hc_momentum_lane"] = momentum
    out["hc_discovery_candidate"] = scored & (score.ge(60) | tier_core | momentum | hp_production)
    out["hc_final_eligible"] = scored & ~severe_risk & (classic_path | override_path)
    out["hc_rank_score"] = (
        score
        + np.where(momentum, 12, 0)
        + np.where(_bool(out, "hp_LLM_best"), 10, 0)
        + np.where(hp_production, 6, 0)
        + np.where(llm_best, 8, 0)
        + market_repricing.clip(0, 20) * 0.75
        + structure.clip(0, 30) * 0.25
        + llm.clip(0, 45) * 0.25
        - np.where(severe_risk, 25, 0)
    ).round(4)
    return out


def _select_with_quota(group: pd.DataFrame, *, deep_k: int, core_quota: int, momentum_quota: int) -> pd.Index:
    ranked = group.sort_values(["hc_rank_score", "entry_score_0_100", "ticker"], ascending=[False, False, True])
    selected: list[int] = []

    core = ranked[ranked["hc_core_lane"] & ~ranked["hc_momentum_lane"]].head(core_quota)
    selected.extend(core.index.tolist())

    momentum = ranked[ranked["hc_momentum_lane"] & ~ranked.index.isin(selected)].head(momentum_quota)
    selected.extend(momentum.index.tolist())

    if len(selected) < deep_k:
        fill = ranked[~ranked.index.isin(selected)].head(deep_k - len(selected))
        selected.extend(fill.index.tolist())

    return pd.Index(selected[:deep_k])


def run_backtest(
    df: pd.DataFrame,
    *,
    discovery_k: int = 30,
    deep_k: int = 12,
    core_quota: int = 6,
    momentum_quota: int = 6,
    max_positions: int = 10,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    data = add_high_conviction_fields(df)
    picks: list[pd.DataFrame] = []

    for quarter, group in data.groupby("quarter", sort=True):
        discovered = (
            group[group["hc_discovery_candidate"]]
            .sort_values(["hc_rank_score", "entry_score_0_100", "ticker"], ascending=[False, False, True])
            .head(discovery_k)
        )
        if discovered.empty:
            continue
        deep_ids = _select_with_quota(
            discovered,
            deep_k=deep_k,
            core_quota=core_quota,
            momentum_quota=momentum_quota,
        )
        deep = discovered.loc[deep_ids].copy()
        final = (
            deep[deep["hc_final_eligible"]]
            .sort_values(["hc_rank_score", "entry_score_0_100", "ticker"], ascending=[False, False, True])
            .head(max_positions)
            .copy()
        )
        if final.empty:
            continue
        final["hc_selected_rank"] = range(1, len(final) + 1)
        picks.append(final)

    selections = pd.concat(picks, ignore_index=True) if picks else pd.DataFrame()
    if selections.empty:
        return data, selections

    ret90 = _num(selections, "return_90d_pct", default=np.nan)
    ret60 = _num(selections, "return_60d_pct", default=np.nan)
    ret30 = _num(selections, "return_30d_pct", default=np.nan)
    selections["hc_return_90d_label"] = ret90
    selections["hc_win_90d_ge_30"] = ret90.ge(30)
    selections["hc_loss_90d_le_neg30"] = ret90.le(-30)
    selections["hc_return_60d_label"] = ret60
    selections["hc_return_30d_label"] = ret30

    quarter_rows = []
    for quarter, group in selections.groupby("quarter", sort=True):
        qret = pd.to_numeric(group["hc_return_90d_label"], errors="coerce").dropna()
        quarter_rows.append(
            {
                "quarter": quarter,
                "selected_count": len(group),
                "valid_90d_count": int(qret.shape[0]),
                "avg_return_90d_pct": float(qret.mean()) if not qret.empty else np.nan,
                "median_return_90d_pct": float(qret.median()) if not qret.empty else np.nan,
                "win_rate_90d_ge_30_pct": float((qret >= 30).mean() * 100) if not qret.empty else np.nan,
                "loss_rate_90d_le_neg30_pct": float((qret <= -30).mean() * 100) if not qret.empty else np.nan,
                "best_return_90d_pct": float(qret.max()) if not qret.empty else np.nan,
                "worst_return_90d_pct": float(qret.min()) if not qret.empty else np.nan,
                "tickers": ",".join(group["ticker"].astype(str).tolist()),
            }
        )
    summary = pd.DataFrame(quarter_rows)
    return summary, selections


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--discovery-k", type=int, default=30)
    parser.add_argument("--deep-k", type=int, default=12)
    parser.add_argument("--core-quota", type=int, default=6)
    parser.add_argument("--momentum-quota", type=int, default=6)
    parser.add_argument("--max-positions", type=int, default=10)
    args = parser.parse_args()

    df = pd.read_csv(args.input, low_memory=False)
    summary, selections = run_backtest(
        df,
        discovery_k=args.discovery_k,
        deep_k=args.deep_k,
        core_quota=args.core_quota,
        momentum_quota=args.momentum_quota,
        max_positions=args.max_positions,
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = args.output_dir / "high_conviction_top10_quarter_summary.csv"
    selections_path = args.output_dir / "high_conviction_top10_selections.csv"
    summary.to_csv(summary_path, index=False)
    selections.to_csv(selections_path, index=False)

    valid = pd.to_numeric(selections.get("hc_return_90d_label", pd.Series(dtype=float)), errors="coerce").dropna()
    aggregate = {
        "quarters": int(summary.shape[0]),
        "selected_rows": int(selections.shape[0]),
        "valid_90d_rows": int(valid.shape[0]),
        "avg_return_90d_pct": float(valid.mean()) if not valid.empty else np.nan,
        "median_return_90d_pct": float(valid.median()) if not valid.empty else np.nan,
        "win_rate_90d_ge_30_pct": float((valid >= 30).mean() * 100) if not valid.empty else np.nan,
        "loss_rate_90d_le_neg30_pct": float((valid <= -30).mean() * 100) if not valid.empty else np.nan,
        "summary_path": str(summary_path),
        "selections_path": str(selections_path),
    }
    pd.DataFrame([aggregate]).to_csv(args.output_dir / "high_conviction_top10_aggregate.csv", index=False)
    print(pd.Series(aggregate).to_string())


if __name__ == "__main__":
    main()
