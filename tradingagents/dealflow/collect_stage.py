"""Scout-only collection stage for dealflow pipeline."""

from __future__ import annotations

import datetime as dt
from typing import Any, Dict, List, Tuple

from .contracts import EventTriggerResult
from .scout_ticker_summary import persist_scout_ticker_summary


def run_collect_stage(
    pipeline: Any,
    *,
    as_of_date: str,
    trigger: str,
    top_k: int,  # kept for legacy CLI/API compatibility; no ranking uses it.
    akg_available: bool,
    akg_cls: Any,
    deps: Dict[str, Any] | None = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], List[dict], EventTriggerResult]:
    del top_k, akg_available, akg_cls, deps

    summary = getattr(pipeline, "_last_scout_ticker_summary", None)
    if summary is None:
        pipeline.discover(as_of_date=as_of_date, trigger=trigger)
        summary = getattr(pipeline, "_last_scout_ticker_summary", None)
    summary = dict(summary or {})
    summary.setdefault("date", as_of_date)
    summary["run_id"] = f"{as_of_date}-{dt.datetime.now().strftime('%H%M%S')}-{trigger}"
    summary["trigger"] = trigger

    event_state = getattr(pipeline, "_last_event_state", None)
    if event_state is None:
        event_state = pipeline._evaluate_event_trigger(as_of_date)
    summary["event_triggered"] = bool(event_state.get("triggered"))
    summary["event_reasons"] = list(event_state.get("reasons", []) or [])

    persist_scout_ticker_summary(summary)
    pipeline._last_scout_ticker_summary = summary
    return summary, {}, [], event_state
