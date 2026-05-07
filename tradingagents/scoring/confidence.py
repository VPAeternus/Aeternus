"""Confidence-factor helpers for Aeternus scoring."""

from __future__ import annotations

from typing import Any, Dict, Optional, Protocol


class TrackRecordLike(Protocol):
    def get_accuracy_by_sector(self, sector: str): ...
    def get_accuracy_by_confidence(self, confidence_level: int): ...


def is_nonempty(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, dict, set)):
        return len(value) > 0
    return bool(value)


def clamp_confidence(value: Any) -> int:
    try:
        num = int(round(float(value)))
    except (TypeError, ValueError):
        return 3
    return max(1, min(5, num))


def normalize_factor(value: Any, default: int = 3) -> int:
    try:
        num = float(value)
        if num > 5:
            num = num / 20.0
        return clamp_confidence(num)
    except (TypeError, ValueError):
        return default


def map_accuracy_to_factor(value: Any) -> int:
    if value is None:
        return 3
    try:
        num = float(value)
        if num > 1:
            num = num / 100.0
        num = max(0.0, min(1.0, num))
        return clamp_confidence(1 + (4 * num))
    except (TypeError, ValueError):
        return 3


def compute_data_quality_factor(state: Dict[str, Any]) -> int:
    keys = [
        "market_report",
        "news_report",
        "fundamentals_report",
        "investment_plan",
        "final_trade_decision",
    ]
    present = 0
    for key in keys:
        if is_nonempty(state.get(key)):
            present += 1
    return clamp_confidence(round(1 + (4 * present / len(keys))))


def compute_historical_accuracy_factor(
    track_record: Optional[TrackRecordLike],
    sector: Optional[str],
    confidence_level: int,
) -> int:
    if not track_record:
        return 3

    accuracy = None
    try:
        if sector and sector != "Unknown":
            accuracy = track_record.get_accuracy_by_sector(sector)
    except Exception:
        accuracy = None

    if accuracy is None:
        try:
            accuracy = track_record.get_accuracy_by_confidence(confidence_level)
        except Exception:
            accuracy = None

    return map_accuracy_to_factor(accuracy)


def compute_confidence_factors(
    state: Dict[str, Any],
    llm_data: Dict[str, Any],
    sector: Optional[str],
    price_target: Optional[float],
    catalyst: Optional[str],
    track_record: Optional[TrackRecordLike],
) -> Dict[str, int]:
    llm_factors = llm_data.get("confidence_factors", {}) or {}
    llm_confidence = normalize_factor(llm_data.get("confidence"), default=3)

    data_quality = compute_data_quality_factor(state)
    thesis_clarity = normalize_factor(
        llm_factors.get("thesis_clarity"),
        default=llm_confidence,
    )
    catalyst_default = 4 if (price_target is not None or is_nonempty(catalyst)) else 2
    catalyst_proximity = normalize_factor(
        llm_factors.get("catalyst_proximity"),
        default=catalyst_default,
    )
    historical_accuracy = compute_historical_accuracy_factor(
        track_record=track_record,
        sector=sector,
        confidence_level=llm_confidence,
    )

    return {
        "data_quality": data_quality,
        "thesis_clarity": thesis_clarity,
        "catalyst_proximity": catalyst_proximity,
        "historical_accuracy": historical_accuracy,
    }


def compute_weighted_confidence(factors: Dict[str, int]) -> int:
    weighted = (
        (factors["data_quality"] * 0.30)
        + (factors["thesis_clarity"] * 0.25)
        + (factors["catalyst_proximity"] * 0.25)
        + (factors["historical_accuracy"] * 0.20)
    )
    return clamp_confidence(round(weighted))
