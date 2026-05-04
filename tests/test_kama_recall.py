import pandas as pd
import pytest


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
        100.0,
        101.0,
        102.0,
        99.0,
        98.0,
        100.0,
        101.0,
        102.0,
        101.0,
        102.0,
        101.0,
        103.0,
        101.0,
        103.0,
        101.0,
        100.0,
        98.0,
        95.0,
        97.0,
        96.0,
        98.0,
        102.0,
        105.0,
        105.0,
        106.0,
        105.0,
        109.0,
        108.0,
        112.0,
        113.0,
        115.0,
        118.0,
        117.0,
        118.0,
        120.0,
        121.0,
        124.0,
        128.0,
        128.0,
        131.0,
        133.0,
        136.0,
        140.0,
        143.0,
        147.0,
        150.0,
        154.0,
        157.0,
        161.0,
        165.0,
        168.0,
        171.0,
        175.0,
        178.0,
        181.0,
        185.0,
        188.0,
        192.0,
        196.0,
        199.0,
        203.0,
        206.0,
        210.0,
        214.0,
        218.0,
        221.0,
        225.0,
        229.0,
        233.0,
        237.0,
        241.0,
        245.0,
        249.0,
        253.0,
        257.0,
        261.0,
        265.0,
        269.0,
        273.0,
        277.0,
        281.0,
        285.0,
        289.0,
        293.0,
        297.0,
        301.0,
        305.0,
        309.0,
        313.0,
        317.0,
        321.0,
        325.0,
        329.0,
        333.0,
        337.0,
        341.0,
        345.0,
        349.0,
        353.0,
    ]
    return _make_ohlcv_from_closes(closes)


def _steady_frame(periods: int = 100, start_price: float = 90.0, daily_step: float = 0.8):
    closes = [start_price + idx * daily_step for idx in range(periods)]
    return _make_ohlcv_from_closes(closes, volume_base=2_000_000)


def _make_ohlcv_from_rows(rows):
    frame = pd.DataFrame(rows)
    frame["date"] = pd.to_datetime(frame["date"])
    return frame


def test_compute_kama_snapshot_detects_bullish_cross():
    from tradingagents.dealflow.kama_recall import compute_kama_snapshot

    frame = _cross_fixture_frame()

    snapshot = compute_kama_snapshot(frame, index=25)

    assert snapshot["valid"] is True
    assert snapshot["cross_up"] is True
    assert snapshot["bullish_state"] is True
    assert snapshot["fast_kama"] > snapshot["slow_kama"]
    assert snapshot["kama_spread"] > 0.0


def test_build_bullish_fvg_regime_tracks_streak_and_resets_on_bear():
    from tradingagents.dealflow.kama_recall import build_bullish_fvg_regime_frame

    frame = _make_ohlcv_from_rows(
        [
            {"date": "2020-01-01", "open": 9.5, "high": 10.0, "low": 9.0, "close": 9.5, "volume": 1_000_000},
            {"date": "2020-01-02", "open": 10.5, "high": 11.0, "low": 10.0, "close": 10.5, "volume": 1_000_000},
            {"date": "2020-01-03", "open": 12.5, "high": 13.0, "low": 12.0, "close": 12.5, "volume": 1_000_000},
            {"date": "2020-01-06", "open": 13.5, "high": 14.0, "low": 13.0, "close": 13.5, "volume": 1_000_000},
            {"date": "2020-01-07", "open": 13.5, "high": 14.0, "low": 13.0, "close": 13.5, "volume": 1_000_000},
            {"date": "2020-01-08", "open": 10.5, "high": 11.0, "low": 10.0, "close": 10.5, "volume": 1_000_000},
        ]
    )

    regime = build_bullish_fvg_regime_frame(frame, atr_floor=0.25, max_age_bars=20)

    assert regime.iloc[2]["bullish_fvg_regime_active"] is True
    assert regime.iloc[2]["bullish_fvg_streak"] == 1
    assert regime.iloc[3]["bullish_fvg_regime_active"] is True
    assert regime.iloc[3]["bullish_fvg_streak"] == 2
    assert regime.iloc[4]["bullish_fvg_regime_active"] is True
    assert regime.iloc[4]["bullish_fvg_streak"] == 2
    assert regime.iloc[4]["bullish_fvg_regime_age_bars"] == 1
    assert regime.iloc[5]["bullish_fvg_regime_active"] is False
    assert regime.iloc[5]["bullish_fvg_streak"] == 0


