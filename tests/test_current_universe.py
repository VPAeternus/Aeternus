import pandas as pd


def test_fetch_current_universe_normalizes_rows_and_tags_sources(monkeypatch):
    from tradingagents.dealflow.current_universe import fetch_current_universe

    spy_frame = pd.DataFrame(
        [
            {"Symbol": "BRK.B", "Security": "Berkshire Hathaway", "GICS Sector": "Financials"},
            {"Symbol": "NVDA", "Security": "NVIDIA", "GICS Sector": "Information Technology"},
        ]
    )
    qqq_frame = pd.DataFrame(
        [
            {"Ticker": "GOOG", "Company": "Alphabet", "GICS Sector": "Communication Services"},
        ]
    )
    dow_frame = pd.DataFrame(
        [
            {"Symbol": "MSFT", "Company": "Microsoft", "Industry": "Technology"},
        ]
    )

    def _fake_read_html(url, *args, **kwargs):
        url = str(url)
        if "S%26P_500" in url or "S&P_500" in url:
            return [spy_frame]
        if "Nasdaq-100" in url:
            return [qqq_frame]
        if "Dow_Jones_Industrial_Average" in url:
            return [dow_frame]
        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr("tradingagents.dealflow.current_universe.pd.read_html", _fake_read_html)

    rows = fetch_current_universe(["SPY", "QQQ", "DOW"], as_of_date="2026-03-11")

    assert len(rows) == 4
    assert any(
        row["source_index"] == "SPY"
        and row["ticker"] == "BRK-B"
        and row["company_name"] == "Berkshire Hathaway"
        and row["sector"] == "Financials"
        for row in rows
    )
    assert any(
        row["source_index"] == "QQQ"
        and row["ticker"] == "GOOG"
        and row["company_name"] == "Alphabet"
        for row in rows
    )
    assert any(
        row["source_index"] == "DOW"
        and row["ticker"] == "MSFT"
        and row["sector"] == "Technology"
        for row in rows
    )


def test_dedupe_current_universe_tickers_preserves_unique_symbols():
    from tradingagents.dealflow.current_universe import dedupe_current_universe_tickers

    rows = [
        {"source_index": "SPY", "ticker": "NVDA"},
        {"source_index": "QQQ", "ticker": "NVDA"},
        {"source_index": "DOW", "ticker": "MSFT"},
    ]

    assert dedupe_current_universe_tickers(rows) == ["MSFT", "NVDA"]


def test_fetch_current_universe_falls_back_to_requests_when_read_html_url_fails(monkeypatch):
    from tradingagents.dealflow.current_universe import fetch_current_universe

    spy_frame = pd.DataFrame(
        [
            {"Symbol": "BRK.B", "Security": "Berkshire Hathaway", "GICS Sector": "Financials"},
        ]
    )

    def _fake_read_html(target, *args, **kwargs):
        if str(target).startswith("https://"):
            raise ValueError("ssl failure")
        return [spy_frame]

    class _Response:
        text = "<html><body><table></table></body></html>"

        def raise_for_status(self):
            return None

    monkeypatch.setattr("tradingagents.dealflow.current_universe.pd.read_html", _fake_read_html)
    monkeypatch.setattr(
        "tradingagents.dealflow.current_universe.requests.get",
        lambda *args, **kwargs: _Response(),
    )

    rows = fetch_current_universe(["SPY"], as_of_date="2026-03-11")

    assert len(rows) == 1
    assert rows[0]["ticker"] == "BRK-B"
