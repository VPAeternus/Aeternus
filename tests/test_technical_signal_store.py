import sqlite3


def test_technical_signal_store_initializes_wal_and_tables(tmp_path):
    from tradingagents.dealflow.technical_signal_store import SQLiteTechnicalSignalStore

    db_path = tmp_path / "technical_signal_cache.db"
    store = SQLiteTechnicalSignalStore(db_path)
    store.initialize()

    with store.connection() as conn:
        mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
        assert str(mode).lower() == "wal"
        names = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "universe_membership_current" in names
        assert "market_history_daily" in names
        assert "signal_kama_fvg_daily" in names
        assert "buy_zone_state_current" in names
        assert "yahoo_symbol_status" in names


def test_technical_signal_store_upserts_membership_and_buy_zone_idempotently(tmp_path):
    from tradingagents.dealflow.technical_signal_store import SQLiteTechnicalSignalStore

    db_path = tmp_path / "technical_signal_cache.db"
    store = SQLiteTechnicalSignalStore(db_path)
    store.initialize()

    store.upsert_universe_membership_current(
        [
            {
                "source_index": "SPY",
                "ticker": "BRK-B",
                "company_name": "Berkshire Hathaway",
                "sector": "Financials",
                "as_of_date": "2026-03-11",
                "fetched_at_utc": "2026-03-11T10:00:00Z",
            },
            {
                "source_index": "QQQ",
                "ticker": "NVDA",
                "company_name": "NVIDIA",
                "sector": "Technology",
                "as_of_date": "2026-03-11",
                "fetched_at_utc": "2026-03-11T10:00:00Z",
            },
        ]
    )
    store.upsert_universe_membership_current(
        [
            {
                "source_index": "SPY",
                "ticker": "BRK-B",
                "company_name": "Berkshire Hathaway Inc.",
                "sector": "Financials",
                "as_of_date": "2026-03-11",
                "fetched_at_utc": "2026-03-11T10:05:00Z",
            }
        ]
    )
    store.upsert_buy_zone_state(
        [
            {
                "ticker": "NVDA",
                "as_of_date": "2026-03-11",
                "in_buy_zone": 1,
                "status_label": "BUY_TRIGGER",
                "reason": "Fresh KAMA cross inside bullish FVG regime",
                "last_cross_up_date": "2026-03-11",
                "bullish_fvg_regime_active": 1,
                "bullish_fvg_streak": 3,
                "bullish_fvg_regime_age_bars": 0,
                "fast_kama": 123.4,
                "slow_kama": 120.0,
                "score": 283.3,
                "updated_at_utc": "2026-03-11T10:10:00Z",
            }
        ]
    )
    store.upsert_buy_zone_state(
        [
            {
                "ticker": "NVDA",
                "as_of_date": "2026-03-11",
                "in_buy_zone": 1,
                "status_label": "BUY_ZONE",
                "reason": "Trend still fresh",
                "last_cross_up_date": "2026-03-11",
                "bullish_fvg_regime_active": 1,
                "bullish_fvg_streak": 3,
                "bullish_fvg_regime_age_bars": 1,
                "fast_kama": 124.0,
                "slow_kama": 121.0,
                "score": 247.9,
                "updated_at_utc": "2026-03-11T10:15:00Z",
            }
        ]
    )

    membership = store.list_universe_membership_current()
    buy_zone = store.get_buy_zone_state("NVDA")

    assert len(membership) == 2
    assert any(
        row["ticker"] == "BRK-B" and row["company_name"] == "Berkshire Hathaway Inc."
        for row in membership
    )
    assert buy_zone is not None
    assert buy_zone["ticker"] == "NVDA"
    assert buy_zone["status_label"] == "BUY_ZONE"
    assert buy_zone["bullish_fvg_regime_age_bars"] == 1


