"""Cost/alpha telemetry and feature-family dashboard builders."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from .ablation import BASE_WEIGHTS


SOURCE_FAMILY_MAP_DEFAULT: Dict[str, Tuple[str, ...]] = {
    # X feed scout effect on social momentum lane.
    "x": ("social_momentum",),
    # Web/news vendor signal path from blended social connector.
    "news_vendors": ("news_catalyst",),
    # Macro feed contribution to regime-fit family.
    "macro_feed": ("macro_regime_fit",),
}


def build_cost_alpha_telemetry(
    summaries: Sequence[Dict[str, Any]],
    from_date: str,
    to_date: str,
    x_cost_per_api_call_usd: float = 1.0,
    dealflow_base_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    base_dir = Path(dealflow_base_dir or (Path("eval_results") / "deal_flow"))
    cost_per_call = max(0.0, _safe_float(x_cost_per_api_call_usd) or 0.0)
    ordered = sorted(
        [row for row in summaries if isinstance(row, dict)],
        key=lambda row: str(row.get("date", "")),
    )

    totals = {
        "processed": 0,
        "success_count": 0,
        "failure_count": 0,
        "skipped_count": 0,
        "estimated_x_api_calls": 0,
        "estimated_x_cost_usd": 0.0,
    }
    overall_horizons = {"5d": _new_horizon_agg(), "20d": _new_horizon_agg()}
    family_aggs: Dict[str, Dict[str, Any]] = {}
    total_signal_count = 0
    per_day = []

    for summary in ordered:
        date_key = str(summary.get("date", "")).strip()
        if not date_key:
            continue

        processed = max(0, _safe_int(summary.get("processed")))
        success_count = max(0, _safe_int(summary.get("success_count")))
        failure_count = max(0, _safe_int(summary.get("failure_count")))
        skipped_count = max(0, _safe_int(summary.get("skipped_count")))
        analysis_mode_counts = summary.get("analysis_mode_counts")
        if not isinstance(analysis_mode_counts, dict):
            analysis_mode_counts = {}

        totals["processed"] += processed
        totals["success_count"] += success_count
        totals["failure_count"] += failure_count
        totals["skipped_count"] += skipped_count

        x_scope = _load_x_scope_for_date(base_dir=base_dir, date_key=date_key)
        x_calls = _estimate_x_api_calls(x_scope)
        x_cost = round(float(x_calls) * cost_per_call, 6)
        totals["estimated_x_api_calls"] += int(x_calls)
        totals["estimated_x_cost_usd"] += float(x_cost)

        attribution = summary.get("attribution")
        if not isinstance(attribution, dict):
            attribution = {}

        overall = attribution.get("overall")
        if not isinstance(overall, dict):
            overall = {}
        overall_day = {
            "5d": _extract_horizon_metrics(overall, "5d"),
            "20d": _extract_horizon_metrics(overall, "20d"),
        }
        _accumulate_horizon(overall_horizons["5d"], overall_day["5d"])
        _accumulate_horizon(overall_horizons["20d"], overall_day["20d"])

        by_family = attribution.get("by_signal_family")
        if not isinstance(by_family, dict):
            by_family = {}
        signal_counts = attribution.get("signal_family_counts")
        if not isinstance(signal_counts, dict):
            signal_counts = {}

        families = sorted(set(by_family.keys()) | set(signal_counts.keys()))
        daily_counts = {
            family: max(
                0,
                _safe_int(signal_counts.get(family))
                or _safe_int((by_family.get(family) or {}).get("count")),
            )
            for family in families
        }
        daily_total_signals = sum(daily_counts.values())
        total_signal_count += int(daily_total_signals)

        for family in families:
            fam_entry = family_aggs.setdefault(
                str(family),
                {
                    "signal_count": 0,
                    "allocated_cost_usd": 0.0,
                    "horizons": {"5d": _new_horizon_agg(), "20d": _new_horizon_agg()},
                },
            )
            family_count = int(daily_counts.get(family, 0))
            fam_entry["signal_count"] += family_count

            if daily_total_signals > 0 and x_cost > 0.0:
                fam_entry["allocated_cost_usd"] += float(x_cost) * (
                    float(family_count) / float(daily_total_signals)
                )

            family_block = by_family.get(family)
            if not isinstance(family_block, dict):
                family_block = {}
            _accumulate_horizon(
                fam_entry["horizons"]["5d"],
                _extract_horizon_metrics(family_block, "5d"),
            )
            _accumulate_horizon(
                fam_entry["horizons"]["20d"],
                _extract_horizon_metrics(family_block, "20d"),
            )

        per_day.append(
            {
                "date": date_key,
                "run_id": str(summary.get("run_id", "")),
                "processed": processed,
                "success_count": success_count,
                "failure_count": failure_count,
                "skipped_count": skipped_count,
                "analysis_mode_counts": dict(sorted(analysis_mode_counts.items(), key=lambda kv: kv[0])),
                "x_scope": x_scope,
                "estimated_x_api_calls": int(x_calls),
                "estimated_x_cost_usd": float(x_cost),
                "alpha": overall_day,
            }
        )

    totals["estimated_x_cost_usd"] = round(float(totals["estimated_x_cost_usd"]), 6)
    alpha_5d = _finalize_horizon(overall_horizons["5d"])
    alpha_20d = _finalize_horizon(overall_horizons["20d"])
    efficiency = {
        "5d_edge_bps_per_usd": _edge_bps_per_usd(
            edge_pct=alpha_5d.get("avg_strategy_edge_vs_benchmark_pct"),
            cost_usd=totals["estimated_x_cost_usd"],
        ),
        "20d_edge_bps_per_usd": _edge_bps_per_usd(
            edge_pct=alpha_20d.get("avg_strategy_edge_vs_benchmark_pct"),
            cost_usd=totals["estimated_x_cost_usd"],
        ),
    }

    by_signal_family: Dict[str, Any] = {}
    for family in sorted(family_aggs.keys()):
        family_row = family_aggs[family]
        allocated_cost = round(float(family_row.get("allocated_cost_usd", 0.0)), 6)
        signal_count = int(family_row.get("signal_count", 0) or 0)
        signal_share = round(
            float(signal_count) / float(total_signal_count),
            6,
        ) if total_signal_count > 0 else 0.0

        horizon_5d = _finalize_horizon((family_row.get("horizons") or {}).get("5d", {}))
        horizon_20d = _finalize_horizon((family_row.get("horizons") or {}).get("20d", {}))
        by_signal_family[family] = {
            "signal_count": signal_count,
            "signal_share": signal_share,
            "allocated_cost_usd": allocated_cost,
            "horizons": {
                "5d": horizon_5d,
                "20d": horizon_20d,
            },
            "efficiency": {
                "5d_edge_bps_per_usd": _edge_bps_per_usd(
                    edge_pct=horizon_5d.get("avg_strategy_edge_vs_benchmark_pct"),
                    cost_usd=allocated_cost,
                ),
                "20d_edge_bps_per_usd": _edge_bps_per_usd(
                    edge_pct=horizon_20d.get("avg_strategy_edge_vs_benchmark_pct"),
                    cost_usd=allocated_cost,
                ),
            },
        }

    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "from_date": str(from_date),
        "to_date": str(to_date),
        "sample_days": len(per_day),
        "cost_model": {
            "x_cost_per_api_call_usd": float(cost_per_call),
            "x_call_estimator": "DIRECT_ONLY=symbol_calls;SCOUT_ONLY=handles;HYBRID=handles+symbol_calls",
        },
        "totals": totals,
        "alpha": {
            "5d": alpha_5d,
            "20d": alpha_20d,
        },
        "efficiency": efficiency,
        "by_signal_family": by_signal_family,
        "per_day": per_day,
    }


def build_feature_family_dashboard(
    telemetry: Dict[str, Any],
    ablation_report: Dict[str, Any],
) -> Dict[str, Any]:
    family_telemetry = telemetry.get("by_signal_family")
    if not isinstance(family_telemetry, dict):
        family_telemetry = {}

    ablation_rows = {}
    for row in ablation_report.get("families", []) if isinstance(ablation_report, dict) else []:
        if not isinstance(row, dict):
            continue
        family = str(row.get("family", "")).strip()
        if family:
            ablation_rows[family] = row

    families = sorted(set(family_telemetry.keys()) | set(ablation_rows.keys()))
    rows = []
    for family in families:
        telemetry_row = family_telemetry.get(family)
        if not isinstance(telemetry_row, dict):
            telemetry_row = {}
        ablation_row = ablation_rows.get(family)
        if not isinstance(ablation_row, dict):
            ablation_row = {}

        horizons = telemetry_row.get("horizons")
        if not isinstance(horizons, dict):
            horizons = {}
        hz5 = horizons.get("5d")
        if not isinstance(hz5, dict):
            hz5 = {}
        hz20 = horizons.get("20d")
        if not isinstance(hz20, dict):
            hz20 = {}

        efficiency = telemetry_row.get("efficiency")
        if not isinstance(efficiency, dict):
            efficiency = {}

        signal_share = _safe_float(telemetry_row.get("signal_share")) or 0.0
        turnover = _safe_float(ablation_row.get("avg_selection_turnover")) or 0.0
        ablation_delta_5d = _safe_float(ablation_row.get("avg_edge_delta_5d_pct"))
        ablation_delta_20d = _safe_float(ablation_row.get("avg_edge_delta_20d_pct"))
        impact_5d = round(abs(ablation_delta_5d or 0.0) * (1.0 + turnover), 6)
        impact_20d = round(abs(ablation_delta_20d or 0.0) * (1.0 + turnover), 6)
        composite_priority = round((impact_20d * 2.0 + impact_5d) * max(signal_share, 0.01), 6)

        rows.append(
            {
                "family": family,
                "signal_count": max(0, _safe_int(telemetry_row.get("signal_count"))),
                "signal_share": round(signal_share, 6),
                "allocated_cost_usd": round(_safe_float(telemetry_row.get("allocated_cost_usd")) or 0.0, 6),
                "alpha_edge_5d_pct": _safe_float(hz5.get("avg_strategy_edge_vs_benchmark_pct")),
                "alpha_edge_20d_pct": _safe_float(hz20.get("avg_strategy_edge_vs_benchmark_pct")),
                "alpha_win_rate_5d": _safe_float(hz5.get("strategy_edge_win_rate")),
                "alpha_win_rate_20d": _safe_float(hz20.get("strategy_edge_win_rate")),
                "efficiency_5d_edge_bps_per_usd": _safe_float(efficiency.get("5d_edge_bps_per_usd")),
                "efficiency_20d_edge_bps_per_usd": _safe_float(efficiency.get("20d_edge_bps_per_usd")),
                "ablation_runs_evaluated": max(0, _safe_int(ablation_row.get("runs_evaluated"))),
                "ablation_turnover": round(turnover, 6),
                "ablation_delta_5d_pct": ablation_delta_5d,
                "ablation_delta_20d_pct": ablation_delta_20d,
                "ablation_impact_5d": impact_5d,
                "ablation_impact_20d": impact_20d,
                "composite_priority": composite_priority,
            }
        )

    rows.sort(key=lambda row: (-float(row.get("composite_priority", 0.0)), str(row.get("family", ""))))
    for idx, row in enumerate(rows, start=1):
        row["rank"] = idx

    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "from_date": str(telemetry.get("from_date", "")),
        "to_date": str(telemetry.get("to_date", "")),
        "family_count": len(rows),
        "ranking_metric": "(abs(delta_20d)*2 + abs(delta_5d)) * max(signal_share, 0.01)",
        "rows": rows,
    }


def build_source_ablation_report(
    items_by_date: Dict[str, List[Dict[str, Any]]],
    from_date: str,
    to_date: str,
    dealflow_base_dir: Optional[Path] = None,
    deep_k: int = 8,
    source_family_map: Optional[Dict[str, Sequence[str]]] = None,
    x_cost_per_api_call_usd: float = 1.0,
    news_cost_per_run_usd: float = 0.0,
    macro_cost_per_run_usd: float = 0.0,
) -> Dict[str, Any]:
    base_dir = Path(dealflow_base_dir or (Path("eval_results") / "deal_flow"))
    deep_k = max(1, int(deep_k))

    normalized_map: Dict[str, Tuple[str, ...]] = {}
    for source, families in (source_family_map or SOURCE_FAMILY_MAP_DEFAULT).items():
        family_tuple = tuple(
            str(family).strip()
            for family in (families or [])
            if str(family).strip()
        )
        if family_tuple:
            normalized_map[str(source).strip()] = family_tuple
    if not normalized_map:
        normalized_map = dict(SOURCE_FAMILY_MAP_DEFAULT)

    per_source_deltas: Dict[str, List[Dict[str, Any]]] = {
        source: [] for source in sorted(normalized_map.keys())
    }

    for date_key, rows in sorted(items_by_date.items(), key=lambda kv: kv[0]):
        candidates = [row for row in rows if _valid_candidate(row)]
        if not candidates:
            continue

        baseline_selected = _select_top(candidates, BASE_WEIGHTS, deep_k=deep_k)
        baseline_symbols = {
            str(row.get("symbol", "")).upper()
            for row in baseline_selected
            if str(row.get("symbol", "")).strip()
        }
        baseline_stats_5 = _selection_horizon_stats(baseline_selected, "5d")
        baseline_stats_20 = _selection_horizon_stats(baseline_selected, "20d")
        baseline_lane_mix = _lane_mix(baseline_selected)

        for source, families in sorted(normalized_map.items(), key=lambda kv: kv[0]):
            families_removed: Set[str] = {str(family) for family in families}
            ablated_weights = {
                key: value
                for key, value in BASE_WEIGHTS.items()
                if key not in families_removed
            }
            if not ablated_weights:
                continue

            ablated_selected = _select_top(candidates, ablated_weights, deep_k=deep_k)
            ablated_symbols = {
                str(row.get("symbol", "")).upper()
                for row in ablated_selected
                if str(row.get("symbol", "")).strip()
            }

            common = baseline_symbols & ablated_symbols
            baseline_count = max(1, len(baseline_selected))
            turnover = 1.0 - (float(len(common)) / float(baseline_count))

            ablated_stats_5 = _selection_horizon_stats(ablated_selected, "5d")
            ablated_stats_20 = _selection_horizon_stats(ablated_selected, "20d")
            ablated_lane_mix = _lane_mix(ablated_selected)

            per_source_deltas[source].append(
                {
                    "date": str(date_key),
                    "selection_turnover": round(turnover, 6),
                    "edge_delta_5d_pct": _delta(
                        ablated_stats_5.get("avg_strategy_edge_pct"),
                        baseline_stats_5.get("avg_strategy_edge_pct"),
                    ),
                    "edge_delta_20d_pct": _delta(
                        ablated_stats_20.get("avg_strategy_edge_pct"),
                        baseline_stats_20.get("avg_strategy_edge_pct"),
                    ),
                    "win_rate_delta_5d": _delta(
                        ablated_stats_5.get("strategy_edge_win_rate"),
                        baseline_stats_5.get("strategy_edge_win_rate"),
                    ),
                    "win_rate_delta_20d": _delta(
                        ablated_stats_20.get("strategy_edge_win_rate"),
                        baseline_stats_20.get("strategy_edge_win_rate"),
                    ),
                    "lane_mix_delta_core": _delta(
                        ablated_lane_mix.get("CORE"),
                        baseline_lane_mix.get("CORE"),
                    ),
                    "lane_mix_delta_momentum": _delta(
                        ablated_lane_mix.get("MOMENTUM"),
                        baseline_lane_mix.get("MOMENTUM"),
                    ),
                }
            )

    source_costs, cost_model = _estimate_source_costs(
        base_dir=base_dir,
        dates=items_by_date.keys(),
        x_cost_per_api_call_usd=x_cost_per_api_call_usd,
        news_cost_per_run_usd=news_cost_per_run_usd,
        macro_cost_per_run_usd=macro_cost_per_run_usd,
    )

    source_rows: List[Dict[str, Any]] = []
    for source in sorted(normalized_map.keys()):
        rows = per_source_deltas.get(source, [])
        avg_edge_delta_5d = _mean([row.get("edge_delta_5d_pct") for row in rows])
        avg_edge_delta_20d = _mean([row.get("edge_delta_20d_pct") for row in rows])

        contribution_5d = None
        if avg_edge_delta_5d is not None:
            contribution_5d = round(-float(avg_edge_delta_5d), 6)
        contribution_20d = None
        if avg_edge_delta_20d is not None:
            contribution_20d = round(-float(avg_edge_delta_20d), 6)

        estimated_cost = round(float(source_costs.get(source, 0.0) or 0.0), 6)
        source_rows.append(
            {
                "source": source,
                "removed_families": list(normalized_map.get(source, ())),
                "runs_evaluated": len(rows),
                "avg_selection_turnover": _mean(
                    [row.get("selection_turnover") for row in rows],
                    default=0.0,
                ),
                "avg_edge_delta_5d_pct": avg_edge_delta_5d,
                "avg_edge_delta_20d_pct": avg_edge_delta_20d,
                "avg_win_rate_delta_5d": _mean([row.get("win_rate_delta_5d") for row in rows]),
                "avg_win_rate_delta_20d": _mean([row.get("win_rate_delta_20d") for row in rows]),
                "lane_mix_delta": {
                    "CORE": _mean(
                        [row.get("lane_mix_delta_core") for row in rows],
                        default=0.0,
                    ),
                    "MOMENTUM": _mean(
                        [row.get("lane_mix_delta_momentum") for row in rows],
                        default=0.0,
                    ),
                },
                "alpha_contribution_5d_pct": contribution_5d,
                "alpha_contribution_20d_pct": contribution_20d,
                "estimated_cost_usd": estimated_cost,
                "alpha_per_dollar_5d_bps": _edge_bps_per_usd(
                    edge_pct=contribution_5d,
                    cost_usd=estimated_cost,
                ),
                "alpha_per_dollar_20d_bps": _edge_bps_per_usd(
                    edge_pct=contribution_20d,
                    cost_usd=estimated_cost,
                ),
            }
        )

    source_rows.sort(
        key=lambda row: (
            float(row["alpha_per_dollar_20d_bps"])
            if isinstance(row.get("alpha_per_dollar_20d_bps"), (int, float))
            else float("-inf"),
            float(row["alpha_contribution_20d_pct"])
            if isinstance(row.get("alpha_contribution_20d_pct"), (int, float))
            else float("-inf"),
            str(row.get("source", "")),
        ),
        reverse=True,
    )
    for idx, row in enumerate(source_rows, start=1):
        row["rank"] = idx

    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "from_date": str(from_date),
        "to_date": str(to_date),
        "source_count": len(source_rows),
        "runs_evaluated": len([date for date, rows in items_by_date.items() if rows]),
        "cost_model": cost_model,
        "parameters": {
            "deep_k": deep_k,
            "base_weights": dict(BASE_WEIGHTS),
            "source_family_map": {
                source: list(families)
                for source, families in sorted(normalized_map.items(), key=lambda kv: kv[0])
            },
            "attribution_note": (
                "alpha_contribution_pct = -(avg_edge_delta_pct) where "
                "edge_delta = ablated_minus_baseline"
            ),
        },
        "sources": source_rows,
        "per_run": per_source_deltas,
    }


def _estimate_source_costs(
    base_dir: Path,
    dates: Sequence[str],
    x_cost_per_api_call_usd: float,
    news_cost_per_run_usd: float,
    macro_cost_per_run_usd: float,
) -> Tuple[Dict[str, float], Dict[str, Any]]:
    source_costs = {
        "x": 0.0,
        "news_vendors": 0.0,
        "macro_feed": 0.0,
    }
    x_cost_per_call = max(0.0, _safe_float(x_cost_per_api_call_usd) or 0.0)
    news_per_run = max(0.0, _safe_float(news_cost_per_run_usd) or 0.0)
    macro_per_run = max(0.0, _safe_float(macro_cost_per_run_usd) or 0.0)

    for date_key in sorted({str(date).strip() for date in dates if str(date).strip()}):
        x_scope = _load_x_scope_for_date(base_dir=base_dir, date_key=date_key)
        x_calls = _estimate_x_api_calls(x_scope)
        source_costs["x"] += float(x_calls) * x_cost_per_call

        connector_rows = _load_connector_health_for_date(base_dir=base_dir, date_key=date_key)
        social_row = _find_connector_row(connector_rows, "social_news")
        if social_row is not None and _connector_cost_active(social_row):
            source_costs["news_vendors"] += news_per_run

        macro_row = _find_connector_row(connector_rows, "macro")
        if macro_row is not None and _connector_cost_active(macro_row):
            source_costs["macro_feed"] += macro_per_run

    rounded = {
        source: round(float(cost), 6)
        for source, cost in source_costs.items()
    }
    model = {
        "x_cost_per_api_call_usd": float(x_cost_per_call),
        "news_cost_per_run_usd": float(news_per_run),
        "macro_cost_per_run_usd": float(macro_per_run),
        "news_cost_activation": "social_news connector present and configured",
        "macro_cost_activation": "macro connector present and configured",
    }
    return rounded, model


def _load_connector_health_for_date(base_dir: Path, date_key: str) -> List[Dict[str, Any]]:
    connector_path = base_dir / str(date_key) / "connector_health.json"
    payload = _read_json(connector_path)
    if not isinstance(payload, list):
        return []
    return [row for row in payload if isinstance(row, dict)]


def _find_connector_row(rows: Sequence[Dict[str, Any]], connector_name: str) -> Optional[Dict[str, Any]]:
    target = str(connector_name or "").strip().lower()
    for row in rows:
        connector = str(row.get("connector", "")).strip().lower()
        if connector == target:
            return row
    return None


def _connector_cost_active(row: Dict[str, Any]) -> bool:
    status = str(row.get("status", "")).strip().upper()
    return status not in {"", "NOT_CONFIGURED"}


def _normalized_source_names(row: Optional[Dict[str, Any]]) -> Set[str]:
    if not isinstance(row, dict):
        return set()
    raw = row.get("source_names")
    if not isinstance(raw, list):
        return set()
    out: Set[str] = set()
    for item in raw:
        token = str(item).strip().lower()
        if token:
            out.add(token)
    return out


def _valid_candidate(row: Dict[str, Any]) -> bool:
    symbol = str(row.get("symbol", "")).strip()
    subscores = row.get("subscores")
    return bool(symbol) and isinstance(subscores, dict)


def _select_top(
    rows: Sequence[Dict[str, Any]],
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


def _selection_horizon_stats(rows: Sequence[Dict[str, Any]], horizon_key: str) -> Dict[str, Optional[float]]:
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


def _lane_mix(rows: Sequence[Dict[str, Any]]) -> Dict[str, float]:
    rows_list = list(rows)
    if not rows_list:
        return {"CORE": 0.0, "MOMENTUM": 0.0}
    total = float(len(rows_list))
    core = sum(1 for row in rows_list if str(row.get("lane", "CORE")).upper() == "CORE")
    momentum = sum(1 for row in rows_list if str(row.get("lane", "CORE")).upper() == "MOMENTUM")
    return {
        "CORE": round(core / total, 6),
        "MOMENTUM": round(momentum / total, 6),
    }


def _mean(values: Sequence[Any], default: Optional[float] = None) -> Optional[float]:
    clean = [float(value) for value in values if isinstance(value, (int, float))]
    if not clean:
        return default
    return round(sum(clean) / len(clean), 6)


def _delta(lhs: Optional[float], rhs: Optional[float]) -> Optional[float]:
    if lhs is None or rhs is None:
        return None
    return round(float(lhs) - float(rhs), 6)


def _load_x_scope_for_date(base_dir: Path, date_key: str) -> Dict[str, Any]:
    shortlist_path = base_dir / str(date_key) / "shortlist_top20.json"
    shortlist_payload = _read_json(shortlist_path)
    if isinstance(shortlist_payload, dict):
        x_scope = shortlist_payload.get("x_scope_summary")
        if isinstance(x_scope, dict):
            return _normalized_x_scope(x_scope)

    return _normalized_x_scope({})


def _normalized_x_scope(payload: Dict[str, Any]) -> Dict[str, Any]:
    mode = str(payload.get("mode", "UNKNOWN")).upper().strip() or "UNKNOWN"
    return {
        "mode": mode,
        "handles": max(0, _safe_int(payload.get("handles"))),
        "symbol_calls": max(0, _safe_int(payload.get("symbol_calls"))),
        "expansions": max(0, _safe_int(payload.get("expansions"))),
    }


def _estimate_x_api_calls(scope: Dict[str, Any]) -> int:
    mode = str(scope.get("mode", "UNKNOWN")).upper().strip()
    handles = max(0, _safe_int(scope.get("handles")))
    symbol_calls = max(0, _safe_int(scope.get("symbol_calls")))
    if mode == "DIRECT_ONLY":
        return int(symbol_calls)
    if mode == "SCOUT_ONLY":
        return int(handles)
    if mode == "HYBRID":
        return int(handles + symbol_calls)
    return int(max(handles, symbol_calls))


def _extract_horizon_metrics(block: Dict[str, Any], horizon_key: str) -> Dict[str, Any]:
    realized = block.get("realized_horizons")
    if not isinstance(realized, dict):
        realized = {}
    horizon = realized.get(horizon_key)
    if not isinstance(horizon, dict):
        horizon = {}
    return {
        "evaluated_count": max(0, _safe_int(horizon.get("evaluated_count"))),
        "pending_count": max(0, _safe_int(horizon.get("pending_count"))),
        "no_data_count": max(0, _safe_int(horizon.get("no_data_count"))),
        "avg_strategy_edge_vs_benchmark_pct": _safe_float(
            horizon.get("avg_strategy_edge_vs_benchmark_pct")
        ),
        "strategy_edge_win_rate": _safe_float(horizon.get("strategy_edge_win_rate")),
    }


def _new_horizon_agg() -> Dict[str, Any]:
    return {
        "evaluated_count": 0,
        "pending_count": 0,
        "no_data_count": 0,
        "edge_weighted_sum": 0.0,
        "win_weighted_sum": 0.0,
    }


def _accumulate_horizon(target: Dict[str, Any], source: Dict[str, Any]) -> None:
    evaluated = max(0, _safe_int(source.get("evaluated_count")))
    pending = max(0, _safe_int(source.get("pending_count")))
    no_data = max(0, _safe_int(source.get("no_data_count")))
    target["evaluated_count"] += evaluated
    target["pending_count"] += pending
    target["no_data_count"] += no_data

    edge = _safe_float(source.get("avg_strategy_edge_vs_benchmark_pct"))
    if edge is not None and evaluated > 0:
        target["edge_weighted_sum"] += float(edge) * float(evaluated)

    win_rate = _safe_float(source.get("strategy_edge_win_rate"))
    if win_rate is not None and evaluated > 0:
        target["win_weighted_sum"] += float(win_rate) * float(evaluated)


def _finalize_horizon(agg: Dict[str, Any]) -> Dict[str, Any]:
    evaluated = max(0, _safe_int(agg.get("evaluated_count")))
    edge = None
    win_rate = None
    if evaluated > 0:
        edge = round(float(agg.get("edge_weighted_sum", 0.0)) / float(evaluated), 6)
        win_rate = round(float(agg.get("win_weighted_sum", 0.0)) / float(evaluated), 6)
    return {
        "evaluated_count": evaluated,
        "pending_count": max(0, _safe_int(agg.get("pending_count"))),
        "no_data_count": max(0, _safe_int(agg.get("no_data_count"))),
        "avg_strategy_edge_vs_benchmark_pct": edge,
        "strategy_edge_win_rate": win_rate,
    }


def _edge_bps_per_usd(edge_pct: Optional[float], cost_usd: float) -> Optional[float]:
    edge = _safe_float(edge_pct)
    if edge is None:
        return None
    cost = _safe_float(cost_usd) or 0.0
    if cost <= 0.0:
        return None
    return round((float(edge) * 100.0) / float(cost), 6)


def _read_json(path: Path) -> Any:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _safe_int(value: Any) -> int:
    try:
        if value is None:
            return 0
        return int(value)
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
