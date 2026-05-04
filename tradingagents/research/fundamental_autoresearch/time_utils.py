from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


_ET = ZoneInfo("America/New_York")
_MARKET_CLOSE_HOUR = 16


def parse_sec_timestamp(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)


def _next_weekday(dt: datetime) -> datetime:
    current = dt
    while current.weekday() >= 5:
        current += timedelta(days=1)
    return current


def _next_trading_day(local_dt: datetime) -> datetime:
    next_day = local_dt + timedelta(days=1)
    return _next_weekday(next_day)


def compute_effective_market_date(
    accepted_at: str,
    *,
    assume_same_day_if_market_hours: bool = False,
) -> str:
    accepted_dt = parse_sec_timestamp(accepted_at).astimezone(_ET)
    accepted_dt = _next_weekday(accepted_dt)

    if (
        assume_same_day_if_market_hours
        and accepted_dt.weekday() < 5
        and accepted_dt.hour < _MARKET_CLOSE_HOUR
    ):
        return accepted_dt.date().isoformat()

    return _next_trading_day(accepted_dt).date().isoformat()
