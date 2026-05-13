from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from tradingagents.research.fundamental.src.features.common import clean, flag, to_float


REVENUE_LARGE = ">$10B"

HP_LABELS = {
    "hp0_high_price_broad": "HP0 - High-price broad watchlist",
    "hp1_quality_pullback": "HP1 - Quality pullback re-rater",
    "hp2_dislocation_momentum_priority": "HP2 - Dislocation momentum re-rater",
    "hp2_dislocation_momentum_watch": "HP2 - Dislocation momentum watch",
    "hp3_large_quality_theme_exception": "HP3 - Large-revenue theme-leader exception",
    "hp4_score_reacceleration_watch": "HP4 - Fundamental reacceleration watch tag",
    "hp_production_extension": "HP production extension",
    "hp_research_extension": "HP research extension",
}

HP_BOOL_COLUMNS = [
    *HP_LABELS,
    "hp1_LLM_best",
    "hp2_LLM_best",
    "hp2_watch_LLM_best",
    "hp3_theme_confirmed",
    "hp4_LLM_supported",
    "hp_LLM_best",
]


def _numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _flag_series(series: pd.Series) -> pd.Series:
    return series.map(flag)


def _quarter_sort_value(value: Any) -> int:
    text = clean(value)
    try:
        year, quarter = text.split("Q", maxsplit=1)
        return int(year) * 10 + int(quarter)
    except (ValueError, TypeError):
        return 0


def add_hp_subtiers(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    if "ticker" not in df.columns:
        df["ticker"] = ""
    if "quarter" not in df.columns:
        df["quarter"] = ""
    if "revenue_bucket" not in df.columns:
        df["revenue_bucket"] = ""
    if "pre_llm_fundamental_bucket" not in df.columns:
        df["pre_llm_fundamental_bucket"] = "not_scored"
    for col in ["pre_llm_fundamental_score", "entry_open", "entry_qoq_pct", "negative_revision_risk", "causal_change"]:
        if col not in df.columns:
            df[col] = np.nan

    for col in [
        "theme_active",
        "theme_cohort_strength",
        "theme_leader_or_direct_beneficiary",
    ]:
        if col not in df.columns:
            df[col] = 0

    if "quarter_sort" in df.columns:
        df = df.sort_values(["ticker", "quarter_sort"])
    else:
        sort_values = df["quarter"].map(_quarter_sort_value) if "quarter" in df.columns else pd.Series([0] * len(df))
        df = df.assign(_hp_quarter_sort=sort_values).sort_values(["ticker", "_hp_quarter_sort"]).drop(columns=["_hp_quarter_sort"])

    for col in ["pre_llm_fundamental_score", "entry_open", "entry_qoq_pct", "negative_revision_risk", "causal_change", "score_change"]:
        if col in df.columns:
            df[col] = _numeric(df[col])

    if "prior_pre_llm_fundamental_score" not in df.columns and "pre_llm_fundamental_score" in df.columns:
        df["prior_pre_llm_fundamental_score"] = df.groupby("ticker")["pre_llm_fundamental_score"].shift(1)

    if "score_change" not in df.columns:
        df["score_change"] = df["pre_llm_fundamental_score"] - df["prior_pre_llm_fundamental_score"]

    scored = (
        df["pre_llm_fundamental_bucket"].ne("not_scored")
        & df["entry_open"].notna()
        & df["revenue_bucket"].notna()
        & df["revenue_bucket"].astype(str).str.strip().ne("")
    )

    llm_best = (
        _flag_series(df.get("post_llm_candidate_flag", pd.Series([0] * len(df), index=df.index)))
        & df.get("causal_change", pd.Series([np.nan] * len(df), index=df.index)).eq(3)
        & df.get("negative_revision_risk", pd.Series([np.nan] * len(df), index=df.index)).le(2)
    )

    df["hp0_high_price_broad"] = scored & df["entry_open"].ge(25)
    df["hp1_quality_pullback"] = scored & df["entry_open"].ge(25) & df["entry_qoq_pct"].le(-20) & df["pre_llm_fundamental_bucket"].isin(["good", "strong"])
    df["hp1_LLM_best"] = df["hp1_quality_pullback"] & llm_best

    df["hp2_dislocation_momentum_priority"] = scored & df["entry_open"].ge(25) & df["pre_llm_fundamental_score"].le(0) & df["entry_qoq_pct"].ge(20)
    df["hp2_dislocation_momentum_watch"] = scored & df["entry_open"].ge(25) & df["pre_llm_fundamental_score"].le(0) & df["entry_qoq_pct"].ge(15) & df["entry_qoq_pct"].lt(20)
    df["hp2_LLM_best"] = df["hp2_dislocation_momentum_priority"] & llm_best
    df["hp2_watch_LLM_best"] = df["hp2_dislocation_momentum_watch"] & llm_best

    df["hp3_large_quality_theme_exception"] = scored & df["entry_open"].ge(25) & df["revenue_bucket"].eq(REVENUE_LARGE) & df["pre_llm_fundamental_score"].ge(8)
    df["hp3_theme_confirmed"] = df["hp3_large_quality_theme_exception"] & (
        llm_best
        | _flag_series(df["theme_active"])
        | _flag_series(df["theme_cohort_strength"])
        | _flag_series(df["theme_leader_or_direct_beneficiary"])
    )

    df["hp4_score_reacceleration_watch"] = scored & df["entry_open"].ge(25) & df["score_change"].ge(2) & df["entry_qoq_pct"].ge(10)
    df["hp4_LLM_supported"] = df["hp4_score_reacceleration_watch"] & llm_best

    df["hp_production_extension"] = (
        df["hp1_quality_pullback"]
        | df["hp2_dislocation_momentum_priority"]
        | df["hp3_large_quality_theme_exception"]
    )

    df["hp_research_extension"] = (
        df["hp1_quality_pullback"]
        | df["hp2_dislocation_momentum_priority"]
        | df["hp2_dislocation_momentum_watch"]
        | df["hp3_large_quality_theme_exception"]
        | df["hp4_score_reacceleration_watch"]
    )

    df["hp_LLM_best"] = df["hp_production_extension"] & llm_best

    df["hp_structure_score"] = np.maximum.reduce(
        [
            np.where(df["hp1_quality_pullback"], 15, 0),
            np.where(df["hp2_dislocation_momentum_priority"], 18, 0),
            np.where(df["hp2_dislocation_momentum_watch"], 8, 0),
            np.where(df["hp3_large_quality_theme_exception"], 10, 0),
            np.where(df["hp4_score_reacceleration_watch"], 8, 0),
        ]
    )

    if "tier_structure_score" in df.columns:
        df["total_structure_score"] = pd.concat(
            [_numeric(df["tier_structure_score"]), pd.Series(df["hp_structure_score"], index=df.index)],
            axis=1,
        ).max(axis=1)

    return df


def hp_labels_from_bool(row: dict[str, Any]) -> dict[str, str]:
    return {column: HP_LABELS[column] if flag(row.get(column)) else "" for column in HP_LABELS}


def hp_bool_from_row(row: dict[str, Any]) -> dict[str, bool]:
    frame = pd.DataFrame([row])
    result = add_hp_subtiers(frame).iloc[0].to_dict()
    return {column: bool(result.get(column)) for column in HP_BOOL_COLUMNS if column in result}
