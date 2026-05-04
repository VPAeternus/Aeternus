"""Macro-on vs macro-neutral dealflow ablation.

The experiment keeps the candidate universe fixed and changes only the
`macro_regime_fit` subscore to a neutral constant in the neutral scenario.
"""

from __future__ import annotations

from typing import Any, Mapping

import pandas as pd

from tradingagents.dealflow.ranking import rank_candidates
from tradingagents.dealflow.scoring import (
    _apply_sector_override,
    _asymmetry_score,
    _assign_lane,
    _momentum_score,
    _weighted_core_score,
)


def run_macro_ablation(
    candidates: pd.DataFrame,
    *,
    forward_return_col: str,
    top_k: int = 20,
    neutral_macro_score: float = 50.0,
    date_col: str = "date",
    symbol_col: str = "symbol",
    subscores_col: str = "subscores",
) -> dict[str, pd.DataFrame]:
    """Rank candidates with macro on and macro neutralized.

    Args:
        candidates: Candidate rows with date, symbol, subscores, and forward return.
        forward_return_col: Column used to evaluate selected names.
        top_k: Per-date top-k to summarize.
        neutral_macro_score: Replacement macro score for neutral scenario.
    """
    required = {date_col, symbol_col, subscores_col, forward_return_col}
    missing = required - set(candidates.columns)
    if missing:
        raise ValueError(f"candidates missing columns: {sorted(missing)}")

    ranked_frames = []
    selected_frames = []
    for scenario in ("macro_on", "macro_neutral"):
        scenario_rows = []
        selected_rows = []
        for _, group in candidates.groupby(date_col, sort=True):
            production_candidates = []
            row_by_symbol = {}
            for source_idx, row in group.reset_index(drop=True).iterrows():
                cand = _recompute_candidate(
                    row=row,
                    scenario=scenario,
                    neutral_macro_score=neutral_macro_score,
                    symbol_col=symbol_col,
                    subscores_col=subscores_col,
                )
                # Stable uniqueness even if a fixture has blank/duplicate symbols.
                key = str(cand.get("symbol") or f"__row_{source_idx}")
                row_by_symbol[key] = row.to_dict()
                production_candidates.append(cand)

            ranked_all = rank_candidates(production_candidates, top_k=len(production_candidates))
            ranked_top = rank_candidates(production_candidates, top_k=int(top_k))
            scenario_rows.extend(_merge_ranked_rows(ranked_all, row_by_symbol, scenario, forward_return_col))
            selected_rows.extend(_merge_ranked_rows(ranked_top, row_by_symbol, scenario, forward_return_col))
        ranked_frames.append(pd.DataFrame(scenario_rows))
        selected_frames.append(pd.DataFrame(selected_rows))

    ranked = pd.concat(ranked_frames, ignore_index=True) if ranked_frames else pd.DataFrame()
    selected = pd.concat(selected_frames, ignore_index=True) if selected_frames else pd.DataFrame()
    summary = _summarize(selected, forward_return_col)
    return {"ranked": ranked, "selected": selected, "summary": summary}


def _recompute_candidate(
    *,
    row: pd.Series,
    scenario: str,
    neutral_macro_score: float,
    symbol_col: str,
    subscores_col: str,
) -> dict[str, Any]:
    subscores = _coerce_subscores(row.get(subscores_col))
    if scenario == "macro_neutral":
        subscores["macro_regime_fit"] = float(neutral_macro_score)

    sector = str(row.get("sector", "Unknown") or "Unknown")
    core_score = _apply_sector_override(_weighted_core_score(subscores), sector)
    momentum_score = _momentum_score(subscores)
    asymmetry_score = _asymmetry_score(subscores, momentum_score)
    trend_tags = row.get("trend_tags") if isinstance(row.get("trend_tags"), list) else []
    lane = _assign_lane(
        subscores=subscores,
        trend_tags=trend_tags,
        momentum_score=momentum_score,
        momentum_lane_threshold=70.0,
        momentum_lane_price_override_threshold=82.0,
        momentum_lane_social_confirmation_threshold=60.0,
    )

    return {
        "symbol": str(row.get(symbol_col, "") or ""),
        "asset_class": row.get("asset_class", "Equity"),
        "sector": sector,
        "subscores": subscores,
        "status": row.get("status", "ACTIVE") or "ACTIVE",
        "lane": lane,
        "core_score": float(core_score),
        "momentum_score": float(momentum_score),
        "asymmetry_score": float(asymmetry_score),
        "freshness_hours": float(row.get("freshness_hours", 9999.0) or 9999.0),
        "macro_regime_fit": float(subscores.get("macro_regime_fit", neutral_macro_score)),
    }


def _merge_ranked_rows(
    ranked_candidates: list[dict[str, Any]],
    row_by_symbol: dict[str, dict[str, Any]],
    scenario: str,
    forward_return_col: str,
) -> list[dict[str, Any]]:
    rows = []
    for candidate in ranked_candidates:
        symbol = str(candidate.get("symbol", ""))
        source = dict(row_by_symbol.get(symbol, {}))
        source.update(
            {
                "scenario": scenario,
                "rank": int(candidate.get("rank", 0)),
                "macro_regime_fit": float(candidate.get("macro_regime_fit", 50.0)),
                "core_score": float(candidate.get("core_score", 0.0)),
                "momentum_score": float(candidate.get("momentum_score", 0.0)),
                "asymmetry_score": float(candidate.get("asymmetry_score", 0.0)),
                "lane": candidate.get("lane", source.get("lane", "CORE")),
            }
        )
        # Preserve the requested return column even when original row omitted it as NaN.
        source.setdefault(forward_return_col, float("nan"))
        rows.append(source)
    return rows


def _coerce_subscores(value: Any) -> dict[str, float]:
    if not isinstance(value, Mapping):
        return {}
    out = {}
    for key, raw in value.items():
        try:
            out[str(key)] = float(raw)
        except (TypeError, ValueError):
            continue
    return out


def _summarize(selected: pd.DataFrame, forward_return_col: str) -> pd.DataFrame:
    rows = []
    for scenario, frame in selected.groupby("scenario"):
        returns = frame[forward_return_col].dropna().astype(float)
        rows.append(
            {
                "scenario": scenario,
                "selected_count": int(len(frame)),
                "return_count": int(returns.count()),
                "mean_return": float(returns.mean()) if not returns.empty else float("nan"),
                "median_return": float(returns.median()) if not returns.empty else float("nan"),
                "hit_rate": float((returns > 0).mean()) if not returns.empty else float("nan"),
            }
        )
    return pd.DataFrame(rows)
