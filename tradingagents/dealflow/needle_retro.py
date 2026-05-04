"""Recent realized false-negative audit for needle-finding improvements."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from .hindsight import _DEAL_FLOW_DIR, _PLANS_DIR, compute_hindsight
from .why_missed import _X_FEED_DIR, audit_ticker_run

_MAX_COMPLETED_CYCLES = 5


def _recent_cycle_dates(base_dir: Path) -> List[str]:
    if not Path(base_dir).is_dir():
        return []
    return sorted(
        [
            path.name
            for path in Path(base_dir).iterdir()
            if path.is_dir() and len(path.name) == 10 and path.name.count("-") == 2
        ],
        reverse=True,
    )


def _stage_summary(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        key = str(row.get("improvement_target") or "unknown")
        grouped.setdefault(key, []).append(row)

    summary: List[Dict[str, Any]] = []
    for key, items in grouped.items():
        edges = [float(item.get("edge_vs_benchmark_5d") or 0.0) for item in items]
        total_edge = round(sum(edges), 6)
        summary.append(
            {
                "improvement_target": key,
                "count": len(items),
                "avg_edge_5d": round(total_edge / float(len(items)), 6) if items else 0.0,
                "total_edge_5d": total_edge,
            }
        )
    summary.sort(key=lambda row: (-float(row.get("total_edge_5d") or 0.0), str(row.get("improvement_target", ""))))
    return summary


def compute_needle_retro(
    *,
    last: int = _MAX_COMPLETED_CYCLES,
    base_dir: Path = _DEAL_FLOW_DIR,
    plans_base_dir: Path = _PLANS_DIR,
    x_feed_base_dir: Path = _X_FEED_DIR,
    benchmark: str = "QQQ",
    min_edge: float = 0.03,
    hurdle: float = 62.0,
) -> Dict[str, Any]:
    """Review the last completed cycles and surface true false negatives."""
    requested = max(1, min(int(last or _MAX_COMPLETED_CYCLES), _MAX_COMPLETED_CYCLES))
    completed_cycles: List[Dict[str, Any]] = []
    opportunities: List[Dict[str, Any]] = []

    for source_date in _recent_cycle_dates(base_dir):
        if len(completed_cycles) >= requested:
            break
        try:
            hindsight = compute_hindsight(source_date=source_date, benchmark=benchmark)
        except FileNotFoundError:
            continue
        if hindsight.get("error"):
            continue

        benchmark_return = hindsight.get("benchmark_return_5d")
        completed_cycles.append(
            {
                "source_date": source_date,
                "status": "COMPLETED",
                "benchmark_return_5d": benchmark_return,
            }
        )
        for ticker_row in hindsight.get("ticker_returns", []):
            if not isinstance(ticker_row, dict):
                continue
            if str(ticker_row.get("cohort", "")).upper() == "DEPLOYED":
                continue
            ret = ticker_row.get("return_5d")
            if ret is None or benchmark_return is None:
                continue
            edge = round(float(ret) - float(benchmark_return), 6)
            if edge < float(min_edge):
                continue

            audit = audit_ticker_run(
                str(ticker_row.get("ticker", "")),
                source_date,
                base_dir=base_dir,
                x_feed_base_dir=x_feed_base_dir,
                plans_base_dir=plans_base_dir,
                hurdle=hurdle,
                benchmark=benchmark,
                include_forward_returns=False,
            )
            if str(audit.get("root_cause", "")).upper() == "PIPELINE_NOT_RUN":
                continue
            merged = dict(audit)
            merged.update(
                {
                    "ticker": str(ticker_row.get("ticker", "")),
                    "cohort": str(ticker_row.get("cohort", "")),
                    "return_5d": float(ret),
                    "benchmark_return_5d": float(benchmark_return),
                    "edge_vs_benchmark_5d": edge,
                }
            )
            opportunities.append(merged)

    opportunities.sort(
        key=lambda row: (
            -float(row.get("edge_vs_benchmark_5d") or 0.0),
            -int(str(row.get("source_date", "0")).replace("-", "") or 0),
            str(row.get("ticker", "")),
        )
    )

    return {
        "cycles_requested": requested,
        "cycles_completed": len(completed_cycles),
        "benchmark": benchmark,
        "min_edge": float(min_edge),
        "cycles": completed_cycles,
        "opportunities": opportunities,
        "stage_summary": _stage_summary(opportunities),
    }
