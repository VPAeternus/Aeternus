"""Evidence-pack pipeline orchestration (artifact-only baseline)."""

from __future__ import annotations

import csv
import datetime as dt
import json
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from tradingagents.default_config import DEFAULT_CONFIG

from .ablation import FAMILY_ORDER, build_ablation_report
from .contracts import EvidencePack, EvidenceRunConfig
from .metrics import (
    build_lane_playbook_rows,
    build_metric_set,
    build_regime_rows,
    group_metric_sets,
)
from .regimes import build_regime_report
from .telemetry import (
    build_cost_alpha_telemetry,
    build_feature_family_dashboard,
    build_source_ablation_report,
)
from .live_outcomes import build_live_outcome_report
from .walkforward import build_walkforward_report


def build_evidence_pack(
    from_date: str,
    to_date: str,
    config: Optional[Dict[str, Any]] = None,
    extra_benchmarks: Optional[Sequence[str]] = None,
) -> Tuple[EvidencePack, Dict[str, Path]]:
    started_at_monotonic = time.monotonic()
    runtime_config = dict(DEFAULT_CONFIG)
    if config:
        runtime_config.update(config)

    evidence_config = _build_run_config(
        from_date=from_date,
        to_date=to_date,
        config=runtime_config,
        extra_benchmarks=extra_benchmarks,
    )

    summaries = _collect_analysis_summaries(
        from_date=evidence_config["from_date"],
        to_date=evidence_config["to_date"],
    )
    items_by_date = _collect_items_by_date(summaries)
    all_items = [row for date in sorted(items_by_date.keys()) for row in items_by_date[date]]

    market_snapshots = {
        date_key: _extract_market_snapshot_for_date(date_key)
        for date_key in sorted(items_by_date.keys())
    }
    dgs10_series, cpi_series = _load_macro_series(runtime_config)
    regime_report = build_regime_report(
        market_snapshots=market_snapshots,
        dgs10_daily=dgs10_series,
        cpi_monthly=cpi_series,
    )

    regime_by_date = {
        str(row.get("date")): str(row.get("regime", "NEUTRAL"))
        for row in regime_report.get("date_labels", [])
        if isinstance(row, dict)
    }
    dgs10_by_date = {
        str(row.get("date")): float(row["dgs10"])
        for row in regime_report.get("date_labels", [])
        if isinstance(row, dict) and isinstance(row.get("dgs10"), (int, float))
    }

    for item in all_items:
        date_key = str(item.get("date", ""))
        item["regime"] = regime_by_date.get(date_key, "NEUTRAL")

    overall_metrics = build_metric_set(all_items, risk_free_annual_by_date=dgs10_by_date)
    by_lane = group_metric_sets(
        all_items,
        key_fn=lambda row: str(row.get("lane", "UNKNOWN")).upper(),
        risk_free_annual_by_date=dgs10_by_date,
    )
    by_playbook = group_metric_sets(
        all_items,
        key_fn=lambda row: str(row.get("research_playbook", "UNKNOWN")),
        risk_free_annual_by_date=dgs10_by_date,
    )
    by_signal_family = group_metric_sets(
        all_items,
        key_fn=lambda row: str(row.get("dominant_signal_family", "UNKNOWN")),
        risk_free_annual_by_date=dgs10_by_date,
    )
    by_regime = group_metric_sets(
        all_items,
        key_fn=lambda row: str(row.get("regime", "NEUTRAL")),
        risk_free_annual_by_date=dgs10_by_date,
    )

    daily_edges = _build_daily_edge_rows(summaries)
    walkforward_report = build_walkforward_report(
        daily_rows=daily_edges,
        train_days=int(evidence_config["walkforward_train_days"]),
        test_days=int(evidence_config["walkforward_test_days"]),
        step_days=int(evidence_config["walkforward_step_days"]),
        fallback_train_days=int(evidence_config["walkforward_fallback_train_days"]),
        fallback_test_days=int(evidence_config["walkforward_fallback_test_days"]),
    )

    ablation_report = build_ablation_report(
        items_by_date=items_by_date,
        deep_k=int(evidence_config["deep_k"]),
        families=FAMILY_ORDER,
    )
    cost_alpha_telemetry = build_cost_alpha_telemetry(
        summaries=summaries,
        from_date=str(evidence_config["from_date"]),
        to_date=str(evidence_config["to_date"]),
        x_cost_per_api_call_usd=float(runtime_config.get("dealflow_x_cost_per_api_call_usd", 1.0)),
        dealflow_base_dir=Path("eval_results") / "deal_flow",
    )
    feature_family_dashboard = build_feature_family_dashboard(
        telemetry=cost_alpha_telemetry,
        ablation_report=ablation_report,
    )
    source_ablation_report = build_source_ablation_report(
        items_by_date=items_by_date,
        from_date=str(evidence_config["from_date"]),
        to_date=str(evidence_config["to_date"]),
        dealflow_base_dir=Path("eval_results") / "deal_flow",
        deep_k=int(evidence_config["deep_k"]),
        x_cost_per_api_call_usd=float(runtime_config.get("dealflow_x_cost_per_api_call_usd", 1.0)),
        news_cost_per_run_usd=float(runtime_config.get("dealflow_news_cost_per_run_usd", 0.0)),
        macro_cost_per_run_usd=float(runtime_config.get("dealflow_macro_cost_per_run_usd", 0.0)),
    )

    # Live outcome analysis — bridge execution results to evidence.
    live_outcome = build_live_outcome_report()

    regime_slices = []
    for regime_slice in regime_report.get("regime_slices", []):
        if not isinstance(regime_slice, dict):
            continue
        regime_name = str(regime_slice.get("regime", "NEUTRAL"))
        regime_metrics = by_regime.get(regime_name, build_metric_set([], risk_free_annual_by_date=dgs10_by_date))
        regime_slices.append(
            {
                "regime": regime_name,
                "count": int(regime_slice.get("count", 0) or 0),
                "pct": float(regime_slice.get("pct", 0.0) or 0.0),
                "metrics": regime_metrics,
            }
        )

    non_zero_regime_slices = sum(1 for row in regime_slices if int(row.get("count", 0)) > 0)
    complete_regimes = _parse_csv_list(
        runtime_config.get("evidence_complete_required_regimes", "BEAR,HIGH_VOL,INFLATION_SHOCK")
    )
    complete_min_days = int(runtime_config.get("evidence_complete_min_regime_days", 180))
    regime_coverage_days = _build_regime_coverage_days(
        counts=(regime_report.get("counts") if isinstance(regime_report, dict) else {}),
        required_regimes=complete_regimes,
    )
    regime_coverage_complete = all(
        int(regime_coverage_days.get(regime, 0)) >= int(complete_min_days)
        for regime in complete_regimes
    ) if complete_regimes else True

    windows_count = int(walkforward_report.get("windows_count", 0) or 0)
    edge_decay_5d = _to_float((walkforward_report.get("aggregate") or {}).get("edge_decay_5d_pct"))
    edge_decay_20d = _to_float((walkforward_report.get("aggregate") or {}).get("edge_decay_20d_pct"))

    status = _derive_status(
        sample_days=len(items_by_date),
        windows_count=windows_count,
        walkforward_status=str(walkforward_report.get("status", "INSUFFICIENT_DEPTH")),
        regime_slices=non_zero_regime_slices,
        complete_regime_coverage=regime_coverage_complete,
    )
    runtime_seconds = round(float(time.monotonic() - started_at_monotonic), 6)
    runtime_soft_cap_seconds = float(runtime_config.get("evidence_runtime_soft_cap_seconds", 600.0))
    runtime_hard_cap_seconds = float(runtime_config.get("evidence_runtime_hard_cap_seconds", 1200.0))
    runtime_alert = _runtime_alert_or_raise(
        runtime_seconds=runtime_seconds,
        soft_cap_seconds=runtime_soft_cap_seconds,
        hard_cap_seconds=runtime_hard_cap_seconds,
    )

    output_root = Path("eval_results") / "evidence" / str(evidence_config["to_date"])
    output_root.mkdir(parents=True, exist_ok=True)

    artifacts = {
        "evidence_pack": output_root / "evidence_pack.json",
        "regime_report": output_root / "regime_report.json",
        "walkforward_report": output_root / "walkforward_report.json",
        "ablation_report": output_root / "ablation_report.json",
        "cost_alpha_telemetry": output_root / "cost_alpha_telemetry.json",
        "feature_family_dashboard": output_root / "feature_family_dashboard.json",
        "feature_family_dashboard_csv": output_root / "feature_family_dashboard.csv",
        "source_ablation_report": output_root / "source_ablation_report.json",
        "source_alpha_per_dollar_csv": output_root / "source_alpha_per_dollar.csv",
        "metrics_by_lane_playbook": output_root / "metrics_by_lane_playbook.csv",
        "metrics_by_regime": output_root / "metrics_by_regime.csv",
        "live_outcome_report": output_root / "live_outcome_report.json",
        "latest": Path("eval_results") / "evidence" / "evidence_pack_latest.json",
    }

    _write_json(artifacts["regime_report"], regime_report)
    _write_json(artifacts["walkforward_report"], walkforward_report)
    _write_json(artifacts["ablation_report"], ablation_report)
    _write_json(artifacts["cost_alpha_telemetry"], cost_alpha_telemetry)
    _write_json(artifacts["feature_family_dashboard"], feature_family_dashboard)
    _write_json(artifacts["source_ablation_report"], source_ablation_report)
    _write_json(artifacts["live_outcome_report"], live_outcome)

    lane_playbook_rows = build_lane_playbook_rows(all_items, risk_free_annual_by_date=dgs10_by_date)
    regime_rows = build_regime_rows(all_items, risk_free_annual_by_date=dgs10_by_date)
    dashboard_rows = feature_family_dashboard.get("rows", [])
    if not isinstance(dashboard_rows, list):
        dashboard_rows = []
    source_rows = source_ablation_report.get("sources", [])
    if not isinstance(source_rows, list):
        source_rows = []
    _write_csv(artifacts["metrics_by_lane_playbook"], lane_playbook_rows)
    _write_csv(artifacts["metrics_by_regime"], regime_rows)
    _write_csv(artifacts["feature_family_dashboard_csv"], dashboard_rows)
    _write_csv(artifacts["source_alpha_per_dollar_csv"], source_rows)

    evidence_pack: EvidencePack = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "status": status,
        "from_date": str(evidence_config["from_date"]),
        "to_date": str(evidence_config["to_date"]),
        "sample_days": len(items_by_date),
        "benchmarks": {
            "primary": evidence_config["primary_benchmark"],
            "secondary": evidence_config["secondary_benchmark"],
            "extra": list(evidence_config["extra_benchmarks"]),
        },
        "config": evidence_config,
        "overall_metrics": overall_metrics,
        "by_lane": by_lane,
        "by_playbook": by_playbook,
        "by_signal_family": by_signal_family,
        "by_regime": by_regime,
        "regime_slices": regime_slices,
        "walkforward": walkforward_report,
        "ablation": ablation_report,
        "source_ablation": source_ablation_report,
        "live_outcome": live_outcome,
        "readiness_summary": {
            "walkforward_windows": windows_count,
            "regime_slices": non_zero_regime_slices,
            "edge_decay_5d_pct": edge_decay_5d,
            "edge_decay_20d_pct": edge_decay_20d,
            "regime_coverage_required_regimes": complete_regimes,
            "regime_coverage_required_days": int(complete_min_days),
            "regime_coverage_days": regime_coverage_days,
            "regime_coverage_complete": bool(regime_coverage_complete),
            "runtime_seconds": runtime_seconds,
            "runtime_soft_cap_seconds": runtime_soft_cap_seconds,
            "runtime_hard_cap_seconds": runtime_hard_cap_seconds,
            "runtime_alert": runtime_alert,
        },
        "artifacts": {key: str(path) for key, path in artifacts.items()},
    }

    _write_json(artifacts["evidence_pack"], evidence_pack)
    _write_json(artifacts["latest"], evidence_pack)

    return evidence_pack, artifacts


