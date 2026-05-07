"""Contribution report helpers for dealflow shortlist artifacts."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from .contracts import DealFlowShortlist
from .scoring import CORE_SCORE_WEIGHTS


def build_family_contribution_report(
    shortlist: DealFlowShortlist,
    *,
    core_contributions_fn: Callable[[Dict[str, float]], Dict[str, float]] | None = None,
    aggregate_contributions_fn: Callable[[List[Dict[str, Any]], Optional[str]], Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    """Build per-candidate and aggregate score contribution report."""
    core_fn = core_contributions_fn or core_contributions
    aggregate_fn = aggregate_contributions_fn or aggregate_contributions
    candidates = shortlist.get("candidates", [])
    rows: List[Dict[str, Any]] = []

    for candidate in candidates:
        subs = dict(candidate.get("subscores", {}))
        core_contrib = core_fn(subs)
        momentum_contrib = {
            "price_momentum": float(round(0.60 * float(subs.get("price_momentum", 50.0)), 4)),
            "social_momentum": float(round(0.30 * float(subs.get("social_momentum", 50.0)), 4)),
            "news_catalyst": float(round(0.10 * float(subs.get("news_catalyst", 50.0)), 4)),
        }
        momentum_score = float(candidate.get("momentum_score", 0.0))
        asymmetry_contrib = {
            "momentum_score": float(round(0.70 * momentum_score, 4)),
            "macro_regime_fit": float(round(0.10 * float(subs.get("macro_regime_fit", 50.0)), 4)),
            "smart_money": float(round(0.10 * float(subs.get("smart_money", 50.0)), 4)),
            "liquidity_tradability": float(round(0.10 * float(subs.get("liquidity_tradability", 50.0)), 4)),
        }
        rows.append(
            {
                "symbol": candidate.get("symbol"),
                "rank": candidate.get("rank"),
                "lane": candidate.get("lane"),
                "core_score": float(candidate.get("core_score", candidate.get("deal_flow_score", 0.0))),
                "momentum_score": momentum_score,
                "asymmetry_score": float(candidate.get("asymmetry_score", 0.0)),
                "core_contributions": core_contrib,
                "momentum_contributions": momentum_contrib,
                "asymmetry_contributions": asymmetry_contrib,
            }
        )

    return {
        "run_id": shortlist.get("run_id"),
        "date": shortlist.get("date"),
        "core_weight_model": dict(CORE_SCORE_WEIGHTS),
        "momentum_weight_model": {"price_momentum": 0.60, "social_momentum": 0.30, "news_catalyst": 0.10},
        "asymmetry_weight_model": {
            "momentum_score": 0.70,
            "macro_regime_fit": 0.10,
            "smart_money": 0.10,
            "liquidity_tradability": 0.10,
        },
        "candidates": rows,
        "aggregate": {
            "ALL": aggregate_fn(rows, None),
            "CORE": aggregate_fn(rows, "CORE"),
            "MOMENTUM": aggregate_fn(rows, "MOMENTUM"),
        },
    }


def aggregate_contributions(rows: List[Dict[str, Any]], lane: Optional[str]) -> Dict[str, Any]:
    selected = rows if lane is None else [r for r in rows if str(r.get("lane")) == lane]
    if not selected:
        return {
            "count": 0,
            "avg_core_contributions": {},
            "avg_momentum_contributions": {},
            "avg_asymmetry_contributions": {},
        }
    return {
        "count": len(selected),
        "avg_core_contributions": average_nested(selected, "core_contributions"),
        "avg_momentum_contributions": average_nested(selected, "momentum_contributions"),
        "avg_asymmetry_contributions": average_nested(selected, "asymmetry_contributions"),
    }


def average_nested(rows: List[Dict[str, Any]], field: str) -> Dict[str, float]:
    totals: Dict[str, float] = {}
    for row in rows:
        data = row.get(field, {}) or {}
        for key, value in data.items():
            totals[key] = totals.get(key, 0.0) + float(value)
    return {k: float(round(v / float(len(rows)), 4)) for k, v in totals.items()}


def core_contributions(subscores: Dict[str, float]) -> Dict[str, float]:
    weighted_parts: List[tuple[str, float, float]] = []
    for family, weight in CORE_SCORE_WEIGHTS.items():
        score = subscores.get(family)
        if score is None:
            continue
        weighted_parts.append((family, float(weight), float(score)))

    total_weight = sum(weight for _, weight, _ in weighted_parts)
    if total_weight <= 0:
        return {}
    return {
        family: float(round((weight * score) / total_weight, 4))
        for family, weight, score in weighted_parts
    }
