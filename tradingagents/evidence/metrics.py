"""Metrics and attribution utilities for evidence packs."""

from __future__ import annotations

import math
from statistics import mean, pstdev
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from .contracts import MetricSet


def build_metric_set(
    items: Iterable[Dict[str, Any]],
    risk_free_annual_by_date: Optional[Dict[str, float]] = None,
) -> MetricSet:
    rows = list(items)
    success_rows = [row for row in rows if str(row.get("status", "")).upper().startswith("SUCCESS")]

    horizon_5 = _extract_horizon_rows(success_rows, "5d")
    horizon_20 = _extract_horizon_rows(success_rows, "20d")

    strategy_returns_5 = [entry["strategy_return_pct"] for entry in horizon_5 if entry["strategy_return_pct"] is not None]
    strategy_returns_20 = [entry["strategy_return_pct"] for entry in horizon_20 if entry["strategy_return_pct"] is not None]
    rf_values_5 = [
        _risk_free_pct_for_date(risk_free_annual_by_date, entry["date"])
        for entry in horizon_5
        if entry["strategy_return_pct"] is not None
    ]
    rf_values_20 = [
        _risk_free_pct_for_date(risk_free_annual_by_date, entry["date"])
        for entry in horizon_20
        if entry["strategy_return_pct"] is not None
    ]

    metric_set: MetricSet = {
        "count": len(rows),
        "success_count": len(success_rows),
        "failure_count": sum(1 for row in rows if str(row.get("status", "")).upper() == "FAILED"),
        "skipped_count": sum(1 for row in rows if str(row.get("status", "")).upper() == "SKIPPED"),
        "evaluated_5d": len(horizon_5),
        "evaluated_20d": len(horizon_20),
        "avg_return_5d_pct": _mean_or_none([entry["return_pct"] for entry in horizon_5]),
        "avg_return_20d_pct": _mean_or_none([entry["return_pct"] for entry in horizon_20]),
        "avg_benchmark_return_5d_pct": _mean_or_none([entry["benchmark_return_pct"] for entry in horizon_5]),
        "avg_benchmark_return_20d_pct": _mean_or_none([entry["benchmark_return_pct"] for entry in horizon_20]),
        "avg_edge_5d_pct": _mean_or_none([entry["edge_vs_benchmark_pct"] for entry in horizon_5]),
        "avg_edge_20d_pct": _mean_or_none([entry["edge_vs_benchmark_pct"] for entry in horizon_20]),
        "edge_win_rate_5d": _win_rate_or_none([entry["edge_vs_benchmark_pct"] for entry in horizon_5]),
        "edge_win_rate_20d": _win_rate_or_none([entry["edge_vs_benchmark_pct"] for entry in horizon_20]),
        "avg_strategy_return_5d_pct": _mean_or_none(strategy_returns_5),
        "avg_strategy_return_20d_pct": _mean_or_none(strategy_returns_20),
        "avg_strategy_edge_5d_pct": _mean_or_none([entry["strategy_edge_vs_benchmark_pct"] for entry in horizon_5]),
        "avg_strategy_edge_20d_pct": _mean_or_none([entry["strategy_edge_vs_benchmark_pct"] for entry in horizon_20]),
        "strategy_edge_win_rate_5d": _win_rate_or_none([entry["strategy_edge_vs_benchmark_pct"] for entry in horizon_5]),
        "strategy_edge_win_rate_20d": _win_rate_or_none([entry["strategy_edge_vs_benchmark_pct"] for entry in horizon_20]),
        "edge_win_rate_5d_p": _win_rate_p_value([entry["edge_vs_benchmark_pct"] for entry in horizon_5]),
        "edge_win_rate_20d_p": _win_rate_p_value([entry["edge_vs_benchmark_pct"] for entry in horizon_20]),
        "strategy_edge_win_rate_5d_p": _win_rate_p_value([entry["strategy_edge_vs_benchmark_pct"] for entry in horizon_5]),
        "strategy_edge_win_rate_20d_p": _win_rate_p_value([entry["strategy_edge_vs_benchmark_pct"] for entry in horizon_20]),
        "sharpe_5d": _annualized_sharpe(strategy_returns_5, horizon_days=5, risk_free_annual_pct=rf_values_5),
        "sharpe_20d": _annualized_sharpe(strategy_returns_20, horizon_days=20, risk_free_annual_pct=rf_values_20),
    }
    return metric_set


def group_metric_sets(
    items: Iterable[Dict[str, Any]],
    key_fn: Callable[[Dict[str, Any]], str],
    risk_free_annual_by_date: Optional[Dict[str, float]] = None,
) -> Dict[str, MetricSet]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for row in items:
        key = str(key_fn(row) or "UNKNOWN")
        grouped.setdefault(key, []).append(row)

    return {
        key: build_metric_set(rows, risk_free_annual_by_date=risk_free_annual_by_date)
        for key, rows in sorted(grouped.items(), key=lambda kv: kv[0])
    }


