"""Read-only discovery delta normalization for scouts and technical recall."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List


def _clamp_unit(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except Exception:
        return default
    if number < 0.0:
        return 0.0
    if number > 1.0:
        return 1.0
    return number


def _normalize_strength(value: Any) -> float:
    try:
        number = float(value)
    except Exception:
        return 0.0
    if number <= 1.0:
        return _clamp_unit(number)
    return _clamp_unit(number / 100.0)


def normalize_discovery_signals(
    *,
    scout_audit: Dict[str, Any] | None,
    fvg_recall: Dict[str, Any] | None,
    fma_recall: Dict[str, Any] | None,
) -> List[Dict[str, Any]]:
    signals: List[Dict[str, Any]] = []

    for row in list((scout_audit or {}).get("signals", []) or []):
        symbol = str(row.get("symbol", "")).upper().strip()
        if not symbol:
            continue
        novelty = _normalize_strength(row.get("raw_strength", 0.5))
        confidence = _clamp_unit(row.get("confidence_score", 0.6), default=0.6)
        signals.append(
            {
                "symbol": symbol,
                "source": str(row.get("source", "scout")).strip() or "scout",
                "channel_type": "scout",
                "delta_kind": str(row.get("delta_kind", "scout_signal")).strip() or "scout_signal",
                "direction": str(row.get("direction", "NEUTRAL")).strip() or "NEUTRAL",
                "raw_strength": novelty,
                "novelty_score": novelty,
                "persistence_score": 0.55,
                "confidence_score": confidence,
                "tags": list(row.get("tags", []) or []),
            }
        )

    for row in list((fvg_recall or {}).get("rows", []) or []):
        symbol = str(row.get("symbol", "")).upper().strip()
        if not symbol:
            continue
        novelty = _normalize_strength(row.get("score", 0.0))
        signals.append(
            {
                "symbol": symbol,
                "source": "fvg_recall",
                "channel_type": "technical_recall",
                "delta_kind": "fvg_recall",
                "direction": "BULLISH",
                "raw_strength": novelty,
                "novelty_score": novelty,
                "persistence_score": 0.7,
                "confidence_score": max(0.55, novelty),
                "tags": [str(row.get("bucket", "fvg_recall")).strip() or "fvg_recall"],
            }
        )

    for row in list((fma_recall or {}).get("rows", []) or []):
        symbol = str(row.get("symbol", "")).upper().strip()
        if not symbol:
            continue
        novelty = _normalize_strength(row.get("score", 0.0))
        signals.append(
            {
                "symbol": symbol,
                "source": "fma_recall",
                "channel_type": "technical_recall",
                "delta_kind": "fma_recall",
                "direction": "BULLISH",
                "raw_strength": novelty,
                "novelty_score": novelty,
                "persistence_score": 0.65,
                "confidence_score": max(0.55, novelty),
                "tags": [str(row.get("bucket", "fma_recall")).strip() or "fma_recall"],
            }
        )

    return signals


def build_discovery_delta(
    *,
    as_of_date: str,
    scout_audit: Dict[str, Any] | None,
    fvg_recall: Dict[str, Any] | None,
    fma_recall: Dict[str, Any] | None,
) -> Dict[str, Any]:
    signals = normalize_discovery_signals(
        scout_audit=scout_audit,
        fvg_recall=fvg_recall,
        fma_recall=fma_recall,
    )

    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for signal in signals:
        grouped.setdefault(signal["symbol"], []).append(signal)

    symbol_records: List[Dict[str, Any]] = []
    for symbol, rows in grouped.items():
        channel_types = {str(row.get("channel_type", "")).strip() for row in rows if str(row.get("channel_type", "")).strip()}
        channel_count = len(channel_types)
        novelty = max(float(row.get("novelty_score", 0.0) or 0.0) for row in rows)
        persistence = sum(float(row.get("persistence_score", 0.0) or 0.0) for row in rows) / float(len(rows))
        confidence = sum(float(row.get("confidence_score", 0.0) or 0.0) for row in rows) / float(len(rows))
        orthogonality = min(1.0, channel_count / 2.0)
        delta_score = round(
            (
                0.35 * novelty
                + 0.25 * orthogonality
                + 0.20 * persistence
                + 0.20 * confidence
            )
            * 100.0,
            2,
        )
        technical_only = channel_types == {"technical_recall"}
        scout_only = channel_types == {"scout"}
        multi_channel = channel_count >= 2
        tags: List[str] = []
        for row in rows:
            tags.extend(list(row.get("tags", []) or []))
        record = {
            "symbol": symbol,
            "sources_fired": sorted({str(row.get("source", "")).strip() for row in rows if str(row.get("source", "")).strip()}),
            "independent_channel_count": channel_count,
            "novelty_score": round(novelty, 4),
            "persistence_score": round(persistence, 4),
            "orthogonality_score": round(orthogonality, 4),
            "confidence_score": round(confidence, 4),
            "delta_score": delta_score,
            "technical_only": technical_only,
            "scout_only": scout_only,
            "multi_channel": multi_channel,
            "theme_tags": [],
            "delta_tags": sorted(set(tags)),
        }
        symbol_records.append(record)

    symbol_records.sort(key=lambda row: (-float(row.get("delta_score", 0.0)), row["symbol"]))
    cohorts = {
        "scout_only": sorted([row["symbol"] for row in symbol_records if row["scout_only"]]),
        "technical_only": sorted([row["symbol"] for row in symbol_records if row["technical_only"]]),
        "multi_channel": sorted([row["symbol"] for row in symbol_records if row["multi_channel"]]),
    }
    top_delta_symbols = [
        {
            "symbol": row["symbol"],
            "delta_score": row["delta_score"],
            "sources_fired": list(row["sources_fired"]),
            "independent_channel_count": row["independent_channel_count"],
        }
        for row in symbol_records[:10]
    ]
    return {
        "as_of_date": as_of_date,
        "rule_snapshot": {
            "scoring_weights": {
                "novelty": 0.35,
                "orthogonality": 0.25,
                "persistence": 0.20,
                "confidence": 0.20,
            },
            "read_only": True,
            "inputs": ["scout_audit", "fvg_recall", "fma_recall"],
        },
        "signals": signals,
        "symbol_records": symbol_records,
        "top_delta_symbols": top_delta_symbols,
        "coverage_summary": {
            "signal_count": len(signals),
            "record_count": len(symbol_records),
        },
        "cohorts": cohorts,
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


def build_discovery_delta_cohort_scorecards(
    *,
    discovery_delta: Dict[str, Any] | None,
    step1_symbols: List[str],
    shortlist_symbols: List[str],
    deep_selection_symbols: List[str],
    forward_returns_by_horizon: Dict[str, Dict[str, float]],
    benchmark_returns_by_horizon: Dict[str, float | None],
) -> Dict[str, Any]:
    cohort_names = ("scout_only", "technical_only", "multi_channel")
    cohorts_input = dict((discovery_delta or {}).get("cohorts", {}) or {})
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
    step1_list = [
        str(symbol).upper().strip()
        for symbol in step1_symbols
        if str(symbol).upper().strip()
    ]
    step1_baseline = _cohort_metrics(
        symbols=step1_list,
        shortlist_symbols=shortlist_set,
        deep_selection_symbols=deep_selection_set,
        forward_returns_by_horizon=forward_returns_by_horizon,
        benchmark_returns_by_horizon=benchmark_returns_by_horizon,
    )

    cohorts: Dict[str, Dict[str, Any]] = {}
    for cohort_name in cohort_names:
        cohort_symbols = [
            str(symbol).upper().strip()
            for symbol in list(cohorts_input.get(cohort_name, []) or [])
            if str(symbol).upper().strip()
        ]
        cohorts[cohort_name] = _cohort_metrics(
            symbols=cohort_symbols,
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
        "vs_step1_baseline": {},
        "vs_other_cohorts": {},
    }

    for cohort_name in cohort_names:
        current = cohorts[cohort_name]
        vs_baseline: Dict[str, Any] = {}
        vs_peers: Dict[str, Any] = {}
        peer_metrics = [cohorts[name] for name in cohort_names if name != cohort_name and cohorts[name]["count"] > 0]
        for key in _metric_keys():
            baseline_value = step1_baseline.get(key)
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
        comparisons["vs_step1_baseline"][cohort_name] = vs_baseline
        comparisons["vs_other_cohorts"][cohort_name] = vs_peers

    return {
        "cohorts": cohorts,
        "step1_baseline": step1_baseline,
        "comparisons": comparisons,
    }
