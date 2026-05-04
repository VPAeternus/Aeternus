"""Step 1 readiness evaluator for Deal Flow build-out."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


def evaluate_step1_readiness(
    config: Dict[str, Any],
    as_of_date: Optional[str] = None,
    base_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Evaluate deterministic Step 1 go/no-go gates from persisted artifacts."""
    root = Path(base_dir or Path("eval_results") / "deal_flow")
    as_of = _parse_iso_date(as_of_date) or dt.date.today()
    lookback_days = int(config.get("dealflow_step1_lookback_days", 60))
    window_start = as_of - dt.timedelta(days=max(0, lookback_days))

    required_stable_cycles = int(config.get("dealflow_step1_required_stable_cycles", 3))
    min_batch_executed = int(config.get("dealflow_step1_min_batch_executed_per_cycle", 1))
    max_batch_failure_ratio = float(config.get("dealflow_step1_max_batch_failure_ratio", 0.40))
    max_connector_errors = int(config.get("dealflow_step1_max_connector_errors_per_cycle", 0))

    cycle_rows = _load_cycle_rows(
        root=root,
        as_of=as_of,
        window_start=window_start,
        min_batch_executed=min_batch_executed,
        max_batch_failure_ratio=max_batch_failure_ratio,
        max_connector_errors=max_connector_errors,
    )

    consecutive_stable = 0
    for row in cycle_rows:
        if bool(row.get("stable")):
            consecutive_stable += 1
        else:
            break

    stability_gate = {
        "pass": consecutive_stable >= required_stable_cycles,
        "required_stable_cycles": required_stable_cycles,
        "consecutive_stable_cycles": consecutive_stable,
        "latest_cycle_count": len(cycle_rows),
    }

    attribution_stats = _collect_unique_realized_samples(cycle_rows)
    min_eval_5d = int(config.get("dealflow_step1_min_evaluated_5d", 2))
    min_eval_20d = int(config.get("dealflow_step1_min_evaluated_20d", 2))
    target_eval_5d = int(config.get("dealflow_step1_target_evaluated_5d", 20))
    target_eval_20d = int(config.get("dealflow_step1_target_evaluated_20d", 20))

    attribution_gate = {
        "pass": (
            int(attribution_stats["evaluated_5d"]) >= min_eval_5d
            and int(attribution_stats["evaluated_20d"]) >= min_eval_20d
        ),
        "evaluated_5d": int(attribution_stats["evaluated_5d"]),
        "evaluated_20d": int(attribution_stats["evaluated_20d"]),
        "required_5d": min_eval_5d,
        "required_20d": min_eval_20d,
    }

    production_targets = {
        "evaluated_5d_target": target_eval_5d,
        "evaluated_20d_target": target_eval_20d,
        "evaluated_5d_met": int(attribution_stats["evaluated_5d"]) >= target_eval_5d,
        "evaluated_20d_met": int(attribution_stats["evaluated_20d"]) >= target_eval_20d,
    }

    connector_policy = _evaluate_connector_policy(
        root=root,
        as_of=as_of,
        window_start=window_start,
        config=config,
    )
    evidence_quality = _evaluate_evidence_quality(
        evidence_root=root.parent / "evidence",
        as_of=as_of,
        config=config,
    )

    gates = {
        "stability": stability_gate,
        "attribution_sample": attribution_gate,
        "connector_policy": connector_policy,
        "evidence_quality": evidence_quality,
    }
    blockers = _build_blockers(gates)
    ready = len(blockers) == 0

    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "as_of_date": as_of.isoformat(),
        "overall_ready": ready,
        "gates": gates,
        "production_targets": production_targets,
        "recent_cycles": cycle_rows[:10],
        "unique_samples": attribution_stats,
        "blockers": blockers,
        "next_action": (
            "READY_FOR_STEP_2"
            if ready
            else "CONTINUE_STEP_1_HARDENING"
        ),
    }


def persist_step1_readiness(
    snapshot: Dict[str, Any],
    as_of_date: str,
    base_dir: Optional[Path] = None,
) -> Path:
    root = Path(base_dir or Path("eval_results") / "deal_flow")
    dated = root / str(as_of_date)
    dated.mkdir(parents=True, exist_ok=True)
    dated_path = dated / "step1_readiness.json"
    latest_path = root / "step1_readiness_latest.json"
    raw = json.dumps(snapshot, indent=2)
    dated_path.write_text(raw)
    latest_path.write_text(raw)
    return dated_path