def build_evidence_regimes(
    date: str,
    config: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Path]:
    runtime_config = dict(DEFAULT_CONFIG)
    if config:
        runtime_config.update(config)

    snapshot = _extract_market_snapshot_for_date(date)
    dgs10_series, cpi_series = _load_macro_series(runtime_config)
    report = build_regime_report(
        market_snapshots={str(date): snapshot},
        dgs10_daily=dgs10_series,
        cpi_monthly=cpi_series,
    )

    output_root = Path("eval_results") / "evidence" / str(date)
    output_root.mkdir(parents=True, exist_ok=True)
    path = output_root / "regime_report.json"
    _write_json(path, report)
    return report, path


def build_evidence_walkforward(
    from_date: str,
    to_date: str,
    config: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Path]:
    runtime_config = dict(DEFAULT_CONFIG)
    if config:
        runtime_config.update(config)

    evidence_config = _build_run_config(from_date, to_date, runtime_config, extra_benchmarks=None)
    summaries = _collect_analysis_summaries(evidence_config["from_date"], evidence_config["to_date"])
    daily_edges = _build_daily_edge_rows(summaries)
    report = build_walkforward_report(
        daily_rows=daily_edges,
        train_days=int(evidence_config["walkforward_train_days"]),
        test_days=int(evidence_config["walkforward_test_days"]),
        step_days=int(evidence_config["walkforward_step_days"]),
        fallback_train_days=int(evidence_config["walkforward_fallback_train_days"]),
        fallback_test_days=int(evidence_config["walkforward_fallback_test_days"]),
    )

    output_root = Path("eval_results") / "evidence" / str(evidence_config["to_date"])
    output_root.mkdir(parents=True, exist_ok=True)
    path = output_root / "walkforward_report.json"
    _write_json(path, report)
    return report, path


