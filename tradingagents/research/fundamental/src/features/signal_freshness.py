from __future__ import annotations

from datetime import date


def _to_date(value: str | date) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def trading_days_between(start: str | date, end: str | date) -> int:
    left = _to_date(start)
    right = _to_date(end)
    if right < left:
        return 0
    days = 0
    current = left
    while current < right:
        current = date.fromordinal(current.toordinal() + 1)
        if current.weekday() < 5:
            days += 1
    return days


def freshness_status(signal_age_days: int) -> str:
    if signal_age_days <= 5:
        return "fresh_signal"
    if signal_age_days <= 20:
        return "active_signal"
    if signal_age_days <= 45:
        return "aging_signal"
    if signal_age_days <= 90:
        return "stale_signal"
    return "expired_signal"


def compute_signal_freshness(tradable_date: str, as_of: str) -> dict[str, int | str]:
    age = trading_days_between(tradable_date, as_of)
    return {"signal_age_days": age, "signal_freshness_status": freshness_status(age)}