def test_build_bullish_fvg_regime_expires_after_max_age():
    from tradingagents.dealflow.kama_recall import build_bullish_fvg_regime_frame

    frame = _make_ohlcv_from_rows(
        [
            {"date": "2020-01-01", "open": 9.5, "high": 10.0, "low": 9.0, "close": 9.5, "volume": 1_000_000},
            {"date": "2020-01-02", "open": 10.5, "high": 11.0, "low": 10.0, "close": 10.5, "volume": 1_000_000},
            {"date": "2020-01-03", "open": 12.5, "high": 13.0, "low": 12.0, "close": 12.5, "volume": 1_000_000},
            {"date": "2020-01-06", "open": 12.7, "high": 13.2, "low": 11.0, "close": 12.8, "volume": 1_000_000},
            {"date": "2020-01-07", "open": 12.8, "high": 13.1, "low": 12.4, "close": 12.9, "volume": 1_000_000},
            {"date": "2020-01-08", "open": 13.0, "high": 13.3, "low": 12.5, "close": 13.0, "volume": 1_000_000},
        ]
    )

    regime = build_bullish_fvg_regime_frame(frame, atr_floor=0.25, max_age_bars=1)

    assert regime.iloc[2]["bullish_fvg_regime_active"] is True
    assert regime.iloc[3]["bullish_fvg_regime_active"] is True
    assert regime.iloc[3]["bullish_fvg_regime_age_bars"] == 1
    assert regime.iloc[4]["bullish_fvg_regime_active"] is False
    assert regime.iloc[4]["bullish_fvg_streak"] == 0


def test_build_kama_rows_only_activates_cross_inside_fvg_regime():
    from tradingagents.dealflow.kama_recall import _build_kama_rows

    frame = _cross_fixture_frame()
    dates = pd.to_datetime(frame["date"]).dt.date.astype(str).tolist()
    trigger_date = dates[25]
    inactive_regime = pd.DataFrame(
        {
            "date": frame["date"],
            "bullish_fvg_regime_active": [False] * len(frame),
            "bullish_fvg_streak": [0] * len(frame),
            "bullish_fvg_regime_age_bars": [0] * len(frame),
        }
    )
    active_regime = inactive_regime.copy()
    active_regime.loc[25, "bullish_fvg_regime_active"] = True
    active_regime.loc[25, "bullish_fvg_streak"] = 2

    inactive_rows = _build_kama_rows(symbol="NVDA", frame=frame, fvg_regime_frame=inactive_regime, fvg_confirmed_map={})
    active_rows = _build_kama_rows(symbol="NVDA", frame=frame, fvg_regime_frame=active_regime, fvg_confirmed_map={})

    inactive_event = next(row for row in inactive_rows if row["date"] == trigger_date)
    active_event = next(row for row in active_rows if row["date"] == trigger_date)

    assert inactive_event["cross_up"] is True
    assert inactive_event["kama_active"] is False
    assert active_event["cross_up"] is True
    assert active_event["kama_active"] is True
    assert active_event["bullish_fvg_regime_active"] is True
    assert active_event["bullish_fvg_streak"] == 2