def build_evidence_ablation(
    from_date: str,
    to_date: str,
    config: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Path]:
    runtime_config = dict(DEFAULT_CONFIG)
    if config:
        runtime_config.update(config)

    evidence_config = _build_run_config(from_date, to_date, runtime_config, extra_benchmarks=None)
    summaries = _collect_analysis_summaries(evidence_config["from_date"], evidence_config["to_date"])
    items_by_date = _collect_items_by_date(summaries)
    report = build_ablation_report(
        items_by_date=items_by_date,
        deep_k=int(evidence_config["deep_k"]),
        families=FAMILY_ORDER,
    )

    output_root = Path("eval_results") / "evidence" / str(evidence_config["to_date"])
    output_root.mkdir(parents=True, exist_ok=True)
    path = output_root / "ablation_report.json"
    _write_json(path, report)
    return report, path


def build_evidence_telemetry(
    from_date: str,
    to_date: str,
    config: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Path]]:
    runtime_config = dict(DEFAULT_CONFIG)
    if config:
        runtime_config.update(config)

    evidence_config = _build_run_config(from_date, to_date, runtime_config, extra_benchmarks=None)
    summaries = _collect_analysis_summaries(evidence_config["from_date"], evidence_config["to_date"])
    items_by_date = _collect_items_by_date(summaries)
    ablation_report = build_ablation_report(
        items_by_date=items_by_date,
        deep_k=int(evidence_config["deep_k"]),
        families=FAMILY_ORDER,
    )
    cost_alpha = build_cost_alpha_telemetry(
        summaries=summaries,
        from_date=str(evidence_config["from_date"]),
        to_date=str(evidence_config["to_date"]),
        x_cost_per_api_call_usd=float(runtime_config.get("dealflow_x_cost_per_api_call_usd", 1.0)),
        dealflow_base_dir=Path("eval_results") / "deal_flow",
    )
    source_ablation = build_source_ablation_report(
        items_by_date=items_by_date,
        from_date=str(evidence_config["from_date"]),
        to_date=str(evidence_config["to_date"]),
        dealflow_base_dir=Path("eval_results") / "deal_flow",
        deep_k=int(evidence_config["deep_k"]),
        x_cost_per_api_call_usd=float(runtime_config.get("dealflow_x_cost_per_api_call_usd", 1.0)),
        news_cost_per_run_usd=float(runtime_config.get("dealflow_news_cost_per_run_usd", 0.0)),
        macro_cost_per_run_usd=float(runtime_config.get("dealflow_macro_cost_per_run_usd", 0.0)),
    )
    dashboard = build_feature_family_dashboard(
        telemetry=cost_alpha,
        ablation_report=ablation_report,
    )
    report = dict(cost_alpha)
    report["feature_family_dashboard"] = dashboard
    report["source_ablation"] = source_ablation

    output_root = Path("eval_results") / "evidence" / str(evidence_config["to_date"])
    output_root.mkdir(parents=True, exist_ok=True)
    artifacts = {
        "cost_alpha_telemetry": output_root / "cost_alpha_telemetry.json",
        "feature_family_dashboard": output_root / "feature_family_dashboard.json",
        "feature_family_dashboard_csv": output_root / "feature_family_dashboard.csv",
        "source_ablation_report": output_root / "source_ablation_report.json",
        "source_alpha_per_dollar_csv": output_root / "source_alpha_per_dollar.csv",
    }

    _write_json(artifacts["cost_alpha_telemetry"], cost_alpha)
    _write_json(artifacts["feature_family_dashboard"], dashboard)
    _write_json(artifacts["source_ablation_report"], source_ablation)
    dashboard_rows = dashboard.get("rows", [])
    if not isinstance(dashboard_rows, list):
        dashboard_rows = []
    source_rows = source_ablation.get("sources", [])
    if not isinstance(source_rows, list):
        source_rows = []
    _write_csv(artifacts["feature_family_dashboard_csv"], dashboard_rows)
    _write_csv(artifacts["source_alpha_per_dollar_csv"], source_rows)
    return report, artifacts