def _load_cycle_rows(
    root: Path,
    as_of: dt.date,
    window_start: dt.date,
    min_batch_executed: int,
    max_batch_failure_ratio: float,
    max_connector_errors: int,
) -> List[Dict[str, Any]]:
    paths = sorted(
        root.glob("*/batch_analyze_summary_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    rows: List[Dict[str, Any]] = []
    for path in paths:
        summary = _read_json(path)
        if not isinstance(summary, dict):
            continue
        date_value = _parse_iso_date(summary.get("date"))
        if date_value is None or date_value > as_of or date_value < window_start:
            continue

        run_date = date_value.isoformat()
        shortlist = _read_json(root / run_date / "shortlist_top20.json")
        connector_summary = (
            shortlist.get("connector_health_summary", {})
            if isinstance(shortlist, dict)
            else {}
        )
        status_totals = (
            connector_summary.get("status_totals", {})
            if isinstance(connector_summary, dict)
            else {}
        )
        connector_errors = int(status_totals.get("ERROR", 0) or 0)

        success_count = int(summary.get("success_count", 0) or 0)
        failure_count = int(summary.get("failure_count", 0) or 0)
        skipped_count = int(summary.get("skipped_count", 0) or 0)
        executed_count = max(0, success_count + failure_count)
        failure_ratio = (
            float(failure_count) / float(executed_count)
            if executed_count > 0
            else 1.0
        )

        reasons: List[str] = []
        if executed_count < min_batch_executed:
            reasons.append(
                f"executed_count={executed_count} below min={min_batch_executed}"
            )
        if failure_ratio > max_batch_failure_ratio:
            reasons.append(
                f"failure_ratio={failure_ratio:.3f} above max={max_batch_failure_ratio:.3f}"
            )
        if connector_errors > max_connector_errors:
            reasons.append(
                f"connector_errors={connector_errors} above max={max_connector_errors}"
            )

        row = {
            "date": run_date,
            "summary_path": str(path),
            "run_id": str(summary.get("run_id") or ""),
            "processed": int(summary.get("processed", 0) or 0),
            "executed_count": int(executed_count),
            "success_count": success_count,
            "failure_count": failure_count,
            "skipped_count": skipped_count,
            "failure_ratio": float(round(failure_ratio, 4)),
            "connector_errors": connector_errors,
            "connector_not_configured": int(status_totals.get("NOT_CONFIGURED", 0) or 0),
            "stable": len(reasons) == 0,
            "stability_reasons": reasons,
            "finished_at": str(summary.get("finished_at") or ""),
            "items": list(summary.get("items", [])) if isinstance(summary.get("items"), list) else [],
        }
        rows.append(row)
    return rows


def _collect_unique_realized_samples(cycle_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_symbol_date: Dict[Tuple[str, str], Dict[str, Any]] = {}
    instance_eval_5d = 0
    instance_eval_20d = 0

    for row in cycle_rows:
        date_value = str(row.get("date") or "")
        for item in row.get("items", []):
            if not isinstance(item, dict):
                continue
            status = str(item.get("status", "")).upper()
            if status not in {"SUCCESS", "SUCCESS_CACHED"}:
                continue
            symbol = str(item.get("symbol", "")).upper().strip()
            if not symbol or not date_value:
                continue
            horizons = item.get("realized_horizons", {})
            if not isinstance(horizons, dict):
                continue
            h5 = horizons.get("5d", {})
            h20 = horizons.get("20d", {})
            if isinstance(h5, dict) and str(h5.get("status", "")).upper() == "READY":
                instance_eval_5d += 1
            if isinstance(h20, dict) and str(h20.get("status", "")).upper() == "READY":
                instance_eval_20d += 1

            key = (date_value, symbol)
            by_symbol_date[key] = item

    unique_eval_5d = 0
    unique_eval_20d = 0
    ready_5d_symbols: List[str] = []
    ready_20d_symbols: List[str] = []
    for (run_date, symbol), item in by_symbol_date.items():
        horizons = item.get("realized_horizons", {})
        if not isinstance(horizons, dict):
            continue
        h5 = horizons.get("5d", {})
        h20 = horizons.get("20d", {})
        if isinstance(h5, dict) and str(h5.get("status", "")).upper() == "READY":
            unique_eval_5d += 1
            ready_5d_symbols.append(f"{run_date}:{symbol}")
        if isinstance(h20, dict) and str(h20.get("status", "")).upper() == "READY":
            unique_eval_20d += 1
            ready_20d_symbols.append(f"{run_date}:{symbol}")

    return {
        "unique_symbols_dates": int(len(by_symbol_date)),
        "evaluated_5d": int(instance_eval_5d),
        "evaluated_20d": int(instance_eval_20d),
        "unique_evaluated_5d": int(unique_eval_5d),
        "unique_evaluated_20d": int(unique_eval_20d),
        "ready_5d_symbols": sorted(ready_5d_symbols),
        "ready_20d_symbols": sorted(ready_20d_symbols),
    }


def _evaluate_connector_policy(
    root: Path,
    as_of: dt.date,
    window_start: dt.date,
    config: Dict[str, Any],
) -> Dict[str, Any]:
    latest_date = _latest_shortlist_date(root=root, as_of=as_of, window_start=window_start)
    if latest_date is None:
        return {
            "pass": False,
            "latest_date": None,
            "required_connectors": [],
            "missing_connectors": ["NO_SHORTLIST_RUNS"],
            "degraded_connectors": [],
            "optional_connector_issues": [],
        }

    connector_health = _read_json(root / latest_date / "connector_health.json")
    rows = connector_health if isinstance(connector_health, list) else []
    status_by_connector = {
        str(row.get("connector", "")): str(row.get("status", "NO_DATA"))
        for row in rows
        if isinstance(row, dict) and str(row.get("connector", "")).strip()
    }

    required_connectors = _parse_csv_list(
        config.get(
            "dealflow_step1_required_connectors",
            "social_news,price_momentum,macro,smart_money",
        )
    )
    optional_connectors = _parse_csv_list(
        config.get("dealflow_step1_optional_connectors", "")
    )
    required_allowed_statuses = set(
        _parse_csv_list(config.get("dealflow_step1_required_connector_statuses", "OK,NO_DATA"))
    )
    if not required_allowed_statuses:
        required_allowed_statuses = {"OK", "NO_DATA"}

    missing_connectors = [
        name for name in required_connectors if name not in status_by_connector
    ]
    degraded_connectors = [
        name
        for name in required_connectors
        if name in status_by_connector and status_by_connector[name] not in required_allowed_statuses
    ]
    optional_issues = [
        name
        for name in optional_connectors
        if name in status_by_connector and status_by_connector[name] == "ERROR"
    ]

    return {
        "pass": len(missing_connectors) == 0 and len(degraded_connectors) == 0,
        "latest_date": latest_date,
        "required_connectors": required_connectors,
        "required_allowed_statuses": sorted(required_allowed_statuses),
        "missing_connectors": missing_connectors,
        "degraded_connectors": degraded_connectors,
        "optional_connector_issues": optional_issues,
        "status_by_connector": status_by_connector,
    }


def _latest_shortlist_date(root: Path, as_of: dt.date, window_start: dt.date) -> Optional[str]:
    best: Optional[str] = None
    for path in root.glob("*/shortlist_top20.json"):
        date_value = _parse_iso_date(path.parent.name)
        if date_value is None or date_value > as_of or date_value < window_start:
            continue
        if best is None or date_value.isoformat() > best:
            best = date_value.isoformat()
    return best


def _build_blockers(gates: Dict[str, Dict[str, Any]]) -> List[str]:
    blockers: List[str] = []
    stability = gates.get("stability", {})
    if not bool(stability.get("pass")):
        blockers.append(
            "Need more consecutive stable batch cycles "
            f"({stability.get('consecutive_stable_cycles', 0)}/"
            f"{stability.get('required_stable_cycles', 0)})."
        )

    attribution = gates.get("attribution_sample", {})
    if not bool(attribution.get("pass")):
        blockers.append(
            "Need more realized attribution samples "
            f"(5d={attribution.get('evaluated_5d', 0)}/{attribution.get('required_5d', 0)}, "
            f"20d={attribution.get('evaluated_20d', 0)}/{attribution.get('required_20d', 0)})."
        )

    connector = gates.get("connector_policy", {})
    if not bool(connector.get("pass")):
        missing = connector.get("missing_connectors", [])
        degraded = connector.get("degraded_connectors", [])
        blockers.append(
            "Connector policy not satisfied "
            f"(missing={missing}, degraded={degraded})."
        )
    evidence = gates.get("evidence_quality", {})
    if not bool(evidence.get("pass")):
        blockers.append(
            "Evidence quality gate not satisfied "
            f"(status={evidence.get('status')}, "
            f"windows={evidence.get('walkforward_windows', 0)}/{evidence.get('required_walkforward_windows', 0)}, "
            f"regimes={evidence.get('regime_slices', 0)}/{evidence.get('required_regime_slices', 0)}, "
            f"edge_decay_5d={evidence.get('edge_decay_5d_pct')}, "
            f"edge_decay_20d={evidence.get('edge_decay_20d_pct')})."
        )
    return blockers


def _evaluate_evidence_quality(
    evidence_root: Path,
    as_of: dt.date,
    config: Dict[str, Any],
) -> Dict[str, Any]:
    required_windows = int(config.get("evidence_min_walkforward_windows", 3))
    required_regime_slices = int(config.get("evidence_min_regime_slices", 4))
    max_edge_decay_5d = float(config.get("evidence_max_edge_decay_5d", 2.0))
    max_edge_decay_20d = float(config.get("evidence_max_edge_decay_20d", 2.0))
    allow_partial_data = bool(config.get("evidence_readiness_allow_partial_data", False))

    evidence_pack = _load_latest_evidence_pack(evidence_root=evidence_root, as_of=as_of)
    if not isinstance(evidence_pack, dict):
        return {
            "pass": False,
            "status": "MISSING",
            "pack_date": None,
            "walkforward_windows": 0,
            "regime_slices": 0,
            "edge_decay_5d_pct": None,
            "edge_decay_20d_pct": None,
            "required_walkforward_windows": required_windows,
            "required_regime_slices": required_regime_slices,
            "max_edge_decay_5d_pct": max_edge_decay_5d,
            "max_edge_decay_20d_pct": max_edge_decay_20d,
            "allow_partial_data": allow_partial_data,
        }

    readiness = evidence_pack.get("readiness_summary", {})
    walkforward_windows = int(
        readiness.get("walkforward_windows")
        or (evidence_pack.get("walkforward", {}) or {}).get("windows_count")
        or 0
    )
    regime_slices = int(readiness.get("regime_slices") or 0)
    edge_decay_5d = _as_float(readiness.get("edge_decay_5d_pct"))
    edge_decay_20d = _as_float(readiness.get("edge_decay_20d_pct"))

    pass_windows = walkforward_windows >= required_windows
    pass_regimes = regime_slices >= required_regime_slices
    pass_decay_5d = edge_decay_5d is not None and edge_decay_5d <= max_edge_decay_5d
    pass_decay_20d = edge_decay_20d is not None and edge_decay_20d <= max_edge_decay_20d

    status = str(evidence_pack.get("status", "UNKNOWN"))
    is_depth_ok = status == "COMPLETE" or (allow_partial_data and status == "PARTIAL_DATA")
    passed = bool(is_depth_ok and pass_windows and pass_regimes and pass_decay_5d and pass_decay_20d)

    return {
        "pass": passed,
        "status": status,
        "pack_date": str(evidence_pack.get("to_date") or evidence_pack.get("date") or ""),
        "walkforward_windows": walkforward_windows,
        "regime_slices": regime_slices,
        "edge_decay_5d_pct": edge_decay_5d,
        "edge_decay_20d_pct": edge_decay_20d,
        "required_walkforward_windows": required_windows,
        "required_regime_slices": required_regime_slices,
        "max_edge_decay_5d_pct": max_edge_decay_5d,
        "max_edge_decay_20d_pct": max_edge_decay_20d,
        "allow_partial_data": allow_partial_data,
    }


def _load_latest_evidence_pack(evidence_root: Path, as_of: dt.date) -> Optional[Dict[str, Any]]:
    if not evidence_root.exists():
        return None

    dated_paths: List[Tuple[dt.date, Path]] = []
    for path in evidence_root.glob("*/evidence_pack.json"):
        date_value = _parse_iso_date(path.parent.name)
        if date_value is None or date_value > as_of:
            continue
        dated_paths.append((date_value, path))

    if dated_paths:
        dated_paths.sort(key=lambda pair: pair[0], reverse=True)
        payload = _read_json(dated_paths[0][1])
        if isinstance(payload, dict):
            return payload

    latest = evidence_root / "evidence_pack_latest.json"
    payload = _read_json(latest)
    if isinstance(payload, dict):
        pack_date = _parse_iso_date(payload.get("to_date"))
        if pack_date is None or pack_date <= as_of:
            return payload
    return None


def _as_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_iso_date(value: Any) -> Optional[dt.date]:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return dt.datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_csv_list(value: Any) -> List[str]:
    if isinstance(value, str):
        parts = [p.strip() for p in value.split(",")]
    elif isinstance(value, Sequence):
        parts = [str(p).strip() for p in value]
    else:
        parts = []
    seen: List[str] = []
    for part in parts:
        if part and part not in seen:
            seen.append(part)
    return seen


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except Exception:
        return None
