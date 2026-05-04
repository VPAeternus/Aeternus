import pandas as pd


def _download_frame(dates, closes):
    frame = pd.DataFrame(
        {
            "Open": [value - 0.5 for value in closes],
            "High": [value + 1.0 for value in closes],
            "Low": [value - 1.0 for value in closes],
            "Close": closes,
            "Volume": [1_000_000 + idx * 10_000 for idx, _ in enumerate(closes)],
        },
        index=pd.to_datetime(dates),
    )
    frame.index.name = "Date"
    return frame


def test_sync_market_history_backfills_then_appends_missing_dates_only(tmp_path, monkeypatch):
    from tradingagents.dealflow.technical_market_cache import sync_market_history
    from tradingagents.dealflow.technical_signal_store import SQLiteTechnicalSignalStore

    store = SQLiteTechnicalSignalStore(tmp_path / "technical_signal_cache.db")
    store.initialize()

    calls = []
    first = _download_frame(["2026-03-03", "2026-03-04"], [100.0, 102.0])
    prepend_gap = pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    append_only = _download_frame(["2026-03-05"], [103.5])

    def _fake_download(symbol, start=None, end=None, **kwargs):
        calls.append({"symbol": symbol, "start": start, "end": end})
        if len(calls) == 1:
            return first
        if start == "2026-03-01" and end == "2026-03-03":
            return prepend_gap
        return append_only

    monkeypatch.setattr("tradingagents.dealflow.technical_market_cache.yf.download", _fake_download)

    sync_market_history(
        store,
        ["NVDA"],
        start_date="2026-03-01",
        end_date="2026-03-06",
        updated_at_utc="2026-03-11T12:00:00Z",
    )
    sync_market_history(
        store,
        ["NVDA"],
        start_date="2026-03-01",
        end_date="2026-03-06",
        updated_at_utc="2026-03-11T12:05:00Z",
    )

    rows = store.load_market_history("NVDA")

    assert len(calls) == 2
    assert calls[0]["start"] == "2026-03-01"
    assert calls[1]["start"] == "2026-03-05"
    assert [row["date"] for row in rows] == ["2026-03-03", "2026-03-04", "2026-03-05"]
    assert rows[-1]["close"] == 103.5


def test_sync_market_history_prepends_when_requested_start_is_before_cached_history(tmp_path, monkeypatch):
    from tradingagents.dealflow.technical_market_cache import sync_market_history
    from tradingagents.dealflow.technical_signal_store import SQLiteTechnicalSignalStore

    store = SQLiteTechnicalSignalStore(tmp_path / "technical_signal_cache.db")
    store.initialize()
    store.upsert_market_history(
        [
            {
                "ticker": "NVDA",
                "date": "2020-01-02",
                "open": 10.0,
                "high": 11.0,
                "low": 9.5,
                "close": 10.5,
                "volume": 1_000_000.0,
                "source": "seed",
                "updated_at_utc": "2026-03-11T12:00:00Z",
            }
        ]
    )

    calls = []
    prepend = _download_frame(["1999-01-04", "1999-01-05"], [2.0, 2.2])

    def _fake_download(symbol, start=None, end=None, **kwargs):
        calls.append({"symbol": symbol, "start": start, "end": end})
        return prepend

    monkeypatch.setattr("tradingagents.dealflow.technical_market_cache.yf.download", _fake_download)

    sync_market_history(
        store,
        ["NVDA"],
        start_date="1999-01-01",
        end_date="2020-01-02",
        updated_at_utc="2026-03-11T12:05:00Z",
    )

    rows = store.load_market_history("NVDA")

    assert len(calls) == 1
    assert calls[0]["start"] == "1999-01-01"
    assert calls[0]["end"] == "2020-01-02"
    assert [row["date"] for row in rows] == ["1999-01-04", "1999-01-05", "2020-01-02"]
    assert rows[0]["close"] == 2.0
    assert rows[-1]["close"] == 10.5


