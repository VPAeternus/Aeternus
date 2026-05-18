from __future__ import annotations

from datetime import date
from typing import Any, Iterable

from tradingagents.research.fundamental.src.features.common import clean


def first_trading_session_after(price_rows: Iterable[dict[str, Any]], value: Any) -> str:
    decision = _parse_date(value)
    sessions = sorted(
        {
            str(row.get("date", ""))[:10]
            for row in price_rows
            if clean(row.get("date")) and clean(row.get("open"))
        }
    )
    for session in sessions:
        parsed = _parse_date(session)
        if parsed and decision and parsed > decision:
            return session
    return ""


def resolve_entry_open(
    ticker: str,
    decision_date: Any,
    price_rows: Iterable[dict[str, Any]],
    *,
    expected_market_sessions: list[str] | None = None,
) -> dict[str, Any]:
    symbol = str(ticker or "").upper()
    ticker_rows = sorted(
        [
            row for row in price_rows
            if str(row.get("ticker", "")).upper() == symbol
            and clean(row.get("date"))
            and clean(row.get("open"))
        ],
        key=lambda row: str(row.get("date", "")),
    )
    expected_sessions = sorted(session for session in (expected_market_sessions or []) if _parse_date(session))
    if expected_sessions:
        decision = _parse_date(decision_date)
        expected = next((session for session in expected_sessions if decision and _parse_date(session) and _parse_date(session) > decision), "")
    else:
        expected = first_trading_session_after(ticker_rows, decision_date)

    match = next((row for row in ticker_rows if expected and str(row.get("date", ""))[:10] >= expected), None)
    if match is None:
        return {
            "entry_open_date": "",
            "entry_open": "",
            "entry_open_source": "",
            "entry_price_calendar_source": "ticker_price_cache",
            "expected_market_session_after_decision": expected,
            "entry_open_gap_sessions": "",
            "entry_date_adjustment_reason": "missing_entry_open",
            "tradable_date": "",
            "tradable_date_alias_source": "",
        }

    entry_date = str(match.get("date", ""))[:10]
    gap = _session_gap(expected_sessions, expected, entry_date) if expected_sessions else 0
    raw_open = match.get("open", "")
    adjusted_open = match.get("adj_open", raw_open)
    return {
        "entry_open_date": entry_date,
        "entry_open": raw_open,
        "entry_open_source": "price_cache_open",
        "entry_price_calendar_source": "ticker_price_cache",
        "expected_market_session_after_decision": expected,
        "entry_open_gap_sessions": gap,
        "entry_date_adjustment_reason": "" if gap == 0 else "missing_ticker_price",
        "tradable_date": entry_date,
        "tradable_date_alias_source": "entry_open_date",
        "price_adjustment_mode": "split_adjusted_for_returns",
        "entry_open_price_basis": "raw_open",
        "return_price_basis": "split_adjusted",
        "entry_open_raw": raw_open,
        "entry_open_adjusted_for_return_calc": adjusted_open,
        "adjustment_factor": _adjustment_factor(raw_open, adjusted_open),
    }


def _session_gap(expected_sessions: list[str], expected: str, entry_date: str) -> int:
    if not expected or expected == entry_date:
        return 0
    try:
        expected_idx = expected_sessions.index(expected)
        entry_idx = expected_sessions.index(entry_date)
        return max(0, entry_idx - expected_idx)
    except ValueError:
        return 1


def _adjustment_factor(raw_open: Any, adjusted_open: Any) -> float | str:
    try:
        raw = float(raw_open)
        adjusted = float(adjusted_open)
    except (TypeError, ValueError):
        return ""
    if raw == 0:
        return ""
    factor = adjusted / raw
    return int(factor) if factor.is_integer() else factor


def _parse_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except Exception:
        return None
