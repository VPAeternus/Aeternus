from __future__ import annotations

from typing import Any


def clean(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def to_float(value: Any) -> float | None:
    text = clean(value).replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def to_int(value: Any, default: int = 0) -> int:
    number = to_float(value)
    if number is None:
        return default
    return int(number)


def flag(value: Any) -> bool:
    return clean(value).lower() in {"1", "true", "yes", "y"}


def clamp(value: float, lo: int = 0, hi: int = 100) -> int:
    return int(max(lo, min(hi, value)))


def prior_quarter(quarter: str) -> str:
    year_text, q_text = clean(quarter).split("Q", maxsplit=1)
    year = int(year_text)
    quarter_num = int(q_text)
    if quarter_num == 1:
        return f"{year - 1}Q4"
    return f"{year}Q{quarter_num - 1}"
