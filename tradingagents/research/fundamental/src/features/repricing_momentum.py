from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from src.features.common import clean


RM_LABELS = {
    "rm1_low_price_dislocation_momentum": "RM1 - Low-price dislocation momentum",
    "rm2_weak_acceleration": "RM2 - Weak-bucket acceleration",
    "rm3_mid_price_dislocation_momentum": "RM3 - Mid-price dislocation momentum",
    "rm4_persistent_repricing_wave": "RM4 - Persistent repricing wave",
    "repricing_momentum_priority": "Repricing momentum priority",
    "repricing_momentum_extension": "Repricing momentum extension",
}


def _numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _theme_text(series_map: dict[str, pd.Series]) -> pd.Series:
    text = pd.Series("", index=next(iter(series_map.values())).index)
    for series in series_map.values():
        text = text.str.cat(series.fillna("").astype(str), sep=" ")
    return text.str.lower()


def _quarter_sort_value(value: Any) -> int:
    text = clean(value)
    try:
        year, quarter = text.split("Q", maxsplit=1)
        return int(year) * 10 + int(quarter)
    except (TypeError, ValueError):
        return 0


def add_repricing_momentum(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for col in ["ticker", "quarter", "revenue_bucket", "pre_llm_fundamental_bucket", "entry_open", "pre_llm_fundamental_score", "entry_qoq_pct"]:
        if col not in df.columns:
            df[col] = ""
    if "quarter_sort" in df.columns:
        df = df.sort_values(["ticker", "quarter_sort"])
    else:
        df = df.assign(_rm_quarter_sort=df["quarter"].map(_quarter_sort_value)).sort_values(["ticker", "_rm_quarter_sort"]).drop(columns=["_rm_quarter_sort"])

    entry_open = _numeric(df["entry_open"])
    if "prior_entry_open" not in df.columns:
        df["prior_entry_open"] = entry_open.groupby(df["ticker"]).shift(1)
    prior_entry_open = _numeric(df["prior_entry_open"])

    existing_entry_qoq = _numeric(df["entry_qoq_pct"])
    computed_entry_qoq = ((entry_open / prior_entry_open) - 1) * 100
    computed_entry_qoq = computed_entry_qoq.mask(prior_entry_open.isna() | prior_entry_open.eq(0))
    df["entry_qoq_pct"] = existing_entry_qoq.where(existing_entry_qoq.notna(), computed_entry_qoq)

    if "prior_entry_qoq_pct" not in df.columns:
        df["prior_entry_qoq_pct"] = df.groupby("ticker")["entry_qoq_pct"].shift(1)

    scored = (
        df["pre_llm_fundamental_bucket"].map(clean).ne("not_scored")
        & df["pre_llm_fundamental_bucket"].map(clean).ne("")
        & df["entry_open"].map(clean).ne("")
        & df["revenue_bucket"].map(clean).ne("")
    )
    entry_open = _numeric(df["entry_open"])
    pre_score = _numeric(df["pre_llm_fundamental_score"])
    entry_qoq = _numeric(df["entry_qoq_pct"])
    prior_entry_qoq = _numeric(df["prior_entry_qoq_pct"])

    df["rm1_low_price_dislocation_momentum"] = (
        scored
        & entry_open.lt(25)
        & pre_score.le(0)
        & entry_qoq.ge(20)
    )
    df["rm2_weak_acceleration"] = (
        scored
        & entry_open.lt(25)
        & df["pre_llm_fundamental_bucket"].map(clean).eq("weak")
        & entry_qoq.ge(20)
    )
    df["rm3_mid_price_dislocation_momentum"] = (
        scored
        & entry_open.ge(15)
        & entry_open.lt(25)
        & pre_score.le(0)
        & entry_qoq.ge(20)
    )
    df["rm4_persistent_repricing_wave"] = (
        scored
        & entry_open.lt(25)
        & pre_score.le(0)
        & entry_qoq.ge(20)
        & prior_entry_qoq.ge(20)
    )
    df["repricing_momentum_extension"] = (
        df["rm1_low_price_dislocation_momentum"]
        | df["rm2_weak_acceleration"]
        | df["rm3_mid_price_dislocation_momentum"]
        | df["rm4_persistent_repricing_wave"]
    )
    df["repricing_momentum_priority"] = (
        df["rm2_weak_acceleration"]
        | df["rm3_mid_price_dislocation_momentum"]
        | df["rm4_persistent_repricing_wave"]
    )
    for col in [
        "primary_theme",
        "secondary_themes",
        "theme_tags",
        "theme_role",
        "theme_confidence",
        "theme_tailwind_score",
        "theme_evidence_summary",
        "theme_ai_data_center",
        "theme_ai_optical_networking",
        "theme_semiconductor_materials",
        "theme_compound_semiconductor",
        "theme_photonics",
        "theme_critical_materials",
    ]:
        if col not in df.columns:
            df[col] = ""
    theme_text = _theme_text(
        {
            "primary_theme": df["primary_theme"],
            "secondary_themes": df["secondary_themes"],
            "theme_tags": df["theme_tags"],
            "theme_evidence_summary": df["theme_evidence_summary"],
        }
    )
    generic_semicap_theme = theme_text.str.contains(
        "ai|data center|optical|photon|semiconductor|compound semiconductor|inp|critical material",
        regex=True,
        na=False,
    )
    df["theme_semicap_datacenter_confirmed"] = (
        _numeric(df["theme_ai_data_center"]).fillna(0).astype(int).eq(1)
        | _numeric(df["theme_ai_optical_networking"]).fillna(0).astype(int).eq(1)
        | _numeric(df["theme_semiconductor_materials"]).fillna(0).astype(int).eq(1)
        | _numeric(df["theme_compound_semiconductor"]).fillna(0).astype(int).eq(1)
        | _numeric(df["theme_photonics"]).fillna(0).astype(int).eq(1)
        | generic_semicap_theme
    ).astype(int)
    theme_confirmed = _numeric(df["theme_tailwind_score"]).fillna(0).gt(0) | df["theme_semicap_datacenter_confirmed"].astype(bool)
    score = np.zeros(len(df))
    weak_repricing = pre_score.le(0) & entry_qoq.ge(20)
    score += np.where(weak_repricing, 6, 0)
    score += np.where(pre_score.le(0) & entry_qoq.ge(50), 4, 0)
    score += np.where(pre_score.le(0) & entry_qoq.ge(100), 4, 0)
    score += np.where(df["rm4_persistent_repricing_wave"], 5, 0)
    score += np.where(theme_confirmed, 5, 0)
    score += np.where(theme_confirmed & df["repricing_momentum_extension"], 5, 0)
    df["market_repricing_score"] = np.minimum(score, 20).astype(int)
    df["force_llm_extraction"] = df["repricing_momentum_extension"].astype(int)
    df["repricing_started"] = df["repricing_momentum_extension"].astype(int)
    df["repricing_confirmed"] = df["rm4_persistent_repricing_wave"].astype(int)
    df["positive_repricing_status"] = df["repricing_momentum_priority"].map(lambda value: "priority" if value else "")
    return df


def rm_labels_from_bool(row: dict[str, Any]) -> dict[str, str]:
    return {column: RM_LABELS[column] if bool(row.get(column)) else "" for column in RM_LABELS}


def rm_bool_from_row(row: dict[str, Any]) -> dict[str, bool]:
    frame = pd.DataFrame([row])
    result = add_repricing_momentum(frame).iloc[0].to_dict()
    return {column: bool(result.get(column)) for column in RM_LABELS}
