import math

import pandas as pd
import pytest


def _make_ohlcv_frame(rows):
    frame = pd.DataFrame(rows)
    frame["date"] = pd.to_datetime(frame["date"])
    return frame


def _base_rows():
    return [
        {"date": "2025-01-02", "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1_000_000},
        {"date": "2025-01-03", "open": 100.0, "high": 102.0, "low": 98.0, "close": 101.0, "volume": 1_100_000},
        {"date": "2025-01-06", "open": 104.0, "high": 106.0, "low": 103.5, "close": 105.0, "volume": 1_500_000},
        {"date": "2025-01-07", "open": 105.0, "high": 107.0, "low": 104.5, "close": 106.0, "volume": 1_600_000},
    ]


def test_compute_bullish_fvg_snapshot_detects_true_gap():
    from tradingagents.dealflow.fvg_recall import compute_bullish_fvg_snapshot

    frame = _make_ohlcv_frame(_base_rows())

    snapshot = compute_bullish_fvg_snapshot(frame, index=2, atr_floor=0.1)

    assert snapshot["bullish_fvg_present"] is True
    assert snapshot["fvg_size"] == pytest.approx(2.5)
    assert snapshot["fvg_midpoint"] == pytest.approx(102.25)
    assert snapshot["price_above_gap_midpoint"] is True
    assert snapshot["same_direction_fvg_count_10d"] == 1
    assert snapshot["alternating_gap_count_10d"] == 0


def test_compute_bullish_fvg_snapshot_rejects_tiny_gap_below_atr_floor():
    from tradingagents.dealflow.fvg_recall import compute_bullish_fvg_snapshot

    rows = _base_rows()
    rows[2] = {
        "date": "2025-01-06",
        "open": 101.1,
        "high": 102.1,
        "low": 101.1,
        "close": 101.8,
        "volume": 1_500_000,
    }
    frame = _make_ohlcv_frame(rows)

    snapshot = compute_bullish_fvg_snapshot(frame, index=2, atr_floor=0.8)

    assert snapshot["bullish_fvg_present"] is False
    assert snapshot["fvg_size"] == pytest.approx(0.1)
    assert snapshot["fvg_size_atr"] < 0.8


def test_score_bullish_recall_snapshot_rewards_persistent_same_direction_gaps():
    from tradingagents.dealflow.fvg_recall import (
        compute_bullish_fvg_snapshot,
        score_bullish_recall_snapshot,
    )

    persistent_rows = [
        {"date": "2025-01-02", "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1_000_000},
        {"date": "2025-01-03", "open": 101.0, "high": 103.0, "low": 100.0, "close": 102.0, "volume": 1_050_000},
        {"date": "2025-01-06", "open": 104.0, "high": 106.0, "low": 103.5, "close": 105.5, "volume": 1_500_000},
        {"date": "2025-01-07", "open": 105.5, "high": 107.0, "low": 104.5, "close": 106.5, "volume": 1_600_000},
        {"date": "2025-01-08", "open": 108.0, "high": 110.0, "low": 107.5, "close": 109.5, "volume": 1_700_000},
        {"date": "2025-01-09", "open": 109.5, "high": 111.0, "low": 108.5, "close": 110.0, "volume": 1_750_000},
    ]
    choppy_rows = [
        {"date": "2025-01-02", "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1_000_000},
        {"date": "2025-01-03", "open": 101.0, "high": 103.0, "low": 100.0, "close": 102.0, "volume": 1_050_000},
        {"date": "2025-01-06", "open": 104.0, "high": 106.0, "low": 103.5, "close": 105.5, "volume": 1_500_000},
        {"date": "2025-01-07", "open": 103.0, "high": 103.4, "low": 100.5, "close": 101.0, "volume": 1_250_000},
        {"date": "2025-01-08", "open": 105.5, "high": 107.0, "low": 104.6, "close": 106.2, "volume": 1_450_000},
        {"date": "2025-01-09", "open": 102.0, "high": 102.3, "low": 99.0, "close": 100.1, "volume": 1_200_000},
    ]

    benchmark = _make_ohlcv_frame([
        {"date": "2025-01-02", "open": 100.0, "high": 100.4, "low": 99.7, "close": 100.0, "volume": 5_000_000},
        {"date": "2025-01-03", "open": 100.2, "high": 100.6, "low": 100.0, "close": 100.4, "volume": 5_000_000},
        {"date": "2025-01-06", "open": 100.3, "high": 100.7, "low": 100.1, "close": 100.6, "volume": 5_000_000},
        {"date": "2025-01-07", "open": 100.4, "high": 100.8, "low": 100.2, "close": 100.7, "volume": 5_000_000},
        {"date": "2025-01-08", "open": 100.5, "high": 100.9, "low": 100.3, "close": 100.8, "volume": 5_000_000},
        {"date": "2025-01-09", "open": 100.6, "high": 101.0, "low": 100.4, "close": 100.9, "volume": 5_000_000},
    ])

    persistent_snapshot = compute_bullish_fvg_snapshot(
        _make_ohlcv_frame(persistent_rows),
        index=5,
        benchmark_frame=benchmark,
        atr_floor=0.1,
    )
    choppy_snapshot = compute_bullish_fvg_snapshot(
        _make_ohlcv_frame(choppy_rows),
        index=5,
        benchmark_frame=benchmark,
        atr_floor=0.1,
    )

    persistent_score = score_bullish_recall_snapshot(persistent_snapshot)
    choppy_score = score_bullish_recall_snapshot(choppy_snapshot)

    assert persistent_snapshot["same_direction_fvg_count_10d"] > choppy_snapshot["same_direction_fvg_count_10d"]
    assert persistent_score > choppy_score


def test_compute_bullish_fvg_snapshot_is_point_in_time_only():
    from tradingagents.dealflow.fvg_recall import compute_bullish_fvg_snapshot

    frame = _make_ohlcv_frame([
        {"date": "2025-01-02", "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1_000_000},
        {"date": "2025-01-03", "open": 101.0, "high": 102.0, "low": 100.0, "close": 101.0, "volume": 1_100_000},
        {"date": "2025-01-06", "open": 104.0, "high": 106.0, "low": 103.0, "close": 105.0, "volume": 1_500_000},
        {"date": "2025-01-07", "open": 105.0, "high": 107.0, "low": 104.0, "close": 106.0, "volume": 1_600_000},
        {"date": "2025-01-08", "open": 106.0, "high": 107.0, "low": 105.0, "close": 106.5, "volume": 1_650_000},
    ])
    mutated = frame.copy()
    mutated.loc[3:, ["high", "low", "close", "volume"]] = [200.0, 50.0, 180.0, 9_999_999]

    original = compute_bullish_fvg_snapshot(frame, index=2, atr_floor=0.1)
    changed_future = compute_bullish_fvg_snapshot(mutated, index=2, atr_floor=0.1)

    assert original == changed_future
    assert math.isfinite(original["fvg_size_atr"])


def test_classify_simple_regime_prefers_high_vol_over_trend():
    from tradingagents.dealflow.fvg_recall import classify_simple_regime

    benchmark = _make_ohlcv_frame([
        {"date": "2025-01-02", "open": 100.0, "high": 101.0, "low": 99.5, "close": 100.0, "volume": 1_000_000},
        {"date": "2025-01-03", "open": 100.5, "high": 101.4, "low": 100.1, "close": 100.9, "volume": 1_050_000},
        {"date": "2025-01-06", "open": 101.0, "high": 102.0, "low": 100.6, "close": 101.4, "volume": 1_050_000},
        {"date": "2025-01-07", "open": 101.6, "high": 103.0, "low": 95.0, "close": 102.5, "volume": 1_050_000},
        {"date": "2025-01-08", "open": 102.7, "high": 103.4, "low": 101.5, "close": 103.0, "volume": 1_050_000},
    ])

    assert classify_simple_regime(benchmark, index=4) == "high_vol"


def test_build_confirmation_slice_flags_tracks_explicit_stack():
    from tradingagents.dealflow.fvg_recall import build_confirmation_slice_flags

    raw = build_confirmation_slice_flags(
        bullish_fvg_present=True,
        relative_strength_20d=0.01,
        trend_alignment_20_50_200=40.0,
        volume_zscore_20d=0.1,
        price_above_sma20=False,
        sma20_above_sma50=False,
        sma50_above_sma200=False,
    )
    stacked = build_confirmation_slice_flags(
        bullish_fvg_present=True,
        relative_strength_20d=0.08,
        trend_alignment_20_50_200=88.0,
        volume_zscore_20d=1.9,
        price_above_sma20=True,
        sma20_above_sma50=True,
        sma50_above_sma200=True,
    )

    assert raw["raw_fvg"] is True
    assert raw["fvg_plus_rs"] is False
    assert raw["fvg_plus_rs_above_sma20"] is False
    assert raw["fvg_plus_rs_sma20_above_sma50"] is False
    assert raw["fvg_plus_rs_sma50_above_sma200"] is False
    assert raw["fvg_plus_rs_full_stack"] is False
    assert raw["fvg_plus_rs_trend"] is False
    assert raw["fvg_plus_rs_trend_volume"] is False

    assert stacked["raw_fvg"] is True
    assert stacked["fvg_plus_rs"] is True
    assert stacked["fvg_plus_rs_above_sma20"] is True
    assert stacked["fvg_plus_rs_sma20_above_sma50"] is True
    assert stacked["fvg_plus_rs_sma50_above_sma200"] is True
    assert stacked["fvg_plus_rs_full_stack"] is True
    assert stacked["fvg_plus_rs_trend"] is True
    assert stacked["fvg_plus_rs_trend_volume"] is True


def test_run_fvg_backtest_summary_includes_regime_and_slice_breakdown(tmp_path, monkeypatch):
    from tradingagents.dealflow import fvg_recall

    history = _make_ohlcv_frame([
        {"date": "2025-01-02", "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1_000_000},
        {"date": "2025-01-03", "open": 101.0, "high": 103.0, "low": 100.0, "close": 102.0, "volume": 1_050_000},
        {"date": "2025-01-06", "open": 104.0, "high": 106.0, "low": 103.5, "close": 105.5, "volume": 1_500_000},
        {"date": "2025-01-07", "open": 105.5, "high": 107.0, "low": 104.5, "close": 106.5, "volume": 1_600_000},
        {"date": "2025-01-08", "open": 108.0, "high": 110.0, "low": 107.5, "close": 109.5, "volume": 1_700_000},
        {"date": "2025-01-09", "open": 109.5, "high": 111.0, "low": 108.5, "close": 110.0, "volume": 1_750_000},
        {"date": "2025-01-10", "open": 110.5, "high": 112.0, "low": 109.0, "close": 111.0, "volume": 1_800_000},
    ])
    benchmark = _make_ohlcv_frame([
        {"date": "2025-01-02", "open": 100.0, "high": 100.5, "low": 99.7, "close": 100.0, "volume": 5_000_000},
        {"date": "2025-01-03", "open": 100.3, "high": 100.8, "low": 100.0, "close": 100.4, "volume": 5_000_000},
        {"date": "2025-01-06", "open": 100.5, "high": 101.0, "low": 100.3, "close": 100.8, "volume": 5_000_000},
        {"date": "2025-01-07", "open": 100.8, "high": 101.2, "low": 100.4, "close": 101.0, "volume": 5_000_000},
        {"date": "2025-01-08", "open": 101.0, "high": 101.4, "low": 100.6, "close": 101.2, "volume": 5_000_000},
        {"date": "2025-01-09", "open": 101.3, "high": 101.7, "low": 100.9, "close": 101.5, "volume": 5_000_000},
        {"date": "2025-01-10", "open": 101.4, "high": 101.8, "low": 101.0, "close": 101.6, "volume": 5_000_000},
    ])

    monkeypatch.setattr(
        fvg_recall,
        "_download_history",
        lambda symbols, start, end: {"NVDA": history, "SMH": benchmark},
    )

    result = fvg_recall.run_fvg_backtest(
        tickers=["NVDA"],
        start="2025-01-02",
        end="2025-01-11",
        top_n=1,
        artifact_dir=tmp_path / "fvg_backtest",
    )

    assert "by_regime" in result
    assert "by_era" in result
    assert "by_slice" in result
    assert "basket_by_slice" in result
    assert "raw_fvg" in result["by_slice"]
    assert "raw_fvg" in result["basket_by_slice"]
    assert "fvg_plus_rs_above_sma20" in result["by_slice"]
    assert "fvg_plus_rs_sma20_above_sma50" in result["by_slice"]
    assert "fvg_plus_rs_sma50_above_sma200" in result["by_slice"]
    assert "fvg_plus_rs_full_stack" in result["by_slice"]
    assert "avg_edge_vs_benchmark_20d" in result["basket_summary"]
    assert "avg_edge_vs_benchmark_60d" in result["basket_summary"]
    assert "avg_edge_vs_benchmark_20d" in result["basket_by_slice"]["raw_fvg"]
    assert "avg_edge_vs_benchmark_60d" in result["basket_by_slice"]["raw_fvg"]


def test_market_era_label_maps_known_periods():
    from tradingagents.dealflow.fvg_recall import market_era_label

    assert market_era_label("2000-03-10") == "1999_2002_dotcom"
    assert market_era_label("2009-07-15") == "2008_2012_crisis_recovery"
    assert market_era_label("2024-11-05") == "2024_2026_ai_cycle"


def test_run_fvg_backtest_uses_unknown_regime_when_benchmark_history_is_shorter(tmp_path, monkeypatch):
    from tradingagents.dealflow import fvg_recall

    history = _make_ohlcv_frame([
        {"date": "2025-01-02", "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1_000_000},
        {"date": "2025-01-03", "open": 101.0, "high": 103.0, "low": 100.0, "close": 102.0, "volume": 1_050_000},
        {"date": "2025-01-06", "open": 104.0, "high": 106.0, "low": 103.5, "close": 105.5, "volume": 1_500_000},
        {"date": "2025-01-07", "open": 105.5, "high": 107.0, "low": 104.5, "close": 106.5, "volume": 1_600_000},
        {"date": "2025-01-08", "open": 108.0, "high": 110.0, "low": 107.5, "close": 109.5, "volume": 1_700_000},
        {"date": "2025-01-09", "open": 109.5, "high": 111.0, "low": 108.5, "close": 110.0, "volume": 1_750_000},
        {"date": "2025-01-10", "open": 110.5, "high": 112.0, "low": 109.0, "close": 111.0, "volume": 1_800_000},
    ])
    short_benchmark = _make_ohlcv_frame([
        {"date": "2025-01-08", "open": 101.0, "high": 101.4, "low": 100.6, "close": 101.2, "volume": 5_000_000},
        {"date": "2025-01-09", "open": 101.3, "high": 101.7, "low": 100.9, "close": 101.5, "volume": 5_000_000},
        {"date": "2025-01-10", "open": 101.4, "high": 101.8, "low": 101.0, "close": 101.6, "volume": 5_000_000},
    ])

    monkeypatch.setattr(
        fvg_recall,
        "_download_history",
        lambda symbols, start, end: {"NVDA": history, "SMH": short_benchmark},
    )

    result = fvg_recall.run_fvg_backtest(
        tickers=["NVDA"],
        start="2025-01-02",
        end="2025-01-11",
        top_n=1,
        artifact_dir=tmp_path / "fvg_backtest",
    )

    assert "unknown" in result["by_regime"]
    assert "nan" not in result["by_regime"]


def test_run_fvg_backtest_resolves_qqq_top20_proxy_universe(tmp_path, monkeypatch):
    from tradingagents.dealflow import fvg_recall

    history = _make_ohlcv_frame([
        {"date": "2025-01-02", "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1_000_000},
        {"date": "2025-01-03", "open": 101.0, "high": 103.0, "low": 100.0, "close": 102.0, "volume": 1_050_000},
        {"date": "2025-01-06", "open": 104.0, "high": 106.0, "low": 103.5, "close": 105.5, "volume": 1_500_000},
        {"date": "2025-01-07", "open": 105.5, "high": 107.0, "low": 104.5, "close": 106.5, "volume": 1_600_000},
        {"date": "2025-01-08", "open": 108.0, "high": 110.0, "low": 107.5, "close": 109.5, "volume": 1_700_000},
        {"date": "2025-01-09", "open": 109.5, "high": 111.0, "low": 108.5, "close": 110.0, "volume": 1_750_000},
        {"date": "2025-01-10", "open": 110.5, "high": 112.0, "low": 109.0, "close": 111.0, "volume": 1_800_000},
    ])
    benchmark = _make_ohlcv_frame([
        {"date": "2025-01-02", "open": 100.0, "high": 100.5, "low": 99.7, "close": 100.0, "volume": 5_000_000},
        {"date": "2025-01-03", "open": 100.3, "high": 100.8, "low": 100.0, "close": 100.4, "volume": 5_000_000},
        {"date": "2025-01-06", "open": 100.5, "high": 101.0, "low": 100.3, "close": 100.8, "volume": 5_000_000},
        {"date": "2025-01-07", "open": 100.8, "high": 101.2, "low": 100.4, "close": 101.0, "volume": 5_000_000},
        {"date": "2025-01-08", "open": 101.0, "high": 101.4, "low": 100.6, "close": 101.2, "volume": 5_000_000},
        {"date": "2025-01-09", "open": 101.3, "high": 101.7, "low": 100.9, "close": 101.5, "volume": 5_000_000},
        {"date": "2025-01-10", "open": 101.4, "high": 101.8, "low": 101.0, "close": 101.6, "volume": 5_000_000},
    ])
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
        fvg_recall,
        "_download_history",
        lambda symbols, start, end: {
            "NVDA": history,
            "AAPL": history,
            "MSFT": history,
            "QQQ": benchmark,
        },
    )

    result = fvg_recall.run_fvg_backtest(
        universe_name="qqq_top20_proxy",
        benchmark="QQQ",
        start="2025-01-02",
        end="2025-01-11",
        top_n=1,
        artifact_dir=tmp_path / "fvg_backtest",
    )

    assert result["tickers"][:3] == ["NVDA", "AAPL", "MSFT"]
    assert len(result["tickers"]) == 20
    assert result["benchmark"] == "QQQ"


def test_run_fvg_backtest_default_artifact_dir_includes_universe_and_benchmark(tmp_path, monkeypatch):
    from tradingagents.dealflow import fvg_recall

    history = _make_ohlcv_frame([
        {"date": "2025-01-02", "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1_000_000},
        {"date": "2025-01-03", "open": 101.0, "high": 103.0, "low": 100.0, "close": 102.0, "volume": 1_050_000},
        {"date": "2025-01-06", "open": 104.0, "high": 106.0, "low": 103.5, "close": 105.5, "volume": 1_500_000},
        {"date": "2025-01-07", "open": 105.5, "high": 107.0, "low": 104.5, "close": 106.5, "volume": 1_600_000},
        {"date": "2025-01-08", "open": 108.0, "high": 110.0, "low": 107.5, "close": 109.5, "volume": 1_700_000},
        {"date": "2025-01-09", "open": 109.5, "high": 111.0, "low": 108.5, "close": 110.0, "volume": 1_750_000},
        {"date": "2025-01-10", "open": 110.5, "high": 112.0, "low": 109.0, "close": 111.0, "volume": 1_800_000},
    ])
    benchmark = history.copy()

    class _FakeDate:
        @staticmethod
        def today():
            return pd.Timestamp("2026-03-06").date()

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(fvg_recall, "date", _FakeDate)
    monkeypatch.setattr(
        fvg_recall,
        "_download_history",
        lambda symbols, start, end: {"NVDA": history, "QQQ": benchmark},
    )

    result = fvg_recall.run_fvg_backtest(
        tickers=["NVDA"],
        universe_name="qqq_top20_proxy",
        benchmark="QQQ",
        start="2025-01-02",
        end="2025-01-11",
        top_n=1,
    )

    assert result["artifact_dir"].endswith("eval_results/deal_flow/fvg_backtest/2026-03-06/qqq_top20_proxy-vs-QQQ")


def test_get_current_qqq_top_holdings_fills_to_twenty_when_primary_source_is_short(monkeypatch):
    from tradingagents.dealflow import fvg_recall

    primary_holdings = pd.DataFrame(
        {
            "Name": [f"Name {idx}" for idx in range(1, 11)],
            "Holding Percent": [0.10 - idx * 0.005 for idx in range(10)],
        },
        index=[f"T{idx:02d}" for idx in range(1, 11)],
    )
    fallback_table = pd.DataFrame(
        {
            "No.": list(range(1, 21)),
            "Symbol": [f"T{idx:02d}" for idx in range(1, 21)],
            "Name": [f"Name {idx}" for idx in range(1, 21)],
            "% Weight": [f"{10 - idx * 0.1:.2f}%" for idx in range(1, 21)],
            "Shares": [1_000_000 - idx for idx in range(1, 21)],
        }
    )

    class _FundsData:
        top_holdings = primary_holdings

    class _Ticker:
        funds_data = _FundsData()

    class _Response:
        text = fallback_table.to_html(index=False)

        def raise_for_status(self):
            return None

    monkeypatch.setattr(fvg_recall.yf, "Ticker", lambda symbol: _Ticker())
    monkeypatch.setattr(fvg_recall.requests, "get", lambda *args, **kwargs: _Response())

    symbols = fvg_recall.get_current_qqq_top_holdings(limit=20)

    assert len(symbols) == 20
    assert symbols[:3] == ["T01", "T02", "T03"]
    assert symbols[-1] == "T20"


def _make_trending_frame(
    *,
    periods: int = 240,
    start_date: str = "2020-01-01",
    start_price: float = 100.0,
    daily_step: float = 0.5,
) -> pd.DataFrame:
    dates = pd.date_range(start=start_date, periods=periods, freq="B")
    rows = []
    price = start_price
    for current in dates:
        open_price = price
        close_price = price + daily_step
        rows.append(
            {
                "date": current,
                "open": open_price,
                "high": close_price + 1.0,
                "low": open_price - 1.0,
                "close": close_price,
                "volume": 1_000_000,
            }
        )
        price += daily_step
    return pd.DataFrame(rows)


def test_run_fvg_strategy_backtest_exits_on_close_below_sma50(monkeypatch, tmp_path):
    from tradingagents.dealflow import fvg_recall

    qqq = _make_trending_frame()
    spy = _make_trending_frame(start_price=90.0, daily_step=0.2)
    entry_index = 205
    qqq.loc[entry_index, ["high", "low", "close"]] = [210.0, 208.0, 209.5]
    qqq.loc[entry_index - 2, "high"] = 205.0
    qqq.loc[entry_index + 1, "open"] = 210.0
    qqq.loc[entry_index + 5, "close"] = 120.0
    qqq.loc[entry_index + 6, "open"] = 119.0

    monkeypatch.setattr(
        fvg_recall,
        "_download_history",
        lambda symbols, start, end: {"QQQ": qqq, "SPY": spy},
    )

    result = fvg_recall.run_fvg_strategy_backtest(
        ticker="QQQ",
        benchmark="SPY",
        start="2020-01-01",
        end="2020-12-31",
        artifact_dir=tmp_path / "strategy",
    )

    assert result["total_trades"] >= 1
    assert result["exit_reason_counts"]["close_below_sma50"] >= 1
    trade = result["trades"][0]
    assert trade["exit_reason"] == "close_below_sma50"
    assert trade["entry_price"] == pytest.approx(210.0)
    assert trade["exit_price"] == pytest.approx(119.0)


def test_run_fvg_strategy_backtest_exits_on_timeout(monkeypatch, tmp_path):
    from tradingagents.dealflow import fvg_recall

    qqq = _make_trending_frame(periods=340)
    spy = _make_trending_frame(periods=340, start_price=90.0, daily_step=0.2)
    entry_index = 205
    qqq.loc[entry_index, ["high", "low", "close"]] = [210.0, 208.0, 209.5]
    qqq.loc[entry_index - 2, "high"] = 205.0
    qqq.loc[entry_index + 1, "open"] = 210.0

    monkeypatch.setattr(
        fvg_recall,
        "_download_history",
        lambda symbols, start, end: {"QQQ": qqq, "SPY": spy},
    )

    result = fvg_recall.run_fvg_strategy_backtest(
        ticker="QQQ",
        benchmark="SPY",
        start="2020-01-01",
        end="2021-06-01",
        max_hold_days=90,
        artifact_dir=tmp_path / "strategy",
    )

    assert result["exit_reason_counts"]["timeout_90d"] >= 1
    assert result["trades"][0]["exit_reason"] == "timeout_90d"


def test_run_fvg_strategy_backtest_exits_on_midpoint_and_rs_break(monkeypatch, tmp_path):
    from tradingagents.dealflow import fvg_recall

    qqq = _make_trending_frame(periods=260)
    spy = _make_trending_frame(periods=260, start_price=90.0, daily_step=0.6)
    entry_index = 205
    qqq.loc[entry_index, ["high", "low", "close"]] = [210.0, 208.0, 209.5]
    qqq.loc[entry_index - 2, "high"] = 205.0
    qqq.loc[entry_index + 1, "open"] = 210.0
    qqq.loc[entry_index + 3, "close"] = 206.0
    qqq.loc[entry_index + 4, "open"] = 205.5

    monkeypatch.setattr(
        fvg_recall,
        "_download_history",
        lambda symbols, start, end: {"QQQ": qqq, "SPY": spy},
    )

    result = fvg_recall.run_fvg_strategy_backtest(
        ticker="QQQ",
        benchmark="SPY",
        start="2020-01-01",
        end="2021-02-01",
        artifact_dir=tmp_path / "strategy",
    )

    assert result["exit_reason_counts"]["fvg_midpoint_rs_break"] >= 1
    assert result["trades"][0]["exit_reason"] == "fvg_midpoint_rs_break"


def test_run_fvg_strategy_backtest_supports_explicit_exit_modes(monkeypatch, tmp_path):
    from tradingagents.dealflow import fvg_recall

    qqq = _make_trending_frame(periods=340)
    spy = _make_trending_frame(periods=340, start_price=90.0, daily_step=0.2)
    entry_index = 205
    qqq.loc[entry_index, ["high", "low", "close"]] = [210.0, 208.0, 209.5]
    qqq.loc[entry_index - 2, "high"] = 205.0
    qqq.loc[entry_index + 1, "open"] = 210.0

    monkeypatch.setattr(
        fvg_recall,
        "_download_history",
        lambda symbols, start, end: {"QQQ": qqq, "SPY": spy},
    )

    exit_c = fvg_recall.run_fvg_strategy_backtest(
        ticker="QQQ",
        benchmark="SPY",
        start="2020-01-01",
        end="2021-06-01",
        max_hold_days=90,
        artifact_dir=tmp_path / "exit_c",
        exit_mode="exit_c",
    )
    timeout_only = fvg_recall.run_fvg_strategy_backtest(
        ticker="QQQ",
        benchmark="SPY",
        start="2020-01-01",
        end="2021-06-01",
        max_hold_days=90,
        artifact_dir=tmp_path / "timeout",
        exit_mode="timeout_90d_only",
    )

    assert exit_c["total_trades"] >= 1
    assert timeout_only["total_trades"] >= 1
    assert timeout_only["exit_reason_counts"]["timeout_90d"] >= 1


def test_run_fvg_strategy_backtest_supports_signal_close_execution(monkeypatch, tmp_path):
    from tradingagents.dealflow import fvg_recall

    qqq = _make_trending_frame(periods=260)
    spy = _make_trending_frame(periods=260, start_price=90.0, daily_step=0.2)
    entry_index = 205
    qqq.loc[entry_index, ["high", "low", "close"]] = [210.0, 208.0, 209.5]
    qqq.loc[entry_index - 2, "high"] = 205.0
    qqq.loc[entry_index + 1, "open"] = 210.0
    qqq.loc[entry_index + 5, "close"] = 120.0
    qqq.loc[entry_index + 6, "open"] = 119.0

    monkeypatch.setattr(
        fvg_recall,
        "_download_history",
        lambda symbols, start, end: {"QQQ": qqq, "SPY": spy},
    )

    result = fvg_recall.run_fvg_strategy_backtest(
        ticker="QQQ",
        benchmark="SPY",
        start="2020-01-01",
        end="2021-02-01",
        artifact_dir=tmp_path / "strategy",
        execution_timing="signal_close",
    )

    trade = result["trades"][0]
    assert trade["entry_date"] == qqq.loc[entry_index, "date"].date().isoformat()
    assert trade["entry_price"] == pytest.approx(209.5)
    assert trade["exit_date"] == qqq.loc[entry_index + 5, "date"].date().isoformat()
    assert trade["exit_price"] == pytest.approx(120.0)


def test_run_fvg_strategy_exit_comparison_includes_buy_and_hold(monkeypatch, tmp_path):
    from tradingagents.dealflow import fvg_recall

    qqq = _make_trending_frame(periods=340)
    spy = _make_trending_frame(periods=340, start_price=90.0, daily_step=0.2)
    entry_index = 205
    qqq.loc[entry_index, ["high", "low", "close"]] = [210.0, 208.0, 209.5]
    qqq.loc[entry_index - 2, "high"] = 205.0
    qqq.loc[entry_index + 1, "open"] = 210.0

    monkeypatch.setattr(
        fvg_recall,
        "_download_history",
        lambda symbols, start, end: {"QQQ": qqq, "SPY": spy},
    )

    result = fvg_recall.run_fvg_strategy_exit_comparison(
        ticker="QQQ",
        benchmark="SPY",
        start="2020-01-01",
        end="2021-06-01",
        artifact_dir=tmp_path / "comparison",
    )

    assert set(result["strategies"].keys()) == {"exit_c", "sma50_only", "timeout_90d_only", "buy_and_hold"}
    assert "total_return" in result["strategies"]["buy_and_hold"]


def test_run_fvg_strategy_exit_comparison_threads_execution_timing(monkeypatch, tmp_path):
    from tradingagents.dealflow import fvg_recall

    qqq = _make_trending_frame(periods=340)
    spy = _make_trending_frame(periods=340, start_price=90.0, daily_step=0.2)
    entry_index = 205
    qqq.loc[entry_index, ["high", "low", "close"]] = [210.0, 208.0, 209.5]
    qqq.loc[entry_index - 2, "high"] = 205.0
    qqq.loc[entry_index + 1, "open"] = 210.0

    monkeypatch.setattr(
        fvg_recall,
        "_download_history",
        lambda symbols, start, end: {"QQQ": qqq, "SPY": spy},
    )

    result = fvg_recall.run_fvg_strategy_exit_comparison(
        ticker="QQQ",
        benchmark="SPY",
        start="2020-01-01",
        end="2021-06-01",
        artifact_dir=tmp_path / "comparison",
        execution_timing="signal_close",
    )

    assert result["strategies"]["exit_c"]["execution_timing"] == "signal_close"
    assert result["strategies"]["sma50_only"]["execution_timing"] == "signal_close"
    assert result["strategies"]["timeout_90d_only"]["execution_timing"] == "signal_close"
