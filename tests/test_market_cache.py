from __future__ import annotations

import pandas as pd

from tradingagents.dealflow.market_cache import (
    ensure_ohlcv_history,
    load_symbol_history,
    market_cache_path,
)


def _frame(start: str, periods: int = 5) -> pd.DataFrame:
    idx = pd.date_range(start=start, periods=periods, freq="D")
    base = pd.Series(range(1, periods + 1), index=idx, dtype=float)
    return pd.DataFrame(
        {
            "Open": base + 10,
            "High": base + 11,
            "Low": base + 9,
            "Close": base + 10,
            "Adj Close": base + 10,
            "Volume": base * 1000,
        }
    )


def test_market_cache_path_is_deterministic_for_index_symbol(tmp_path):
    path = market_cache_path("^VIX", cache_root=tmp_path)
    assert path == tmp_path / "_IDX_VIX.csv"


def test_ensure_ohlcv_history_appends_recent_rows_to_existing_cache(tmp_path):
    existing = _frame("2026-03-01", periods=3)
    existing.to_csv(market_cache_path("AAPL", cache_root=tmp_path))

    calls = []

    def _fetch(symbols, period):
        calls.append((tuple(symbols), period))
        return {"AAPL": _frame("2026-03-03", periods=3)}

    frames = ensure_ohlcv_history(
        ["AAPL"],
        min_bars=2,
        cache_root=tmp_path,
        refresh_period="30d",
        fetch_batch=_fetch,
    )

    assert calls == [(("AAPL",), "30d")]
    cached = load_symbol_history("AAPL", cache_root=tmp_path)
    assert cached is not None
    assert len(cached) == 5
    assert list(frames["AAPL"].index) == list(cached.index)


def test_ensure_ohlcv_history_uses_full_fetch_for_missing_symbol(tmp_path):
    calls = []

    def _fetch(symbols, period):
        calls.append((tuple(symbols), period))
        return {"SPY": _frame("2026-01-01", periods=20)}

    frames = ensure_ohlcv_history(
        ["SPY"],
        min_bars=10,
        cache_root=tmp_path,
        full_period="30d",
        fetch_batch=_fetch,
    )

    assert calls == [(("SPY",), "30d")]
    assert "SPY" in frames
    assert len(frames["SPY"]) == 20


def test_ensure_ohlcv_history_accepts_dataframe_fetcher_result(tmp_path):
    idx = pd.date_range("2026-03-01", periods=3, freq="D")
    raw = pd.DataFrame(
        {
            ("AAPL", "Open"): [99.0, 100.0, 101.0],
            ("AAPL", "High"): [101.0, 102.0, 103.0],
            ("AAPL", "Low"): [98.0, 99.0, 100.0],
            ("AAPL", "Close"): [100.0, 101.0, 102.0],
            ("AAPL", "Adj Close"): [100.0, 101.0, 102.0],
            ("AAPL", "Volume"): [10, 11, 12],
        },
        index=idx,
    )
    raw.columns = pd.MultiIndex.from_tuples(raw.columns)

    frames = ensure_ohlcv_history(
        ["AAPL"],
        min_bars=2,
        cache_root=tmp_path,
        full_period="10d",
        fetch_batch=lambda symbols, period: raw,
    )

    assert "AAPL" in frames
    assert list(frames["AAPL"]["Close"]) == [100.0, 101.0, 102.0]
