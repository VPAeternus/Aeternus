"""Signal-family ablation analysis for evidence packs."""

from __future__ import annotations

import datetime as dt
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

FAMILY_ORDER: List[str] = [
    "social_momentum",
    "price_momentum",
    "macro_regime_fit",
    "news_catalyst",
    "smart_money",
    "liquidity_tradability",
]

BASE_WEIGHTS: Dict[str, float] = {
    "social_momentum": 15.0,
    "price_momentum": 25.0,
    "macro_regime_fit": 20.0,
    "news_catalyst": 15.0,
    "smart_money": 15.0,
    "liquidity_tradability": 5.0,
}


def build_ablation_report(
    items_by_date: Dict[str, List[Dict[str, Any]]],
    deep_k: int = 8,
    families: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    family_list = [str(family) for family in (families or FAMILY_ORDER)]
    deep_k = max(1, int(deep_k))

    per_family_deltas: Dict[str, List[Dict[str, Any]]] = {family: [] for family in family_list}

    for date_key, rows in sorted(items_by_date.items(), key=lambda kv: kv[0]):
        candidates = [row for row in rows if _valid_candidate(row)]
        if not candidates:
            continue

        baseline_selected = _select_top(candidates, BASE_WEIGHTS, deep_k=deep_k)
        baseline_symbols = {str(row.get("symbol", "")).upper() for row in baseline_selected}
        baseline_stats_5 = _selection_horizon_stats(baseline_selected, "5d")
        baseline_stats_20 = _selection_horizon_stats(baseline_selected, "20d")
        baseline_lane_mix = _lane_mix(baseline_selected)

        for family in family_list:
            ablated_weights = {key: value for key, value in BASE_WEIGHTS.items() if key != family}
            ablated_selected = _select_top(candidates, ablated_weights, deep_k=deep_k)
            ablated_symbols = {str(row.get("symbol", "")).upper() for row in ablated_selected}

            common = baseline_symbols & ablated_symbols
            baseline_count = max(1, len(baseline_selected))
            turnover = 1.0 - (float(len(common)) / float(baseline_count))

            ablated_stats_5 = _selection_horizon_stats(ablated_selected, "5d")
            ablated_stats_20 = _selection_horizon_stats(ablated_selected, "20d")
            ablated_lane_mix = _lane_mix(ablated_selected)

            per_family_deltas[family].append(
                {
                    "date": date_key,
                    "selection_turnover": round(turnover, 6),
                    "edge_delta_5d_pct": _delta(ablated_stats_5.get("avg_strategy_edge_pct"), baseline_stats_5.get("avg_strategy_edge_pct")),
                    "edge_delta_20d_pct": _delta(ablated_stats_20.get("avg_strategy_edge_pct"), baseline_stats_20.get("avg_strategy_edge_pct")),
                    "win_rate_delta_5d": _delta(ablated_stats_5.get("strategy_edge_win_rate"), baseline_stats_5.get("strategy_edge_win_rate")),
                    "win_rate_delta_20d": _delta(ablated_stats_20.get("strategy_edge_win_rate"), baseline_stats_20.get("strategy_edge_win_rate")),
                    "lane_mix_delta_core": _delta(ablated_lane_mix.get("CORE"), baseline_lane_mix.get("CORE")),
                    "lane_mix_delta_momentum": _delta(ablated_lane_mix.get("MOMENTUM"), baseline_lane_mix.get("MOMENTUM")),
                }
            )

    slices: List[Dict[str, Any]] = []
    for family in family_list:
        rows = per_family_deltas.get(family, [])
        slices.append(
            {
                "family": family,
                "runs_evaluated": len(rows),
                "avg_selection_turnover": _mean([row.get("selection_turnover") for row in rows], default=0.0),
                "avg_edge_delta_5d_pct": _mean([row.get("edge_delta_5d_pct") for row in rows]),
                "avg_edge_delta_20d_pct": _mean([row.get("edge_delta_20d_pct") for row in rows]),
                "avg_win_rate_delta_5d": _mean([row.get("win_rate_delta_5d") for row in rows]),
                "avg_win_rate_delta_20d": _mean([row.get("win_rate_delta_20d") for row in rows]),
                "lane_mix_delta": {
                    "CORE": _mean([row.get("lane_mix_delta_core") for row in rows], default=0.0),
                    "MOMENTUM": _mean([row.get("lane_mix_delta_momentum") for row in rows], default=0.0),
                },
            }
        )

    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "families": slices,
        "family_count": len(slices),
        "runs_evaluated": len([d for d, rows in items_by_date.items() if rows]),
        "parameters": {
            "deep_k": deep_k,
            "base_weights": dict(BASE_WEIGHTS),
            "families": family_list,
        },
        "per_run": per_family_deltas,
    }


