from tradingagents.research.fundamental.src.ingest.trading_calendar import (
    first_trading_session_after,
    resolve_entry_open,
)


def _price(ticker, date, open_price=10, adjusted_open=None):
    row = {"ticker": ticker, "date": date, "open": open_price}
    if adjusted_open is not None:
        row["adj_open"] = adjusted_open
    return row


def test_first_trading_session_after_skips_market_holiday():
    price_rows = [
        _price("ABC", "2022-02-18"),
        _price("ABC", "2022-02-22"),
    ]

    assert first_trading_session_after(price_rows, "2022-02-21") == "2022-02-22"


def test_first_trading_session_after_is_strictly_after_decision_date():
    price_rows = [
        _price("ABC", "2022-03-03"),
        _price("ABC", "2022-03-04"),
    ]

    assert first_trading_session_after(price_rows, "2022-03-03") == "2022-03-04"


def test_resolve_entry_open_marks_missing_first_ticker_price_gap():
    resolved = resolve_entry_open(
        "ABC",
        "2022-03-03",
        [_price("ABC", "2022-03-07", open_price=11)],
        expected_market_sessions=["2022-03-04", "2022-03-07"],
    )

    assert resolved["expected_market_session_after_decision"] == "2022-03-04"
    assert resolved["entry_open_date"] == "2022-03-07"
    assert resolved["entry_open"] == 11
    assert resolved["entry_open_gap_sessions"] == 1
    assert resolved["entry_date_adjustment_reason"] == "missing_ticker_price"


def test_resolve_entry_open_sets_tradable_date_alias_and_price_basis():
    resolved = resolve_entry_open(
        "ABC",
        "2022-03-03",
        [_price("ABC", "2022-03-04", open_price=10, adjusted_open=5)],
        expected_market_sessions=["2022-03-04"],
    )

    assert resolved["entry_open_date"] == "2022-03-04"
    assert resolved["tradable_date"] == "2022-03-04"
    assert resolved["tradable_date_alias_source"] == "entry_open_date"
    assert resolved["entry_open_raw"] == 10
    assert resolved["entry_open_adjusted_for_return_calc"] == 5
    assert resolved["entry_open_price_basis"] == "raw_open"
    assert resolved["return_price_basis"] == "split_adjusted"
    assert resolved["price_adjustment_mode"] == "split_adjusted_for_returns"
