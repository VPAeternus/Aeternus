import pandas as pd


def _make_ohlcv_from_closes(closes, start_date: str = "2020-01-01", volume_base: float = 1_000_000):
    dates = pd.date_range(start=start_date, periods=len(closes), freq="B")
    rows = []
    for idx, (current, close_price) in enumerate(zip(dates, closes)):
        rows.append(
            {
                "date": current,
                "open": close_price - 0.5,
                "high": close_price + 1.0,
                "low": close_price - 1.0,
                "close": close_price,
                "volume": volume_base + idx * 10_000,
            }
        )
    return pd.DataFrame(rows)


def _cross_fixture_frame():
    closes = [
        100.0, 101.0, 102.0, 99.0, 98.0, 100.0, 101.0, 102.0, 101.0, 102.0,
        101.0, 103.0, 101.0, 103.0, 101.0, 100.0, 98.0, 95.0, 97.0, 96.0,
        98.0, 102.0, 105.0, 105.0, 106.0, 105.0, 109.0, 108.0, 112.0, 113.0,
        115.0, 118.0, 117.0, 118.0, 120.0, 121.0, 124.0, 128.0, 128.0, 131.0,
        133.0, 136.0, 140.0, 143.0, 147.0, 150.0, 154.0, 157.0, 161.0, 165.0,
        168.0, 171.0, 175.0, 178.0, 181.0, 185.0, 188.0, 192.0, 196.0, 199.0,
        203.0, 206.0, 210.0, 214.0, 218.0, 221.0, 225.0, 229.0, 233.0, 237.0,
        241.0, 245.0, 249.0, 253.0, 257.0, 261.0, 265.0, 269.0, 273.0, 277.0,
        281.0, 285.0, 289.0, 293.0, 297.0, 301.0, 305.0, 309.0, 313.0, 317.0,
        321.0, 325.0, 329.0, 333.0, 337.0, 341.0, 345.0, 349.0, 353.0,
    ]
    return _make_ohlcv_from_closes(closes)


def test_build_signal_rows_classifies_trigger_zone_and_stale_trend():
    from tradingagents.dealflow.technical_signal_engine import build_signal_rows, classify_buy_zone_state

    frame = _cross_fixture_frame()

    trigger_rows = build_signal_rows(
        "NVDA",
        frame.iloc[:26].copy(),
        computed_at_utc="2026-03-11T12:00:00Z",
        freshness_bars=5,
        fvg_regime_max_age_bars=200,
    )
    zone_rows = build_signal_rows(
        "NVDA",
        frame.iloc[:29].copy(),
        computed_at_utc="2026-03-11T12:01:00Z",
        freshness_bars=5,
        fvg_regime_max_age_bars=200,
    )
    stale_rows = build_signal_rows(
        "NVDA",
        frame.copy(),
        computed_at_utc="2026-03-11T12:02:00Z",
        freshness_bars=5,
        fvg_regime_max_age_bars=200,
    )

    trigger_state = classify_buy_zone_state(trigger_rows, freshness_bars=5)
    zone_state = classify_buy_zone_state(zone_rows, freshness_bars=5)
    stale_state = classify_buy_zone_state(stale_rows, freshness_bars=5)

    assert trigger_state["status_label"] == "BUY_TRIGGER"
    assert zone_state["status_label"] == "BUY_ZONE"
    assert stale_state["status_label"] == "TREND_UP_NOT_FRESH"


def test_recompute_signal_state_replaces_recent_tail_only(tmp_path):
    from tradingagents.dealflow.technical_signal_engine import recompute_signal_state
    from tradingagents.dealflow.technical_signal_store import SQLiteTechnicalSignalStore

    frame = _cross_fixture_frame().iloc[:30].copy()
    store = SQLiteTechnicalSignalStore(tmp_path / "technical_signal_cache.db")
    store.initialize()
    store.upsert_market_history(
        [
            {
                "ticker": "NVDA",
                "date": pd.to_datetime(row["date"]).date().isoformat(),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["volume"]),
                "source": "test",
                "updated_at_utc": "2026-03-11T12:00:00Z",
            }
            for _, row in frame.iterrows()
        ]
    )

    recompute_signal_state(
        store,
        "NVDA",
        computed_at_utc="2026-03-11T12:00:00Z",
        recompute_tail_bars=30,
        freshness_bars=5,
        fvg_regime_max_age_bars=200,
    )
    recompute_signal_state(
        store,
        "NVDA",
        computed_at_utc="2026-03-11T12:05:00Z",
        recompute_tail_bars=5,
        freshness_bars=5,
        fvg_regime_max_age_bars=200,
    )

    rows = store.load_signal_rows("NVDA")

    assert len(rows) == len(frame)
    assert rows[10]["computed_at_utc"] == "2026-03-11T12:00:00Z"
    assert rows[-1]["computed_at_utc"] == "2026-03-11T12:05:00Z"