def _valid_candidate(row: Dict[str, Any]) -> bool:
    symbol = str(row.get("symbol", "")).strip()
    subscores = row.get("subscores")
    return bool(symbol) and isinstance(subscores, dict)


def _select_top(
    rows: Iterable[Dict[str, Any]],
    weights: Dict[str, float],
    deep_k: int,
) -> List[Dict[str, Any]]:
    scored: List[Tuple[float, Dict[str, Any]]] = []
    for row in rows:
        subscores = row.get("subscores")
        if not isinstance(subscores, dict):
            continue
        score = _weighted_score(subscores, weights)
        scored.append((score, row))

    scored.sort(
        key=lambda pair: (
            -float(pair[0]),
            str(pair[1].get("symbol", "")).upper(),
        )
    )
    limit = max(1, int(deep_k))
    return [row for _, row in scored[:limit]]


def _weighted_score(subscores: Dict[str, Any], weights: Dict[str, float]) -> float:
    numerator = 0.0
    denominator = 0.0
    for family, weight in weights.items():
        value = subscores.get(family)
        if not isinstance(value, (int, float)):
            continue
        numerator += float(weight) * float(value)
        denominator += float(weight)
    if denominator <= 0.0:
        return 0.0
    return numerator / denominator


def _selection_horizon_stats(rows: List[Dict[str, Any]], horizon_key: str) -> Dict[str, Optional[float]]:
    strategy_edges: List[float] = []
    for row in rows:
        horizons = row.get("realized_horizons")
        if not isinstance(horizons, dict):
            continue
        horizon = horizons.get(horizon_key)
        if not isinstance(horizon, dict):
            continue
        if str(horizon.get("status", "")).upper() != "READY":
            continue
        value = horizon.get("strategy_edge_vs_benchmark_pct")
        if isinstance(value, (int, float)):
            strategy_edges.append(float(value))

    if not strategy_edges:
        return {"avg_strategy_edge_pct": None, "strategy_edge_win_rate": None}

    win_rate = sum(1 for value in strategy_edges if value > 0.0) / float(len(strategy_edges))
    return {
        "avg_strategy_edge_pct": round(sum(strategy_edges) / len(strategy_edges), 6),
        "strategy_edge_win_rate": round(win_rate, 6),
    }


def _lane_mix(rows: List[Dict[str, Any]]) -> Dict[str, float]:
    if not rows:
        return {"CORE": 0.0, "MOMENTUM": 0.0}
    total = float(len(rows))
    core = sum(1 for row in rows if str(row.get("lane", "CORE")).upper() == "CORE")
    momentum = sum(1 for row in rows if str(row.get("lane", "CORE")).upper() == "MOMENTUM")
    return {
        "CORE": round(core / total, 6),
        "MOMENTUM": round(momentum / total, 6),
    }


def _mean(values: List[Any], default: Optional[float] = None) -> Optional[float]:
    clean = [float(value) for value in values if isinstance(value, (int, float))]
    if not clean:
        return default
    return round(sum(clean) / len(clean), 6)


def _delta(lhs: Optional[float], rhs: Optional[float]) -> Optional[float]:
    if lhs is None or rhs is None:
        return None
    return round(float(lhs) - float(rhs), 6)