def _build_run_config(
    from_date: str,
    to_date: str,
    config: Dict[str, Any],
    extra_benchmarks: Optional[Sequence[str]],
) -> EvidenceRunConfig:
    validated_from = _coerce_date_str(from_date)
    validated_to = _coerce_date_str(to_date)
    if validated_from > validated_to:
        validated_from, validated_to = validated_to, validated_from

    return {
        "from_date": validated_from,
        "to_date": validated_to,
        "primary_benchmark": str(config.get("evidence_primary_benchmark", "SPY")),
        "secondary_benchmark": str(config.get("evidence_secondary_benchmark", "QQQ")),
        "extra_benchmarks": [str(x).upper() for x in (extra_benchmarks or []) if str(x).strip()],
        "walkforward_train_days": int(config.get("evidence_walkforward_train_days", 756)),
        "walkforward_test_days": int(config.get("evidence_walkforward_test_days", 252)),
        "walkforward_step_days": int(config.get("evidence_walkforward_step_days", 63)),
        "walkforward_fallback_train_days": int(config.get("evidence_walkforward_fallback_train_days", 252)),
        "walkforward_fallback_test_days": int(config.get("evidence_walkforward_fallback_test_days", 63)),
        "fundamental_handoff_limit": int(config.get("evidence_fundamental_handoff_limit", 0)),
        "slippage_bps": float(config.get("paper_execution_slippage_bps", 0.0)),
    }


