from tradingagents.graph.track_record import TrackRecord


def test_accuracy_by_sector(tmp_path):
    tr = TrackRecord(path=str(tmp_path / "track_record.json"))
    tr.append(
        {
            "rating_id": "r1",
            "ticker": "AAA",
            "sector": "Technology",
            "rating": "Buy",
            "confidence": 4,
            "status": "CLOSED",
            "price_at_rating": 100.0,
            "close_price": 120.0,
        }
    )
    tr.append(
        {
            "rating_id": "r2",
            "ticker": "BBB",
            "sector": "Technology",
            "rating": "Buy",
            "confidence": 4,
            "status": "CLOSED",
            "price_at_rating": 100.0,
            "close_price": 90.0,
        }
    )

    acc = tr.get_accuracy_by_sector("Technology")
    assert acc == 0.5


def test_accuracy_by_confidence(tmp_path):
    tr = TrackRecord(path=str(tmp_path / "track_record.json"))
    tr.append(
        {
            "rating_id": "r1",
            "ticker": "AAA",
            "sector": "Technology",
            "rating": "Buy",
            "confidence": 5,
            "status": "CLOSED",
            "price_at_rating": 100.0,
            "close_price": 120.0,
        }
    )
    tr.append(
        {
            "rating_id": "r2",
            "ticker": "BBB",
            "sector": "Technology",
            "rating": "Sell",
            "confidence": 5,
            "status": "CLOSED",
            "price_at_rating": 100.0,
            "close_price": 105.0,
        }
    )

    acc = tr.get_accuracy_by_confidence(5)
    assert acc == 0.5


def test_compute_v3_benchmark_uses_configured_ticker_and_track_record_window(tmp_path, monkeypatch):
    tr = TrackRecord(path=str(tmp_path / "track_record.json"))
    tr.append(
        {
            "rating_id": "r1",
            "ticker": "AAA",
            "rating": "Buy",
            "date": "2025-01-15",
            "price_at_rating": 100.0,
            "close_price": 110.0,
            "status": "CLOSED",
        }
    )
    tr.append(
        {
            "rating_id": "r2",
            "ticker": "BBB",
            "rating": "Buy",
            "trade_date": "2025-03-20",
            "price_at_rating": 100.0,
            "close_price": 105.0,
            "status": "CLOSED",
        }
    )

    calls = {}

    def fake_v3_benchmark_stats(*, ticker, lookback_days, date_start=None, date_end=None):
        calls["ticker"] = ticker
        calls["lookback_days"] = lookback_days
        calls["date_start"] = date_start
        calls["date_end"] = date_end
        return {
            "ticker": ticker,
            "period_days": 46,
            "date_start": date_start,
            "date_end": date_end,
            "total_pts": 12.0,
            "bh_pts": 8.0,
            "v3_total_return_pct": 15.0,
            "bh_total_return_pct": 10.0,
            "v3_cagr_pct": 20.0,
            "bh_cagr_pct": 13.0,
        }

    monkeypatch.setattr("tradingagents.graph.track_record.DEFAULT_CONFIG", {
        "v3_benchmark_ticker": "SPY",
    })
    monkeypatch.setattr(
        "tradingagents.phase_engine.index_overlay.v3_benchmark_stats",
        fake_v3_benchmark_stats,
    )

    result = tr.compute_v3_benchmark()

    assert calls == {
        "ticker": "SPY",
        "lookback_days": 0,
        "date_start": "2025-01-15",
        "date_end": "2025-03-20",
    }
    assert result["ticker"] == "SPY"
    assert result["date_start"] == "2025-01-15"
    assert result["date_end"] == "2025-03-20"
    assert result["v3_total_return_pct"] == 15.0
    assert result["bh_total_return_pct"] == 10.0
