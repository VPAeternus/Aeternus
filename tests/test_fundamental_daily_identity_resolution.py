from __future__ import annotations

from tradingagents.research.fundamental.src.daily_run.identity import (
    SEC_COMPANY_TICKERS_EXCHANGE_URL,
    SEC_COMPANY_TICKERS_MF_URL,
    SEC_COMPANY_TICKERS_URL,
    resolve_ticker_identity,
)


def test_sec_map_hit_resolves_cik_name():
    result = resolve_ticker_identity(
        "AAPL",
        local_sec_ticker_rows=[{"ticker": "AAPL", "cik_str": "320193", "title": "Apple Inc."}],
    )

    assert result.identity_status == "resolved_from_sec_ticker_map"
    assert result.cik == "320193"
    assert result.company_title == "Apple Inc."
    assert result.ticker == "AAPL"


def test_sec_map_miss_falls_back_to_complete_panel():
    result = resolve_ticker_identity(
        "EXAS",
        complete_panel_rows=[{"ticker": "EXAS", "cik": "1124140", "company_title": "Exact Sciences"}],
    )

    assert result.identity_status == "resolved_from_complete_panel"
    assert result.cik == "1124140"
    assert result.company_title == "Exact Sciences"


def test_sec_map_miss_falls_back_to_sec_facts():
    result = resolve_ticker_identity(
        "CFLT",
        local_sec_facts={"CFLT": {"cik": "1743748", "entityName": "Confluent, Inc."}},
    )

    assert result.identity_status == "resolved_from_sec_facts"
    assert result.cik == "1743748"
    assert result.company_title == "Confluent, Inc."


def test_blank_sec_map_row_falls_through_to_later_valid_source():
    result = resolve_ticker_identity(
        "AAPL",
        local_sec_ticker_rows=[{"ticker": "AAPL", "cik": "", "company_title": ""}],
        refreshed_sec_ticker_rows=[{"ticker": "AAPL", "cik_str": "320193", "title": "Apple Inc."}],
    )

    assert result.identity_status == "resolved_from_refreshed_sec_ticker_map"
    assert result.cik == "320193"
    assert result.company_title == "Apple Inc."


def test_blank_sec_facts_row_does_not_resolve():
    result = resolve_ticker_identity(
        "CFLT",
        local_sec_facts={"CFLT": {"cik": "", "entityName": ""}},
    )

    assert result.identity_status == "ticker_or_name_unresolved"
    assert result.rejection_reason == "no local SEC identity match and SEC direct lookup returned nothing"
    assert result.cik == ""
    assert result.company_title == ""


def test_share_class_alias_keeps_canonical_ticker_plus_sec_yahoo_mapping():
    result = resolve_ticker_identity(
        "BRK.B",
        local_sec_ticker_rows=[{"ticker": "BRK-B", "cik": "1067983", "company_title": "Berkshire Hathaway Inc."}],
    )

    assert result.identity_status == "resolved_from_sec_ticker_map"
    assert result.ticker == "BRK.B"
    assert result.sec_ticker == "BRK-B"
    assert result.yahoo_ticker == "BRK-B"
    assert "sec_ticker=BRK-B" in result.symbol_alias_reason


def test_refreshed_official_sec_ticker_map_resolves_stale_local_miss():
    result = resolve_ticker_identity(
        "TGNA",
        local_sec_ticker_rows=[],
        refreshed_sec_ticker_rows=[{"ticker": "TGNA", "cik": "39899", "company_title": "TEGNA Inc."}],
    )

    assert result.identity_status == "resolved_from_refreshed_sec_ticker_map"
    assert result.cik == "39899"
    assert result.company_title == "TEGNA Inc."


def test_sec_direct_search_called_only_after_local_and_cache_fallbacks_fail():
    calls: list[str] = []

    def direct_lookup(symbol: str):
        calls.append(symbol)
        return {"ticker": symbol, "cik": "999999", "company_title": "Direct Lookup Co."}

    result = resolve_ticker_identity(
        "MISSING",
        local_sec_ticker_rows=[{"ticker": "OTHER", "cik": "1", "company_title": "Other"}],
        refreshed_sec_ticker_rows=[{"ticker": "OTHER2", "cik": "2", "company_title": "Other 2"}],
        complete_panel_rows=[{"ticker": "OTHER3", "cik": "3", "company_title": "Other 3"}],
        local_sec_facts={"OTHER4": {"cik": "4", "entityName": "Other 4"}},
        sec_direct_lookup=direct_lookup,
    )

    assert calls == ["MISSING"]
    assert result.identity_status == "resolved_from_sec_direct"
    assert result.cik == "999999"


def test_direct_negative_status_is_preserved_with_reason():
    result = resolve_ticker_identity(
        "MISSING",
        sec_direct_lookup=lambda symbol: {
            "ticker": symbol,
            "identity_status": "foreign_or_no_us_sec_filing",
            "rejection_reason": "foreign issuer",
        },
    )

    assert result.identity_status == "foreign_or_no_us_sec_filing"
    assert result.rejection_reason == "foreign issuer"
    assert result.cik == ""
    assert result.company_title == ""


def test_direct_blank_positive_payload_does_not_resolve():
    result = resolve_ticker_identity(
        "MISSING",
        sec_direct_lookup=lambda symbol: {"ticker": symbol, "cik": "", "company_title": ""},
    )

    assert result.identity_status == "ticker_or_name_unresolved"
    assert result.rejection_reason == "no local SEC identity match and SEC direct lookup returned nothing"
    assert result.cik == ""
    assert result.company_title == ""


def test_unresolved_ticker_returns_clear_plain_reason():
    result = resolve_ticker_identity("ZZZZ")

    assert result.identity_status == "ticker_or_name_unresolved"
    assert result.rejection_reason == "no local SEC identity match and SEC direct lookup returned nothing"
    assert result.cik == ""
    assert result.company_title == ""


def test_official_sec_identity_source_constants_are_present():
    assert SEC_COMPANY_TICKERS_URL == "https://www.sec.gov/files/company_tickers.json"
    assert SEC_COMPANY_TICKERS_EXCHANGE_URL == "https://www.sec.gov/files/company_tickers_exchange.json"
    assert SEC_COMPANY_TICKERS_MF_URL == "https://www.sec.gov/files/company_tickers_mf.json"
