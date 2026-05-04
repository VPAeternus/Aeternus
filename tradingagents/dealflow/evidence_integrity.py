"""Read-only evidence integrity classification for Step 2 candidates."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, Iterable, List

from .scoring import GATING_FAMILIES


INTEGRITY_CLASSES = ("CONFIRMED", "SPARSE_BUT_INTERESTING", "DATA_DEGRADED", "LOW_SIGNAL")


def build_evidence_integrity_report(
    candidates: Iterable[Dict[str, Any]],
    signals: Iterable[Dict[str, Any]],
    connector_health: Iterable[Dict[str, Any]],
    rule_snapshot: Dict[str, Any],
) -> Dict[str, Any]:
    candidate_list = list(candidates)
    signal_list = list(signals)
    connector_rows = list(connector_health)

    signals_by_symbol_family: Dict[str, Dict[str, List[Dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for sig in signal_list:
        symbol = str(sig.get("symbol", "")).upper().strip()
        family = str(sig.get("signal_family", "")).strip()
        if not symbol or not family:
            continue
        signals_by_symbol_family[symbol][family].append(sig)

    degraded_families_by_run = _degraded_families(connector_rows)
    records: List[Dict[str, Any]] = []
    class_counts = {name: 0 for name in INTEGRITY_CLASSES}

    min_signal_families = int(rule_snapshot.get("min_signal_families", 3) or 3)
    min_evidence_count = int(rule_snapshot.get("min_evidence_count", 5) or 5)

    for candidate in candidate_list:
        record = _build_candidate_record(
            candidate=candidate,
            family_signals=signals_by_symbol_family.get(str(candidate.get("symbol", "")).upper().strip(), {}),
            degraded_families_by_run=degraded_families_by_run,
            min_signal_families=min_signal_families,
            min_evidence_count=min_evidence_count,
        )
        records.append(record)
        class_counts[record["integrity_class"]] += 1

    top_sparse = sorted(
        [r for r in records if r["integrity_class"] == "SPARSE_BUT_INTERESTING"],
        key=lambda row: (-float(row["asymmetry_score"]), row["symbol"]),
    )[:10]
    top_degraded = sorted(
        [r for r in records if r["integrity_class"] == "DATA_DEGRADED"],
        key=lambda row: (-float(row["degradation_score"]), row["symbol"]),
    )[:10]

    return {
        "rule_snapshot": {
            "min_signal_families": min_signal_families,
            "min_evidence_count": min_evidence_count,
        },
        "class_counts": class_counts,
        "candidate_records": records,
        "top_sparse_but_interesting": top_sparse,
        "top_data_degraded": top_degraded,
        "connector_context": {
            "connectors_total": len(connector_rows),
            "degraded_families": sorted(degraded_families_by_run),
        },
    }


def summarize_evidence_integrity(report: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "class_counts": dict(report.get("class_counts", {})),
        "record_count": len(report.get("candidate_records", [])),
        "top_sparse_but_interesting": [
            {
                "symbol": row.get("symbol"),
                "integrity_class": row.get("integrity_class"),
                "asymmetry_score": row.get("asymmetry_score"),
            }
            for row in report.get("top_sparse_but_interesting", [])
        ],
        "top_data_degraded": [
            {
                "symbol": row.get("symbol"),
                "integrity_class": row.get("integrity_class"),
                "degradation_score": row.get("degradation_score"),
            }
            for row in report.get("top_data_degraded", [])
        ],
    }


def _round_metric(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value), 4)
    except Exception:
        return None


def _mean(values: Iterable[float]) -> float | None:
    items = [float(value) for value in values]
    if not items:
        return None
    return sum(items) / float(len(items))


def _cohort_metrics(
    *,
    symbols: List[str],
    shortlist_symbols: set[str],
    deep_selection_symbols: set[str],
    forward_returns_by_horizon: Dict[str, Dict[str, float]],
    benchmark_returns_by_horizon: Dict[str, float | None],
) -> Dict[str, Any]:
    metrics: Dict[str, Any] = {"count": len(symbols)}
    symbol_set = {str(symbol).upper().strip() for symbol in symbols if str(symbol).upper().strip()}
    shortlist_conversion = (
        len(symbol_set & shortlist_symbols) / float(len(symbol_set))
        if symbol_set
        else None
    )
    deep_selection_conversion = (
        len(symbol_set & deep_selection_symbols) / float(len(symbol_set))
        if symbol_set
        else None
    )
    metrics["shortlist_conversion"] = _round_metric(shortlist_conversion)
    metrics["deep_selection_conversion"] = _round_metric(deep_selection_conversion)

    for horizon, returns_map in forward_returns_by_horizon.items():
        returns = [
            float(returns_map[symbol])
            for symbol in sorted(symbol_set)
            if symbol in returns_map and returns_map[symbol] is not None
        ]
        mean_return = _mean(returns)
        benchmark_return = benchmark_returns_by_horizon.get(horizon)
        edge = (
            float(mean_return) - float(benchmark_return)
            if mean_return is not None and benchmark_return is not None
            else None
        )
        metrics[f"mean_return_{horizon}"] = _round_metric(mean_return)
        metrics[f"edge_vs_benchmark_{horizon}"] = _round_metric(edge)
    return metrics


def build_evidence_integrity_scorecards(
    *,
    evidence_integrity: Dict[str, Any] | None,
    step2_symbols: List[str],
    shortlist_symbols: List[str],
    deep_selection_symbols: List[str],
    forward_returns_by_horizon: Dict[str, Dict[str, float]],
    benchmark_returns_by_horizon: Dict[str, float | None],
) -> Dict[str, Any]:
    candidate_records = list((evidence_integrity or {}).get("candidate_records", []) or [])
    shortlist_set = {
        str(symbol).upper().strip()
        for symbol in shortlist_symbols
        if str(symbol).upper().strip()
    }
    deep_selection_set = {
        str(symbol).upper().strip()
        for symbol in deep_selection_symbols
        if str(symbol).upper().strip()
    }
    step2_list = [
        str(symbol).upper().strip()
        for symbol in step2_symbols
        if str(symbol).upper().strip()
    ]

    step2_baseline = _cohort_metrics(
        symbols=step2_list,
        shortlist_symbols=shortlist_set,
        deep_selection_symbols=deep_selection_set,
        forward_returns_by_horizon=forward_returns_by_horizon,
        benchmark_returns_by_horizon=benchmark_returns_by_horizon,
    )

    cohorts: Dict[str, Dict[str, Any]] = {}
    for class_name in INTEGRITY_CLASSES:
        class_symbols = [
            str(row.get("symbol", "")).upper().strip()
            for row in candidate_records
            if str(row.get("integrity_class", "")).upper() == class_name
            and str(row.get("symbol", "")).upper().strip()
        ]
        cohorts[class_name] = _cohort_metrics(
            symbols=class_symbols,
            shortlist_symbols=shortlist_set,
            deep_selection_symbols=deep_selection_set,
            forward_returns_by_horizon=forward_returns_by_horizon,
            benchmark_returns_by_horizon=benchmark_returns_by_horizon,
        )

    def _metric_keys() -> List[str]:
        keys = ["shortlist_conversion", "deep_selection_conversion"]
        for horizon in forward_returns_by_horizon.keys():
            keys.append(f"mean_return_{horizon}")
            keys.append(f"edge_vs_benchmark_{horizon}")
        return keys

    comparisons = {
        "vs_step2_baseline": {},
        "vs_other_cohorts": {},
    }

    for class_name in INTEGRITY_CLASSES:
        current = cohorts[class_name]
        vs_baseline: Dict[str, Any] = {}
        vs_peers: Dict[str, Any] = {}
        peer_metrics = [cohorts[name] for name in INTEGRITY_CLASSES if name != class_name and cohorts[name]["count"] > 0]
        for key in _metric_keys():
            baseline_value = step2_baseline.get(key)
            current_value = current.get(key)
            baseline_delta = (
                float(current_value) - float(baseline_value)
                if current_value is not None and baseline_value is not None
                else None
            )
            peer_average = _mean(
                float(metric[key])
                for metric in peer_metrics
                if metric.get(key) is not None
            )
            peer_delta = (
                float(current_value) - float(peer_average)
                if current_value is not None and peer_average is not None
                else None
            )
            vs_baseline[f"{key}_delta"] = _round_metric(baseline_delta)
            vs_peers[f"{key}_delta"] = _round_metric(peer_delta)
        comparisons["vs_step2_baseline"][class_name] = vs_baseline
        comparisons["vs_other_cohorts"][class_name] = vs_peers

    return {
        "cohorts": cohorts,
        "step2_baseline": step2_baseline,
        "comparisons": comparisons,
    }


def _build_candidate_record(
    candidate: Dict[str, Any],
    family_signals: Dict[str, List[Dict[str, Any]]],
    degraded_families_by_run: set[str],
    min_signal_families: int,
    min_evidence_count: int,
) -> Dict[str, Any]:
    symbol = str(candidate.get("symbol", "")).upper().strip()
    active_families = int(candidate.get("active_families", 0) or 0)
    evidence_count = int(candidate.get("evidence_count", 0) or 0)
    freshness_hours = float(candidate.get("freshness_hours", 9999.0) or 9999.0)
    candidate_asymmetry = float(candidate.get("asymmetry_score", 0.0) or 0.0)

    ok_families = {
        family
        for family, sigs in family_signals.items()
        if any(str(sig.get("source_status", "")).upper() == "OK" for sig in sigs)
    }
    missing_families = [family for family in GATING_FAMILIES if family not in ok_families]
    degraded_families = sorted([family for family in missing_families if family in degraded_families_by_run])

    strong_families: List[str] = []
    for family, sigs in family_signals.items():
        strongest = max((float(sig.get("raw_score", 0.0) or 0.0) for sig in sigs if str(sig.get("source_status", "")).upper() == "OK"), default=0.0)
        if strongest >= 70.0:
            strong_families.append(family)
    strong_families = sorted(strong_families)

    breadth_score = min(1.0, active_families / float(max(1, min_signal_families)))
    evidence_score = min(1.0, evidence_count / float(max(1, min_evidence_count)))
    freshness_score = max(0.0, min(1.0, 1.0 - (freshness_hours / 168.0)))
    evidence_quality_score = round((evidence_score * 0.6) + (freshness_score * 0.4), 4)
    degradation_score = round(len(degraded_families) / float(max(1, len(missing_families))), 4) if missing_families else 0.0
    asymmetry_score = round(max(candidate_asymmetry / 100.0, 1.0 if strong_families else 0.0), 4)

    integrity_class = "LOW_SIGNAL"
    if breadth_score >= 1.0 and evidence_quality_score >= 0.5 and degradation_score < 0.5:
        integrity_class = "CONFIRMED"
    elif degraded_families and (degradation_score >= 0.34 or evidence_quality_score < 0.5) and (
        breadth_score < 1.0 or evidence_quality_score < 0.5
    ):
        integrity_class = "DATA_DEGRADED"
    elif asymmetry_score >= 0.65 and (breadth_score < 1.0 or str(candidate.get("status", "")).upper() == "LOW_DATA"):
        integrity_class = "SPARSE_BUT_INTERESTING"

    return {
        "symbol": symbol,
        "current_status": str(candidate.get("status", "UNKNOWN")).upper(),
        "integrity_class": integrity_class,
        "evidence_breadth_score": round(breadth_score, 4),
        "evidence_quality_score": evidence_quality_score,
        "degradation_score": degradation_score,
        "asymmetry_score": asymmetry_score,
        "missing_families": missing_families,
        "degraded_families": degraded_families,
        "strong_families": strong_families,
    }


def _degraded_families(connector_rows: Iterable[Dict[str, Any]]) -> set[str]:
    degraded: set[str] = set()
    for row in connector_rows:
        status = str(row.get("status", "")).upper()
        if status not in {"ERROR", "NOT_CONFIGURED"}:
            continue
        for family in row.get("signal_families", []) or []:
            name = str(family).strip()
            if name:
                degraded.add(name)
    return degraded
