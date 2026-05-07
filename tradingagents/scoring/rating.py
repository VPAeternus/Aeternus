"""Rating label and score clamp helpers for Aeternus scoring."""

from __future__ import annotations

from typing import Any


def clamp_score(value: Any) -> int:
    try:
        num = int(round(float(value)))
    except (TypeError, ValueError):
        return 50
    return max(0, min(100, num))


def rating_from_score(score: float) -> str:
    if score >= 80:
        return "Strong Buy"
    if score >= 60:
        return "Buy"
    if score >= 40:
        return "Hold"
    if score >= 20:
        return "Sell"
    return "Strong Sell"
