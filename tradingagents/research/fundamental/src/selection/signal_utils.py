"""Shared signal helpers for deterministic fundamental selectors."""
from __future__ import annotations

from typing import Any, Mapping, Sequence

RM_SIGNAL_FIELDS = (
    "rm1_low_price_dislocation_momentum",
    "rm2_weak_acceleration",
    "rm3_mid_price_dislocation_momentum",
    "rm4_persistent_repricing_wave",
    "rm_buy_review_flag",
)

HP_SIGNAL_FIELDS = (
    "hp0_high_price_broad",
    "hp1_quality_pullback",
    "hp2_dislocation_momentum_priority",
    "hp2_dislocation_momentum_watch",
    "hp3_large_quality_theme_exception",
    "hp4_score_reacceleration_watch",
    "hp_production_extension",
    "hp_research_extension",
    "hp_LLM_best",
)


def to_float(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def truthy(value: Any) -> bool:
    text = str(value if value is not None else "").strip().lower()
    if text in {"", "nan", "none", "null", "false", "no", "n", "low", "0"}:
        return False
    numeric = to_float(text)
    if numeric is not None:
        return numeric != 0
    return text in {"1", "true", "yes", "y", "high", "priority", "t5_rescan"}


def signal_count(row: Mapping[str, Any], fields: Sequence[str]) -> int:
    return len([field for field in fields if field in row and truthy(row.get(field))])


_FALSE_LABELS = {"", "0", "0.0", "false", "no", "n", "none", "null", "nan", "na", "n/a"}


def label_active(value: Any) -> bool:
    text = str(value if value is not None else "").strip().lower()
    return text not in _FALSE_LABELS


def label_signal_count(row: Mapping[str, Any], fields: Sequence[str]) -> int:
    return len([field for field in fields if field in row and label_active(row.get(field))])


def signal_bucket(row: Mapping[str, Any], fields: Sequence[str]) -> tuple[str, list[str]]:
    active = [field for field in fields if field in row and truthy(row.get(field))]
    if len(active) >= 2:
        return "2+", active
    return str(len(active)), active


def rm_signal_bucket(row: Mapping[str, Any]) -> str:
    return signal_bucket(row, RM_SIGNAL_FIELDS)[0]


def hp_signal_bucket(row: Mapping[str, Any]) -> str:
    return signal_bucket(row, HP_SIGNAL_FIELDS)[0]
