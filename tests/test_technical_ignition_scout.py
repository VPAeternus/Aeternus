from pathlib import Path


def test_scan_technical_ignition_setups_promotes_fresh_buy_states_and_tracks_stale(tmp_path):
    from tradingagents.dealflow.sources.technical_ignition_scout import scan_technical_ignition_setups
    from tradingagents.dealflow.technical_signal_store import SQLiteTechnicalSignalStore

    db_path = tmp_path / "technical_signal_cache.db"
    store = SQLiteTechnicalSignalStore(db_path)
    store.initialize()
    store.upsert_buy_zone_state(
        [
            {
                "ticker": "AAPL",
                "as_of_date": "2026-03-10",
                "in_buy_zone": 1,
                "status_label": "BUY_TRIGGER",
                "reason": "Fresh trigger",
                "last_cross_up_date": "2026-03-10",
                "bullish_fvg_regime_active": 1,
                "bullish_fvg_streak": 2,
                "bullish_fvg_regime_age_bars": 0,
                "fast_kama": 101.0,
                "slow_kama": 99.0,
                "score": 88.0,
                "updated_at_utc": "2026-03-11T12:00:00Z",
            },
            {
                "ticker": "MSFT",
                "as_of_date": "2026-03-10",
                "in_buy_zone": 1,
                "status_label": "BUY_ZONE",
                "reason": "Trend still fresh",
                "last_cross_up_date": "2026-03-05",
                "bullish_fvg_regime_active": 1,
                "bullish_fvg_streak": 3,
                "bullish_fvg_regime_age_bars": 4,
                "fast_kama": 201.0,
                "slow_kama": 199.0,
                "score": 42.0,
                "updated_at_utc": "2026-03-11T12:00:00Z",
            },
            {
                "ticker": "NVDA",
                "as_of_date": "2026-03-10",
                "in_buy_zone": 0,
                "status_label": "TREND_UP_NOT_FRESH",
                "reason": "Old but valid trend",
                "last_cross_up_date": "2026-02-01",
                "bullish_fvg_regime_active": 1,
                "bullish_fvg_streak": 5,
                "bullish_fvg_regime_age_bars": 11,
                "fast_kama": 301.0,
                "slow_kama": 298.0,
                "score": 30.0,
                "updated_at_utc": "2026-03-11T12:00:00Z",
            },
            {
                "ticker": "GOOG",
                "as_of_date": "2026-03-09",
                "in_buy_zone": 1,
                "status_label": "BUY_TRIGGER",
                "reason": "Wrong date",
                "last_cross_up_date": "2026-03-09",
                "bullish_fvg_regime_active": 1,
                "bullish_fvg_streak": 2,
                "bullish_fvg_regime_age_bars": 0,
                "fast_kama": 401.0,
                "slow_kama": 398.0,
                "score": 91.0,
                "updated_at_utc": "2026-03-11T12:00:00Z",
            },
        ]
    )

    result = scan_technical_ignition_setups(as_of_date="2026-03-10", db_path=db_path)

    assert result["promoted_count"] == 2
    assert result["promoted_symbols"] == ["AAPL", "MSFT"]
    assert result["stale_count"] == 1
    assert result["stale_symbols"] == ["NVDA"]
    assert [row["symbol"] for row in result["signals"]] == ["AAPL", "MSFT"]
    assert result["signals"][0]["source"] == "technical_ignition"
    assert result["signals"][0]["delta_kind"] == "technical_ignition"


def test_scan_technical_ignition_setups_returns_empty_when_db_missing(tmp_path):
    from tradingagents.dealflow.sources.technical_ignition_scout import scan_technical_ignition_setups

    missing_path = tmp_path / "missing.db"
    result = scan_technical_ignition_setups(as_of_date="2026-03-10", db_path=missing_path)

    assert result["promoted_count"] == 0
    assert result["promoted_symbols"] == []
    assert result["signals"] == []
    assert result["db_path"] == str(Path(missing_path))
