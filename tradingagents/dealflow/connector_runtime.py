"""Connector execution and health summaries for dealflow collection."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from statistics import median
from typing import Any, Dict, List, Tuple


def collect_connector_signals(
    name: str,
    collector,
    *args,
    timeout_seconds: float = 45.0,
    max_attempts: int = 2,
    **kwargs,
) -> Tuple[List[Dict], Dict[str, Any]]:
    """Run a connector with retry/timeout and return signals plus health entry."""
    start = time.perf_counter()
    error_message = ""
    signals: List[Dict] = []
    max_attempts = max(1, int(max_attempts))
    for attempt in range(1, max_attempts + 1):
        try:
            payload = run_connector_with_timeout(
                collector,
                timeout_seconds=timeout_seconds,
                args=args,
                kwargs=kwargs,
            )
            signals = list(payload)
            error_message = ""
            break
        except Exception as exc:
            signals = []
            error_message = str(exc)
            if attempt < max_attempts:
                time.sleep(min(0.5, 0.15 * attempt))
    latency_ms = (time.perf_counter() - start) * 1000.0
    health = build_connector_health_entry(
        connector_name=name,
        signals=signals,
        latency_ms=latency_ms,
        error_message=error_message,
    )
    return signals, health


def run_connector_with_timeout(
    collector,
    timeout_seconds: float,
    args: tuple,
    kwargs: Dict[str, Any],
):
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        future = executor.submit(collector, *args, **kwargs)
        try:
            return future.result(timeout=max(0.01, float(timeout_seconds)))
        except FuturesTimeoutError as exc:
            future.cancel()
            raise TimeoutError(f"Connector timed out after {float(timeout_seconds):.1f}s") from exc
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def build_connector_health_entry(
    connector_name: str,
    signals: List[Dict],
    latency_ms: float,
    error_message: str = "",
    status_override: str | None = None,
    metadata: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    status_counts = {"OK": 0, "NO_DATA": 0, "ERROR": 0, "NOT_CONFIGURED": 0}
    evidence_total = 0
    freshness_ok: List[float] = []
    sources: set[str] = set()
    families: set[str] = set()

    for sig in signals:
        status = str(sig.get("source_status", "NO_DATA"))
        if status not in status_counts:
            status = "NO_DATA"
        status_counts[status] += 1
        evidence_total += int(sig.get("evidence_count", 0) or 0)

        source_name = str(sig.get("source_name", "") or "").strip()
        if source_name:
            sources.add(source_name)
        family = str(sig.get("signal_family", "") or "").strip()
        if family:
            families.add(family)

        if status == "OK":
            freshness_ok.append(float(sig.get("freshness_hours", 9999.0) or 9999.0))

    final_status = "NO_DATA"
    if status_override in {"OK", "NO_DATA", "ERROR", "NOT_CONFIGURED"}:
        final_status = status_override
    elif error_message:
        final_status = "ERROR"
    elif status_counts["OK"] > 0:
        final_status = "OK"
    elif status_counts["ERROR"] > 0:
        final_status = "ERROR"
    elif status_counts["NOT_CONFIGURED"] > 0 and status_counts["NO_DATA"] == 0:
        final_status = "NOT_CONFIGURED"

    signal_count = len(signals)
    ok_coverage_pct = 0.0
    if signal_count > 0:
        ok_coverage_pct = (status_counts["OK"] / float(signal_count)) * 100.0

    entry: Dict[str, Any] = {
        "connector": connector_name,
        "status": final_status,
        "latency_ms": float(round(latency_ms, 2)),
        "signal_count": signal_count,
        "status_counts": status_counts,
        "ok_coverage_pct": float(round(ok_coverage_pct, 2)),
        "evidence_total": int(evidence_total),
        "freshness_min_hours": float(round(min(freshness_ok), 4)) if freshness_ok else None,
        "freshness_median_hours": float(round(median(freshness_ok), 4)) if freshness_ok else None,
        "source_names": sorted(sources),
        "signal_families": sorted(families),
        "error": error_message if final_status == "ERROR" else "",
    }
    if metadata:
        entry.update(metadata)
    return entry


def summarize_connector_health(connector_health: List[Dict[str, Any]]) -> Dict[str, Any]:
    total = len(connector_health)
    status_totals = {"OK": 0, "NO_DATA": 0, "ERROR": 0, "NOT_CONFIGURED": 0}
    for row in connector_health:
        status = str(row.get("status", "NO_DATA"))
        if status not in status_totals:
            status = "NO_DATA"
        status_totals[status] += 1
    return {
        "connectors_total": total,
        "status_totals": status_totals,
        "degraded": status_totals["ERROR"] > 0,
        "not_configured": status_totals["NOT_CONFIGURED"],
    }