def test_compute_kama_overlap_bucket_summaries_tracks_union():
    from tradingagents.dealflow.kama_recall import compute_kama_overlap_bucket_summaries

    rows = [
        {"ticker": "A", "kama_active": True, "fvg_confirmed": False, "fma_active": False, "forward_return_20d": 0.05, "forward_return_30d": 0.06, "forward_return_60d": 0.09, "forward_return_90d": 0.12},
        {"ticker": "B", "kama_active": False, "fvg_confirmed": True, "fma_active": False, "forward_return_20d": 0.08, "forward_return_30d": 0.09, "forward_return_60d": 0.11, "forward_return_90d": 0.15},
        {"ticker": "C", "kama_active": False, "fvg_confirmed": False, "fma_active": True, "forward_return_20d": 0.07, "forward_return_30d": 0.08, "forward_return_60d": 0.10, "forward_return_90d": 0.13},
        {"ticker": "D", "kama_active": True, "fvg_confirmed": True, "fma_active": True, "forward_return_20d": 0.10, "forward_return_30d": 0.11, "forward_return_60d": 0.14, "forward_return_90d": 0.20},
    ]

    summary = compute_kama_overlap_bucket_summaries(rows)

    assert summary["kama_only"]["event_count"] == 1
    assert summary["fvg_only"]["event_count"] == 1
    assert summary["fma_only"]["event_count"] == 1
    assert summary["kama_and_fvg_and_fma"]["event_count"] == 1
    assert summary["any_signal"]["event_count"] == 4


def test_run_kama_backtest_summary_includes_overlap_breakdown(tmp_path, monkeypatch):
    from tradingagents.dealflow import kama_recall

    alpha = _cross_fixture_frame()
    beta = _steady_frame()
    benchmark = _steady_frame(start_price=80.0, daily_step=0.4)

    monkeypatch.setattr(
        kama_recall,
        "_download_history",
        lambda symbols, start, end: {"NVDA": alpha, "AMD": beta, "SMH": benchmark},
    )

    result = kama_recall.run_kama_backtest(
        tickers=["NVDA", "AMD"],
        start="2020-01-01",
        end="2021-01-01",
        top_n=1,
        artifact_dir=tmp_path / "kama_backtest",
        benchmark="SMH",
    )

    assert result["benchmark"] == "SMH"
    assert result["event_summary"]["event_count"] > 0
    assert "mean_forward_return_30d" in result["event_summary"]
    assert result["parameters"]["fvg_regime_max_age_bars"] == 20
    assert "basket_summary" in result
    assert "avg_forward_return_30d" in result["basket_summary"]
    assert "overlap_summary" in result
    assert "kama_only" in result["overlap_summary"]
    assert "union_summary" in result


def test_run_kama_backtest_resolves_qqq_top20_proxy_universe(tmp_path, monkeypatch):
    from tradingagents.dealflow import kama_recall
    from tradingagents.dealflow import fvg_recall

    frame = _cross_fixture_frame()
    benchmark = _steady_frame(start_price=100.0, daily_step=0.5)
    holdings = pd.DataFrame(
        {
            "Name": ["NVIDIA Corp", "Apple Inc", "Microsoft Corp"],
            "Holding Percent": [0.08, 0.07, 0.06],
        },
        index=["NVDA", "AAPL", "MSFT"],
    )

    class _FundsData:
        top_holdings = holdings

    class _Ticker:
        funds_data = _FundsData()

    monkeypatch.setattr(fvg_recall.yf, "Ticker", lambda symbol: _Ticker())
    monkeypatch.setattr(
        kama_recall,
        "_download_history",
        lambda symbols, start, end: {
            "NVDA": frame,
            "AAPL": frame,
            "MSFT": frame,
            "QQQ": benchmark,
        },
    )

    result = kama_recall.run_kama_backtest(
        universe_name="qqq_top20_proxy",
        benchmark="QQQ",
        start="2020-01-01",
        end="2021-01-01",
        top_n=1,
        artifact_dir=tmp_path / "kama_backtest",
    )

    assert result["tickers"][:3] == ["NVDA", "AAPL", "MSFT"]
    assert len(result["tickers"]) == 20
    assert result["benchmark"] == "QQQ"