def build_lane_playbook_rows(
    items: Iterable[Dict[str, Any]],
    risk_free_annual_by_date: Optional[Dict[str, float]] = None,
) -> List[Dict[str, Any]]:
    grouped: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for row in items:
        lane = str(row.get("lane", "UNKNOWN")).upper()
        playbook = str(row.get("research_playbook", "UNKNOWN"))
        grouped.setdefault((lane, playbook), []).append(row)

    output: List[Dict[str, Any]] = []
    for (lane, playbook), rows in sorted(grouped.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        metrics = build_metric_set(rows, risk_free_annual_by_date=risk_free_annual_by_date)
        output.append(
            {
                "lane": lane,
                "playbook": playbook,
                **metrics,
            }
        )
    return output


def build_regime_rows(
    items: Iterable[Dict[str, Any]],
    risk_free_annual_by_date: Optional[Dict[str, float]] = None,
) -> List[Dict[str, Any]]:
    grouped = group_metric_sets(
        items,
        key_fn=lambda row: str(row.get("regime", "UNKNOWN")),
        risk_free_annual_by_date=risk_free_annual_by_date,
    )
    return [{"regime": regime, **metrics} for regime, metrics in grouped.items()]


def _extract_horizon_rows(
    rows: List[Dict[str, Any]],
    horizon_key: str,
) -> List[Dict[str, Optional[float]]]:
    extracted: List[Dict[str, Optional[float]]] = []
    for row in rows:
        realized = row.get("realized_horizons")
        if not isinstance(realized, dict):
            continue
        horizon = realized.get(horizon_key)
        if not isinstance(horizon, dict):
            continue
        if str(horizon.get("status", "")).upper() != "READY":
            continue
        extracted.append(
            {
                "date": str(row.get("date", "")),
                "return_pct": _safe_float(horizon.get("return_pct")),
                "benchmark_return_pct": _safe_float(horizon.get("benchmark_return_pct")),
                "edge_vs_benchmark_pct": _safe_float(horizon.get("edge_vs_benchmark_pct")),
                "strategy_return_pct": _safe_float(horizon.get("strategy_return_pct")),
                "strategy_edge_vs_benchmark_pct": _safe_float(horizon.get("strategy_edge_vs_benchmark_pct")),
            }
        )
    return extracted


def _annualized_sharpe(
    returns_pct: List[Optional[float]],
    horizon_days: int,
    risk_free_annual_pct: Optional[List[float]] = None,
) -> Optional[float]:
    cleaned_returns = [float(value) for value in returns_pct if isinstance(value, (int, float))]
    if not cleaned_returns:
        return None

    rf_values = list(risk_free_annual_pct or [])
    if len(rf_values) < len(cleaned_returns):
        rf_values.extend([0.0] * (len(cleaned_returns) - len(rf_values)))
    rf_values = rf_values[: len(cleaned_returns)]

    daily_excess: List[float] = []
    for idx, pct_return in enumerate(cleaned_returns):
        daily_ret = (pct_return / 100.0) / float(max(1, horizon_days))
        rf_daily = (float(rf_values[idx]) / 100.0) / 252.0
        daily_excess.append(daily_ret - rf_daily)

    sigma = pstdev(daily_excess)
    if sigma <= 0.0:
        return None
    sharpe = (mean(daily_excess) / sigma) * math.sqrt(252.0)
    return round(float(sharpe), 6)


def _risk_free_pct_for_date(series: Optional[Dict[str, float]], date_key: str) -> float:
    if not isinstance(series, dict):
        return 0.0
    value = series.get(str(date_key))
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _mean_or_none(values: List[Optional[float]]) -> Optional[float]:
    clean = [float(v) for v in values if isinstance(v, (int, float))]
    if not clean:
        return None
    return round(sum(clean) / len(clean), 6)


def _win_rate_or_none(values: List[Optional[float]]) -> Optional[float]:
    clean = [float(v) for v in values if isinstance(v, (int, float))]
    if not clean:
        return None
    return round(sum(1.0 for value in clean if value > 0.0) / float(len(clean)), 6)


def _win_rate_p_value(values: List[Optional[float]]) -> Optional[float]:
    """Binomial test: is win rate significantly > 50%? Returns p-value or None."""
    clean = [float(v) for v in values if isinstance(v, (int, float))]
    if not clean:
        return None
    wins = sum(1 for v in clean if v > 0.0)
    from scipy.stats import binomtest
    return round(binomtest(wins, len(clean), 0.5, alternative="greater").pvalue, 6)