def _collect_analysis_summaries(from_date: str, to_date: str) -> List[Dict[str, Any]]:
    del from_date, to_date
    return []


def _collect_items_by_date(summaries: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    by_date: Dict[str, List[Dict[str, Any]]] = {}
    for summary in summaries:
        date_key = str(summary.get("date", "")).strip()
        if not date_key:
            continue
        rows = by_date.setdefault(date_key, [])
        for item in summary.get("items", []):
            if not isinstance(item, dict):
                continue
            enriched = dict(item)
            enriched["date"] = date_key
            rows.append(enriched)
    return by_date


def _build_daily_edge_rows(summaries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for summary in summaries:
        attribution = summary.get("attribution")
        if not isinstance(attribution, dict):
            continue
        overall = attribution.get("overall")
        if not isinstance(overall, dict):
            continue
        horizons = overall.get("realized_horizons")
        if not isinstance(horizons, dict):
            continue

        edge_5 = _extract_strategy_edge(horizons.get("5d"))
        edge_20 = _extract_strategy_edge(horizons.get("20d"))
        rows.append(
            {
                "date": str(summary.get("date", "")),
                "edge_5d_pct": edge_5,
                "edge_20d_pct": edge_20,
            }
        )
    return sorted(rows, key=lambda row: str(row.get("date", "")))


def _extract_strategy_edge(horizon_payload: Any) -> Optional[float]:
    if not isinstance(horizon_payload, dict):
        return None
    primary = horizon_payload.get("avg_strategy_edge_vs_benchmark_pct")
    fallback = horizon_payload.get("avg_edge_vs_benchmark_pct")
    if isinstance(primary, (int, float)):
        return float(primary)
    if isinstance(fallback, (int, float)):
        return float(fallback)
    return None


def _extract_market_snapshot_for_date(date_key: str) -> Dict[str, Any]:
    # First preference: plan hedge context snapshot.
    plans_dir = Path("eval_results") / "paper_execution" / "plans" / str(date_key)
    if plans_dir.exists():
        plan_paths = sorted(plans_dir.glob("portfolio_plan_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        for path in plan_paths:
            payload = _read_json(path)
            hedge_context = payload.get("hedge_context") if isinstance(payload, dict) else None
            if isinstance(hedge_context, dict):
                market = hedge_context.get("market_snapshot")
                if isinstance(market, dict) and market:
                    return dict(market)

    # Fallback: any per-symbol analysis report market_regime block.
    results_root = Path("results")
    if results_root.exists():
        for report_path in sorted(results_root.glob(f"*/{date_key}/analysis_report.json")):
            payload = _read_json(report_path)
            market = payload.get("market_regime") if isinstance(payload, dict) else None
            if isinstance(market, dict) and market:
                return dict(market)

    return {
        "spy_close": None,
        "spy_sma20": None,
        "spy_sma200": None,
        "spy_sma200_5d_ago": None,
        "spy_deviation_pct": None,
        "vix_close": None,
    }


def _load_macro_series(config: Dict[str, Any]) -> Tuple[Dict[str, float], Dict[str, float]]:
    dgs10_path = str(config.get("evidence_dgs10_series_path", "")).strip()
    cpi_path = str(config.get("evidence_cpi_series_path", "")).strip()
    return _load_series_map(dgs10_path), _load_series_map(cpi_path)


def _load_series_map(path_value: str) -> Dict[str, float]:
    if not path_value:
        return {}
    path = Path(path_value)
    if not path.exists():
        return {}

    if path.suffix.lower() == ".json":
        payload = _read_json(path)
        return _coerce_map(payload)

    if path.suffix.lower() == ".csv":
        out: Dict[str, float] = {}
        with path.open("r", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                if not isinstance(row, dict):
                    continue
                key = str(row.get("date") or row.get("month") or "").strip()
                value = _to_float(row.get("value"))
                if key and value is not None:
                    out[key] = value
        return out

    return {}


def _coerce_map(payload: Any) -> Dict[str, float]:
    if isinstance(payload, dict):
        out: Dict[str, float] = {}
        for key, value in payload.items():
            numeric = _to_float(value)
            if numeric is not None:
                out[str(key)] = numeric
        return out

    if isinstance(payload, list):
        out: Dict[str, float] = {}
        for row in payload:
            if not isinstance(row, dict):
                continue
            key = str(row.get("date") or row.get("month") or "").strip()
            numeric = _to_float(row.get("value"))
            if key and numeric is not None:
                out[key] = numeric
        return out

    return {}


def _derive_status(
    sample_days: int,
    windows_count: int,
    walkforward_status: str,
    regime_slices: int,
    complete_regime_coverage: bool = True,
) -> str:
    if sample_days <= 0 or windows_count <= 0:
        return "INSUFFICIENT_DEPTH"
    if str(walkforward_status).upper() != "COMPLETE":
        return "PARTIAL_DATA"
    if regime_slices < 4:
        return "PARTIAL_DATA"
    if not bool(complete_regime_coverage):
        return "PARTIAL_DATA"
    return "COMPLETE"


def _parse_csv_list(value: Any) -> List[str]:
    if isinstance(value, str):
        parts = [part.strip() for part in value.split(",")]
    elif isinstance(value, Sequence):
        parts = [str(part).strip() for part in value]
    else:
        parts = []
    out: List[str] = []
    for part in parts:
        if part and part not in out:
            out.append(part)
    return out


def _build_regime_coverage_days(
    counts: Any,
    required_regimes: Sequence[str],
) -> Dict[str, int]:
    raw = counts if isinstance(counts, dict) else {}
    return {
        str(regime): int(raw.get(str(regime), 0) or 0)
        for regime in required_regimes
    }


def _runtime_alert_or_raise(
    runtime_seconds: float,
    soft_cap_seconds: float,
    hard_cap_seconds: float,
) -> str:
    alert = "NONE"
    if soft_cap_seconds > 0 and runtime_seconds > soft_cap_seconds:
        alert = "SOFT_CAP_EXCEEDED"
    if hard_cap_seconds > 0 and runtime_seconds > hard_cap_seconds:
        raise TimeoutError(
            "Evidence pack runtime exceeded hard cap "
            f"({runtime_seconds:.3f}s > {hard_cap_seconds:.3f}s)."
        )
    return alert


def _coerce_date_str(value: str) -> str:
    parsed = _parse_date(value)
    if parsed is None:
        raise ValueError(f"Invalid date: {value}")
    return parsed.isoformat()


def _parse_date(value: Any) -> Optional[dt.date]:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return dt.datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return None


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text())
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))


def _write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("")
        return
    fields = sorted({key for row in rows for key in row.keys()})
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _to_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
