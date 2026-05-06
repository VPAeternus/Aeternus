from __future__ import annotations

import re

import pandas as pd


POST_LLM_SUBTIER_LABELS = {
    "post_llm_tier_1_1_flag": "Tier 1.1 - LLM-supported candidate",
    "post_llm_tier_1_2_flag": "Tier 1.2 - Causal re-rating candidate",
    "post_llm_tier_1_3_flag": "Tier 1.3 - Best balanced production subset",
    "post_llm_tier_1_4_flag": "Tier 1.4 - Clean high-priority subset",
    "post_llm_tier_2_1_flag": "Tier 2.1 - LLM-supported",
    "post_llm_tier_2_2_flag": "Tier 2.2 - Causal re-rating",
    "post_llm_tier_2_3_flag": "Tier 2.3 - Best balanced LLM subset",
    "post_llm_tier_3_1_flag": "Tier 3.1 - Cleaner LLM-positive Tier 3",
    "post_llm_tier_3_2_flag": "Tier 3.2 - LLM inflection / high priority",
    "post_llm_tier_3_3_flag": "Tier 3.3 - Persistent re-rating setup",
    "post_llm_tier_3_4_flag": "Tier 3.4 - Persistent high-priority re-rating",
    "post_llm_tier_4_1_flag": "Tier 4.1 - LLM-supported aggressive",
    "post_llm_tier_4_2_flag": "Tier 4.2 - Causal re-rating candidate",
    "post_llm_tier_4_3_flag": "Tier 4.3 - Clean high-priority",
}

POST_LLM_SUBTIER_FLAGS = list(POST_LLM_SUBTIER_LABELS)


def _truthy(series: pd.Series) -> pd.Series:
    cleaned = series.astype(str).str.strip().str.lower()
    return cleaned.isin({"1", "1.0", "true", "yes", "y"})


def _numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _clean(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip()


def _ensure_columns(df: pd.DataFrame, defaults: dict[str, object]) -> None:
    for col, default in defaults.items():
        if col not in df.columns:
            df[col] = default


def _prior_quarter(value: object) -> str:
    match = re.fullmatch(r"(\d{4})Q([1-4])", str(value or "").strip())
    if not match:
        return ""
    year = int(match.group(1))
    quarter = int(match.group(2))
    if quarter == 1:
        return f"{year - 1}Q4"
    return f"{year}Q{quarter - 1}"


def _prior_score_addition(df: pd.DataFrame) -> pd.Series:
    if "ticker" not in df.columns or "quarter" not in df.columns:
        return pd.Series([pd.NA] * len(df), index=df.index)
    score_by_key = {
        (str(ticker).upper(), str(quarter)): score
        for ticker, quarter, score in zip(
            df["ticker"],
            df["quarter"],
            _numeric(df["score_addition"]),
            strict=False,
        )
    }
    values = [
        score_by_key.get((str(ticker).upper(), _prior_quarter(quarter)), pd.NA)
        for ticker, quarter in zip(df["ticker"], df["quarter"], strict=False)
    ]
    return pd.Series(values, index=df.index)


def add_post_llm_subtiers(df: pd.DataFrame) -> pd.DataFrame:
    """Recompute formula-clean post-LLM subtier flags.

    This intentionally overwrites carried legacy flags so reports and filters use
    the live framework formulas instead of stale scoped-tier labels.
    """
    df = df.copy()
    _ensure_columns(
        df,
        {
            "tier_1_bucket": "",
            "tier_2_bucket": "",
            "tier_3_bucket": "",
            "tier_4_bucket": "",
            "post_llm_candidate_flag": 0,
            "post_llm_high_priority_flag": 0,
            "causal_change": pd.NA,
            "negative_revision_risk": pd.NA,
            "narrative_delta_bucket": "",
            "score_addition": pd.NA,
        },
    )

    tier1 = _clean(df["tier_1_bucket"]).ne("")
    tier2 = _clean(df["tier_2_bucket"]).ne("")
    tier3 = _clean(df["tier_3_bucket"]).ne("")
    tier4 = _clean(df["tier_4_bucket"]).ne("")
    candidate = _truthy(df["post_llm_candidate_flag"])
    high_priority = _truthy(df["post_llm_high_priority_flag"])
    causal3 = _numeric(df["causal_change"]).eq(3)
    neg_ok = _numeric(df["negative_revision_risk"]).le(2)
    inflecting = _clean(df["narrative_delta_bucket"]).str.lower().eq("inflecting")
    score_addition = _numeric(df["score_addition"])
    prior_addition = _numeric(_prior_score_addition(df))

    formulas = {
        "post_llm_tier_1_1_flag": tier1 & candidate,
        "post_llm_tier_1_2_flag": tier1 & causal3,
        "post_llm_tier_1_3_flag": tier1 & candidate & causal3 & neg_ok,
        "post_llm_tier_1_4_flag": tier1 & high_priority,
        "post_llm_tier_2_1_flag": tier2 & candidate,
        "post_llm_tier_2_2_flag": tier2 & causal3,
        "post_llm_tier_2_3_flag": tier2 & candidate & causal3 & neg_ok,
        "post_llm_tier_3_1_flag": tier3 & candidate,
        "post_llm_tier_3_2_flag": tier3 & inflecting,
        "post_llm_tier_3_3_flag": tier3 & score_addition.gt(0) & prior_addition.gt(0),
        "post_llm_tier_3_4_flag": tier3 & high_priority & prior_addition.gt(0),
        "post_llm_tier_4_1_flag": tier4 & candidate,
        "post_llm_tier_4_2_flag": tier4 & causal3,
        "post_llm_tier_4_3_flag": tier4 & candidate & causal3 & neg_ok,
    }
    for flag, formula in formulas.items():
        df[flag] = formula.fillna(False).astype(int)

    labels: list[str] = []
    for _, row in df[POST_LLM_SUBTIER_FLAGS].iterrows():
        labels.append(
            ";".join(
                POST_LLM_SUBTIER_LABELS[flag]
                for flag in POST_LLM_SUBTIER_FLAGS
                if int(row.get(flag, 0) or 0) == 1
            )
        )
    df["post_llm_sub_tier_bucket"] = labels
    return df
