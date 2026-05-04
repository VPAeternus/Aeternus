from tradingagents.research.fundamental_autoresearch.time_utils import (
    compute_effective_market_date,
    parse_sec_timestamp,
)


def test_parse_sec_timestamp_normalizes_z_suffix():
    parsed = parse_sec_timestamp("2026-01-29T16:32:10Z")

    assert parsed.isoformat() == "2026-01-29T16:32:10+00:00"


def test_effective_market_date_defaults_to_next_session_even_if_market_hours():
    effective = compute_effective_market_date("2026-01-29T15:00:00Z")

    assert effective == "2026-01-30"


def test_effective_market_date_can_use_same_day_when_explicitly_enabled():
    effective = compute_effective_market_date(
        "2026-01-29T15:00:00Z",
        assume_same_day_if_market_hours=True,
    )

    assert effective == "2026-01-29"


def test_effective_market_date_rolls_after_hours_to_next_trading_day():
    effective = compute_effective_market_date(
        "2026-01-29T22:30:00Z",
        assume_same_day_if_market_hours=True,
    )

    assert effective == "2026-01-30"


def test_effective_market_date_skips_weekend():
    effective = compute_effective_market_date(
        "2026-01-30T23:30:00Z",
        assume_same_day_if_market_hours=True,
    )

    assert effective == "2026-02-02"