def test_technical_signal_store_tracks_yahoo_symbol_status_and_filters_invalid_membership(tmp_path):
    from tradingagents.dealflow.technical_signal_store import SQLiteTechnicalSignalStore

    db_path = tmp_path / "technical_signal_cache.db"
    store = SQLiteTechnicalSignalStore(db_path)
    store.initialize()

    store.upsert_universe_membership_current(
        [
            {
                "source_index": "SPY",
                "ticker": "GOOD",
                "company_name": "Good Co",
                "sector": "Industrials",
                "as_of_date": "2026-03-11",
                "fetched_at_utc": "2026-03-11T10:00:00Z",
            },
            {
                "source_index": "QQQ",
                "ticker": "BAD",
                "company_name": "Bad Co",
                "sector": "Technology",
                "as_of_date": "2026-03-11",
                "fetched_at_utc": "2026-03-11T10:00:00Z",
            },
        ]
    )
    store.upsert_yahoo_symbol_status(
        [
            {
                "ticker": "GOOD",
                "is_invalid": 0,
                "invalid_reason": "",
                "no_data_before_date": "2021-01-04",
                "checked_through_date": "2026-03-11",
                "updated_at_utc": "2026-03-11T10:05:00Z",
            },
            {
                "ticker": "BAD",
                "is_invalid": 1,
                "invalid_reason": "No recent Yahoo data",
                "no_data_before_date": None,
                "checked_through_date": "2026-03-11",
                "updated_at_utc": "2026-03-11T10:05:00Z",
            },
        ]
    )

    valid_membership = store.list_universe_membership_current(exclude_invalid=True)
    invalid_tickers = store.list_invalid_yahoo_tickers()
    bad_status = store.get_yahoo_symbol_status("BAD")

    assert [row["ticker"] for row in valid_membership] == ["GOOD"]
    assert invalid_tickers == ["BAD"]
    assert bad_status is not None
    assert bad_status["is_invalid"] == 1
    assert bad_status["invalid_reason"] == "No recent Yahoo data"


def test_technical_signal_store_purges_ticker_from_current_cache_surfaces(tmp_path):
    from tradingagents.dealflow.technical_signal_store import SQLiteTechnicalSignalStore

    db_path = tmp_path / "technical_signal_cache.db"
    store = SQLiteTechnicalSignalStore(db_path)
    store.initialize()

    store.upsert_universe_membership_current(
        [
            {
                "source_index": "SPY",
                "ticker": "BAD",
                "company_name": "Bad Co",
                "sector": "Technology",
                "as_of_date": "2026-03-11",
                "fetched_at_utc": "2026-03-11T10:00:00Z",
            }
        ]
    )
    store.upsert_market_history(
        [
            {
                "ticker": "BAD",
                "date": "2026-03-10",
                "open": 10.0,
                "high": 11.0,
                "low": 9.5,
                "close": 10.5,
                "volume": 1000.0,
                "source": "test",
                "updated_at_utc": "2026-03-11T10:00:00Z",
            }
        ]
    )
    store.replace_signal_rows(
        "BAD",
        "2026-03-10",
        [
            {
                "ticker": "BAD",
                "date": "2026-03-10",
                "fast_kama": 10.0,
                "slow_kama": 9.5,
                "kama_spread_pct": 0.05,
                "cross_up": True,
                "bullish_state": True,
                "bullish_fvg_regime_active": True,
                "bullish_fvg_streak": 2,
                "bullish_fvg_regime_age_bars": 0,
                "buy_zone": True,
                "buy_zone_reason": "test",
                "score": 10.0,
                "computed_at_utc": "2026-03-11T10:00:00Z",
            }
        ],
    )
    store.upsert_buy_zone_state(
        [
            {
                "ticker": "BAD",
                "as_of_date": "2026-03-11",
                "in_buy_zone": 1,
                "status_label": "BUY_ZONE",
                "reason": "test",
                "last_cross_up_date": "2026-03-10",
                "bullish_fvg_regime_active": 1,
                "bullish_fvg_streak": 2,
                "bullish_fvg_regime_age_bars": 0,
                "fast_kama": 10.0,
                "slow_kama": 9.5,
                "score": 10.0,
                "updated_at_utc": "2026-03-11T10:00:00Z",
            }
        ]
    )
    store.upsert_yahoo_symbol_status(
        [
            {
                "ticker": "BAD",
                "is_invalid": 1,
                "invalid_reason": "No recent Yahoo data",
                "no_data_before_date": None,
                "checked_through_date": "2026-03-11",
                "updated_at_utc": "2026-03-11T10:05:00Z",
            }
        ]
    )

    store.purge_tickers(["BAD"])

    assert store.list_universe_membership_current() == []
    assert store.load_market_history("BAD") == []
    assert store.load_signal_rows("BAD") == []
    assert store.get_buy_zone_state("BAD") is None
    assert store.get_yahoo_symbol_status("BAD")["is_invalid"] == 1
