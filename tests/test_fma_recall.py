import pandas as pd
import pytest


def _make_ohlcv_frame(rows):
    frame = pd.DataFrame(rows)
    frame["date"] = pd.to_datetime(frame["date"])
    return frame


def _make_momentum_frame(
    *,
    periods: int = 260,
    start_date: str = "2020-01-01",
    start_price: float = 100.0,
    daily_step: float = 0.4,
    volume_base: float = 1_000_000,
    volume_step: float = 2_000.0,
):
    dates = pd.date_range(start=start_date, periods=periods, freq="B")
    rows = []
    price = start_price
    for idx, current in enumerate(dates):
        open_price = price
        close_price = price + daily_step
        rows.append(
            {
                "date": current,
                "open": open_price,
                "high": close_price + 1.0,
                "low": open_price - 1.0,
                "close": close_price,
                "volume": volume_base + idx * volume_step,
            }
        )
        price += daily_step
    return pd.DataFrame(rows)


def test_compute_fma_snapshot_includes_live_components():
    from tradingagents.dealflow.fma_recall import compute_fma_snapshot

    frame = _make_momentum_frame(periods=260, daily_step=0.6, volume_base=2_000_000)
    benchmark = _make_momentum_frame(periods=260, start_price=90.0, daily_step=0.2, volume_base=4_000_000)

    snapshot = compute_fma_snapshot(frame, index=220, benchmark_frame=benchmark, variant="fma_live")

    assert snapshot["variant"] == "fma_live"
    assert snapshot["velocity_60d"] > 0.0
    assert snapshot["mass_ratio"] > 0.0
    assert snapshot["force_value"] == pytest.approx(snapshot["mass_ratio"] * snapshot["accel_value"])
    assert "relative_strength_60d" in snapshot


def test_score_fma_cross_section_prefers_stronger_snapshot():
    from tradingagents.dealflow.fma_recall import score_fma_cross_section

    snapshots = [
        {
            "ticker": "FAST",
            "variant": "fma_live",
            "valid": True,
            "velocity_60d": 0.30,
            "accel_value": 0.12,
            "mass_ratio": 1.8,
            "force_value": 0.216,
            "relative_strength_60d": 0.15,
        },
        {
            "ticker": "SLOW",
            "variant": "fma_live",
            "valid": True,
            "velocity_60d": 0.05,
            "accel_value": 0.01,
            "mass_ratio": 1.1,
            "force_value": 0.011,
            "relative_strength_60d": 0.02,
        },
    ]

    scored = score_fma_cross_section(snapshots, variant="fma_live")

    assert scored["FAST"] > scored["SLOW"]
    assert 0.0 <= scored["FAST"] <= 100.0
    assert 0.0 <= scored["SLOW"] <= 100.0


def test_compute_overlap_bucket_summaries_tracks_fvg_and_fma_union():
    from tradingagents.dealflow.fma_recall import compute_overlap_bucket_summaries

    rows = [
        {"ticker": "A", "fvg_confirmed": True, "fma_active": False, "forward_return_20d": 0.10, "forward_return_60d": 0.15, "forward_return_90d": 0.20},
        {"ticker": "B", "fvg_confirmed": False, "fma_active": True, "forward_return_20d": 0.08, "forward_return_60d": 0.10, "forward_return_90d": 0.12},
        {"ticker": "C", "fvg_confirmed": True, "fma_active": True, "forward_return_20d": 0.12, "forward_return_60d": 0.18, "forward_return_90d": 0.25},
    ]

    summary = compute_overlap_bucket_summaries(rows)

    assert summary["fvg_only"]["event_count"] == 1
    assert summary["fma_only"]["event_count"] == 1
    assert summary["fvg_and_fma"]["event_count"] == 1
    assert summary["fvg_or_fma"]["event_count"] == 3


def test_run_fma_backtest_summary_includes_variants_and_overlap_breakdown(tmp_path, monkeypatch):
    from tradingagents.dealflow import fma_recall

    alpha = _make_momentum_frame(periods=260, daily_step=0.7, volume_base=2_500_000)
    beta = _make_momentum_frame(periods=260, daily_step=0.25, volume_base=1_100_000)
    benchmark = _make_momentum_frame(periods=260, start_price=90.0, daily_step=0.2, volume_base=4_000_000)

    monkeypatch.setattr(
        fma_recall,
        "_download_history",
        lambda symbols, start, end: {"NVDA": alpha, "AMD": beta, "SMH": benchmark},
    )

    result = fma_recall.run_fma_backtest(
        tickers=["NVDA", "AMD"],
        start="2020-01-01",
        end="2021-01-01",
        top_n=1,
        artifact_dir=tmp_path / "fma_backtest",
        benchmark="SMH",
    )

    assert result["benchmark"] == "SMH"
    assert "variant_summaries" in result
    assert "fma_live" in result["variant_summaries"]
    assert "fma_best_shadow" in result["variant_summaries"]
    assert "basket_summary" in result["variant_summaries"]["fma_live"]
    assert "overlap_summary" in result
    assert "fvg_only" in result["overlap_summary"]
    assert "basket_summary" in result["union_summary"]


def test_run_fma_backtest_resolves_qqq_top20_proxy_universe(tmp_path, monkeypatch):
    from tradingagents.dealflow import fma_recall

    frame = _make_momentum_frame(periods=260)
    benchmark = _make_momentum_frame(periods=260, start_price=90.0, daily_step=0.2, volume_base=4_000_000)
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

    monkeypatch.setattr(fma_recall.yf, "Ticker", lambda symbol: _Ticker())
    monkeypatch.setattr(
        fma_recall,
        "_download_history",
        lambda symbols, start, end: {
            "NVDA": frame,
            "AAPL": frame,
            "MSFT": frame,
            "QQQ": benchmark,
        },
    )

    result = fma_recall.run_fma_backtest(
        universe_name="qqq_top20_proxy",
        benchmark="QQQ",
        start="2020-01-01",
        end="2021-01-01",
        top_n=1,
        artifact_dir=tmp_path / "fma_backtest",
    )

    assert result["tickers"][:3] == ["NVDA", "AAPL", "MSFT"]
    assert len(result["tickers"]) == 20
    assert result["benchmark"] == "QQQ"