def test_normalize_download_frame_handles_single_ticker_multiindex():
    from tradingagents.dealflow.technical_market_cache import _normalize_download_frame

    frame = pd.DataFrame(
        {
            ("Close", "NVDA"): [100.0],
            ("High", "NVDA"): [101.0],
            ("Low", "NVDA"): [99.0],
            ("Open", "NVDA"): [99.5],
            ("Volume", "NVDA"): [1_000_000],
            ("Adj Close", "NVDA"): [100.0],
        },
        index=pd.to_datetime(["2026-03-10"]),
    )

    normalized = _normalize_download_frame(frame)

    assert list(normalized.columns) == ["open", "high", "low", "close", "volume"]
    assert float(normalized.iloc[0]["close"]) == 100.0


def test_sync_market_history_learns_no_data_before_first_available_date_and_skips_repeat_prepend(tmp_path, monkeypatch):
    from tradingagents.dealflow.technical_market_cache import sync_market_history
    from tradingagents.dealflow.technical_signal_store import SQLiteTechnicalSignalStore

    store = SQLiteTechnicalSignalStore(tmp_path / "technical_signal_cache.db")
    store.initialize()

    calls = []
    first = _download_frame(["2021-07-29", "2021-07-30"], [45.0, 46.0])

    def _fake_download(symbol, start=None, end=None, **kwargs):
        calls.append({"symbol": symbol, "start": start, "end": end})
        return first

    monkeypatch.setattr("tradingagents.dealflow.technical_market_cache.yf.download", _fake_download)

    sync_market_history(
        store,
        ["HOOD"],
        start_date="1999-01-01",
        end_date="2021-07-31",
        updated_at_utc="2026-03-11T12:00:00Z",
    )
    sync_market_history(
        store,
        ["HOOD"],
        start_date="1999-01-01",
        end_date="2021-07-31",
        updated_at_utc="2026-03-11T12:05:00Z",
    )

    status = store.get_yahoo_symbol_status("HOOD")

    assert len(calls) == 1
    assert status is not None
    assert status["is_invalid"] == 0
    assert status["no_data_before_date"] == "2021-07-29"


def test_sync_market_history_marks_recently_empty_symbol_invalid_and_skips_future_fetches(tmp_path, monkeypatch):
    from tradingagents.dealflow.technical_market_cache import sync_market_history
    from tradingagents.dealflow.technical_signal_store import SQLiteTechnicalSignalStore

    store = SQLiteTechnicalSignalStore(tmp_path / "technical_signal_cache.db")
    store.initialize()
    store.upsert_universe_membership_current(
        [
            {
                "source_index": "SPY",
                "ticker": "BAD",
                "company_name": "Bad Co",
                "sector": "Industrials",
                "as_of_date": "2026-03-11",
                "fetched_at_utc": "2026-03-11T12:00:00Z",
            }
        ]
    )

    calls = []

    def _fake_download(symbol, start=None, end=None, **kwargs):
        calls.append({"symbol": symbol, "start": start, "end": end})
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])

    monkeypatch.setattr("tradingagents.dealflow.technical_market_cache.yf.download", _fake_download)

    first = sync_market_history(
        store,
        ["BAD"],
        start_date="2020-01-01",
        end_date="2026-03-11",
        updated_at_utc="2026-03-11T12:00:00Z",
    )
    second = sync_market_history(
        store,
        ["BAD"],
        start_date="2020-01-01",
        end_date="2026-03-11",
        updated_at_utc="2026-03-11T12:05:00Z",
    )

    status = store.get_yahoo_symbol_status("BAD")

    assert len(calls) == 1
    assert status is not None
    assert status["is_invalid"] == 1
    assert status["checked_through_date"] == "2026-03-11"
    assert first["invalid_tickers_removed"] == ["BAD"]
    assert second["skipped_invalid_tickers"] == ["BAD"]
    assert store.list_universe_membership_current() == []
