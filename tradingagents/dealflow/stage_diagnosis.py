"""Rolling operator diagnosis for funnel-stage summaries."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .hindsight import _DEAL_FLOW_DIR

_DATE_DIR_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ARTIFACT_ORDER = ("performance_review.json", "hindsight.json")


def compute_stage_diagnosis(
    *,
    base_dir: Path | None = None,
    last: int = 20,
    lane: str = "shared",
    top: int = 5,
) -> dict[str, Any]:
    root = Path(base_dir or _DEAL_FLOW_DIR)
    cycle_dirs = _recent_cycle_dirs(root=root, last=last)

    cycle_summaries: list[dict[str, Any]] = []
    stage_entries: list[dict[str, Any]] = []
    for cycle_dir in cycle_dirs:
        loaded = _load_cycle_summary(cycle_dir=cycle_dir, lane=lane)
        if not loaded:
            continue
        cycle_summaries.append(
            {
                "source_date": cycle_dir.name,
                "artifact": loaded["artifact"],
                "stage_count": len(loaded["stages"]),
            }
        )
        for stage in loaded["stages"]:
            stage_entries.append(
                {
                    "source_date": cycle_dir.name,
                    "stage_id": str(stage.get("stage_id", "")).strip(),
                    "kept_count": int(stage.get("kept_count", 0) or 0),
                    "dropped_count": int(stage.get("dropped_count", 0) or 0),
                    "edge_5d": _as_float_or_none(stage.get("edge_5d")),
                    "edge_20d": _as_float_or_none(stage.get("edge_20d")),
                    "edge_3m": _as_float_or_none(stage.get("edge_3m")),
                    "future_winner_recall": _as_float_or_none(stage.get("future_winner_recall")),
                    "false_negative_cost": _as_float_or_none(stage.get("false_negative_cost")),
                    "sample_size": _as_int_or_none(stage.get("sample_size")),
                }
            )

    aggregated_stages = _aggregate_stage_entries(stage_entries)
    worst_cycles = sorted(
        [entry for entry in stage_entries if entry.get("false_negative_cost") is not None],
        key=lambda entry: (
            -float(entry.get("false_negative_cost") or 0.0),
            str(entry.get("source_date", "")),
            str(entry.get("stage_id", "")),
        ),
    )[: max(int(top), 1)]

    return {
        "lane": str(lane),
        "cycles_considered": len(cycle_summaries),
        "cycles": cycle_summaries,
        "stages": aggregated_stages[: max(int(top), 1)],
        "worst_cycles": worst_cycles,
        "diagnosis": _build_diagnosis(aggregated_stages),
    }


def _recent_cycle_dirs(*, root: Path, last: int) -> list[Path]:
    if not root.exists():
        return []
    candidates = [
        path
        for path in root.iterdir()
        if path.is_dir() and _DATE_DIR_PATTERN.match(path.name)
    ]
    candidates.sort(key=lambda path: path.name, reverse=True)
    return candidates[: max(int(last), 1)]


def _load_cycle_summary(*, cycle_dir: Path, lane: str) -> dict[str, Any] | None:
    for artifact_name in _ARTIFACT_ORDER:
        artifact_path = cycle_dir / artifact_name
        if not artifact_path.exists():
            continue
        try:
            payload = json.loads(artifact_path.read_text())
        except Exception:
            continue
        summary = payload.get("hypothesis_stage_summary")
        if not isinstance(summary, dict):
            continue
        if str(summary.get("lane", "")).strip() != str(lane).strip():
            continue
        stages = summary.get("stages")
        if not isinstance(stages, list) or not stages:
            continue
        return {
            "artifact": artifact_name,
            "stages": stages,
        }
    return None


def _aggregate_stage_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        stage_id = str(entry.get("stage_id", "")).strip()
        if not stage_id:
            continue
        grouped.setdefault(stage_id, []).append(entry)

    aggregated: list[dict[str, Any]] = []
    for stage_id, stage_entries in grouped.items():
        false_negative_values = [
            float(entry["false_negative_cost"])
            for entry in stage_entries
            if entry.get("false_negative_cost") is not None
        ]
        recall_values = [
            float(entry["future_winner_recall"])
            for entry in stage_entries
            if entry.get("future_winner_recall") is not None
        ]
        edge_5d_values = [
            float(entry["edge_5d"])
            for entry in stage_entries
            if entry.get("edge_5d") is not None
        ]
        edge_20d_values = [
            float(entry["edge_20d"])
            for entry in stage_entries
            if entry.get("edge_20d") is not None
        ]
        edge_3m_values = [
            float(entry["edge_3m"])
            for entry in stage_entries
            if entry.get("edge_3m") is not None
        ]
        worst_cycle = max(
            stage_entries,
            key=lambda entry: (
                float(entry.get("false_negative_cost") or float("-inf")),
                str(entry.get("source_date", "")),
            ),
        )
        total_false_negative_cost = round(sum(false_negative_values), 4) if false_negative_values else 0.0
        aggregated_row = {
            "stage_id": stage_id,
            "cycles_seen": len(stage_entries),
            "sample_cycles": sum(
                1
                for entry in stage_entries
                if entry.get("sample_size") is not None and int(entry["sample_size"]) > 0
            ),
            "avg_edge_5d": _avg_or_none(edge_5d_values),
            "avg_edge_20d": _avg_or_none(edge_20d_values),
            "avg_edge_3m": _avg_or_none(edge_3m_values),
            "avg_recall": _avg_or_none(recall_values),
            "total_false_negative_cost": total_false_negative_cost,
            "avg_false_negative_cost": (
                round(total_false_negative_cost / float(len(false_negative_values)), 4)
                if false_negative_values
                else 0.0
            ),
            "worst_cycle_date": str(worst_cycle.get("source_date", "")),
            "worst_cycle_false_negative_cost": _as_float_or_none(worst_cycle.get("false_negative_cost")) or 0.0,
        }
        aggregated_row["priority_score"] = _priority_score(aggregated_row)
        aggregated.append(aggregated_row)

    aggregated.sort(
        key=lambda row: (
            -float(row.get("priority_score") or 0.0),
            -float(row.get("total_false_negative_cost") or 0.0),
            str(row.get("stage_id", "")),
        )
    )
    return aggregated


def _priority_score(row: dict[str, Any]) -> float:
    total_false_negative_cost = max(float(row.get("total_false_negative_cost") or 0.0), 0.0)
    avg_recall = row.get("avg_recall")
    avg_edge_20d = row.get("avg_edge_20d")
    avg_edge_3m = row.get("avg_edge_3m")
    avg_edge_5d = row.get("avg_edge_5d")

    recall_penalty = 0.0
    if avg_recall is not None:
        recall_penalty = max(0.0, 0.75 - float(avg_recall)) * 40.0

    edge_penalty = 0.0
    if avg_edge_20d is not None:
        edge_penalty += max(0.0, -float(avg_edge_20d)) * 75.0
    elif avg_edge_3m is not None:
        edge_penalty += max(0.0, -float(avg_edge_3m)) * 100.0
    elif avg_edge_5d is not None:
        edge_penalty += max(0.0, -float(avg_edge_5d)) * 25.0

    return round((total_false_negative_cost * 100.0) + recall_penalty + edge_penalty, 2)


def _build_diagnosis(stages: list[dict[str, Any]]) -> str:
    if not stages:
        return "No stage summaries found in the requested cycles."

    first = stages[0]
    reasons: list[str] = []
    if float(first.get("total_false_negative_cost") or 0.0) > 0.0:
        reasons.append("highest cumulative false-negative cost")
    avg_recall = first.get("avg_recall")
    if avg_recall is not None:
        recall_value = float(avg_recall)
        if recall_value < 0.5:
            reasons.append("sub-50% recall")
        elif recall_value < 0.7:
            reasons.append("weak recall")
    avg_edge_20d = first.get("avg_edge_20d")
    avg_edge_3m = first.get("avg_edge_3m")
    avg_edge_5d = first.get("avg_edge_5d")
    if avg_edge_20d is not None and float(avg_edge_20d) <= 0.0:
        reasons.append("non-positive 20d edge")
    elif avg_edge_3m is not None and float(avg_edge_3m) <= 0.0:
        reasons.append("non-positive 3m edge")
    elif avg_edge_5d is not None and float(avg_edge_5d) <= 0.0:
        reasons.append("non-positive 5d edge")

    if not reasons:
        reasons.append("highest current priority score")

    return f"Inspect {first['stage_id']} first: {', '.join(reasons)}."


def _avg_or_none(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / float(len(values)), 4)


def _as_float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value), 4)
    except Exception:
        return None


def _as_int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None
