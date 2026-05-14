from tradingagents.research.fundamental.src.daily_run.price_cache import load_or_fetch_price_rows
from tradingagents.research.fundamental.src.daily_run.review_list_filter import load_cached_review_price_rows, store_review_price_rows


def _price_rows(ticker: str, days: int = 60):
    return [
        {
            "ticker": ticker,
            "date": f"2026-03-{(idx % 28) + 1:02d}",
            "open": 10.0,
            "high": 11.0,
            "low": 9.0,
            "close": 10.5,
            "volume": 600_000,
        }
        for idx in range(days)
    ]


def test_daily_price_cache_uses_cache_before_live_fetch(tmp_path):
    cache_path = store_review_price_rows(_price_rows("AAA"), output_root=tmp_path / "cache", quarter="2026Q2", as_of="2026-05-12")

    def fail_provider(*args, **kwargs):
        raise AssertionError("live price fetch should not be called when cache has the ticker")

    result = load_or_fetch_price_rows(
        ["AAA"],
        start="2026-03-01",
        end="2026-05-13",
        cache_paths=[cache_path],
        price_provider=fail_provider,
        output_root=tmp_path / "run",
        quarter="2026Q2",
        as_of="2026-05-12",
    )

    assert result.summary["daily_price_cached_ticker_count"] == 1
    assert result.summary["daily_price_missing_cache_ticker_count"] == 0
    assert {row["ticker"] for row in result.rows} == {"AAA"}


def test_daily_price_cache_fetches_missing_and_writes_cache(tmp_path):
    calls = []

    def provider(tickers, *, start, end):
        calls.append(list(tickers))
        return _price_rows("BBB")

    result = load_or_fetch_price_rows(
        ["BBB"],
        start="2026-03-01",
        end="2026-05-13",
        cache_paths=[tmp_path / "missing_cache"],
        price_provider=provider,
        output_root=tmp_path / "run",
        quarter="2026Q2",
        as_of="2026-05-12",
        shared_cache_root=tmp_path / "shared",
    )

    assert calls == [["BBB"]]
    assert result.summary["daily_price_live_fetch_ticker_count"] == 1
    assert "daily_live_price_run_cache" in result.artifacts
    assert "daily_live_price_shared_cache" in result.artifacts
    loaded = load_cached_review_price_rows([tmp_path / "shared"], tickers=["BBB"], start="2026-03-01", end="2026-05-13")
    assert {row["ticker"] for row in loaded} == {"BBB"}


def test_daily_price_cache_fetches_when_cached_rows_are_before_needed_entry_date(tmp_path):
    old_cache_path = store_review_price_rows(
        [
            {
                "ticker": "CCC",
                "date": "2026-03-01",
                "open": 4.0,
                "high": 5.0,
                "low": 3.0,
                "close": 4.5,
                "volume": 600_000,
            }
        ],
        output_root=tmp_path / "cache",
        quarter="2026Q2",
        as_of="2026-05-12",
    )
    calls = []

    def provider(tickers, *, start, end):
        calls.append({"tickers": list(tickers), "start": start, "end": end})
        return [
            {
                "ticker": "CCC",
                "date": "2026-05-11",
                "open": 9.0,
                "high": 10.0,
                "low": 8.0,
                "close": 9.5,
                "volume": 700_000,
            }
        ]

    result = load_or_fetch_price_rows(
        ["CCC"],
        start="2026-03-01",
        end="2026-05-13",
        cache_paths=[old_cache_path],
        price_provider=provider,
        output_root=tmp_path / "run",
        quarter="2026Q2",
        as_of="2026-05-12",
        required_start_by_ticker={"CCC": "2026-05-10"},
    )

    assert calls == [{"tickers": ["CCC"], "start": "2026-05-10", "end": "2026-05-13"}]
    assert result.summary["daily_price_partial_cache_ticker_count"] == 1
    assert result.summary["daily_price_live_fetch_ticker_count"] == 1
    assert any(row["ticker"] == "CCC" and row["date"] == "2026-05-11" for row in result.rows)
