import pandas as pd

from tradingagents.dealflow.sources import price_momentum


def _universe_row(symbol: str):
    return {
        "symbol": symbol,
        "asset_class": "Equity",
        "sector": "Technology",
        "liquidity_score": 90.0,
        "aliases": [symbol.lower()],
    }


def test_price_momentum_handles_unavailable_batch_download(monkeypatch):
    monkeypatch.setattr(price_momentum, "ensure_ohlcv_history", lambda symbols, **kwargs: {})
    signals = price_momentum.collect_price_momentum_signals([_universe_row("AAPL"), _universe_row("TSLA")])
    assert len(signals) == 2
    assert all(signal["source_status"] == "NO_DATA" for signal in signals)


def test_price_momentum_uses_shared_market_cache(monkeypatch):
    idx = pd.date_range("2026-01-01", periods=120, freq="D")
    captured = {}

    def _frame(offset: float):
        base = pd.Series(range(len(idx)), index=idx, dtype=float) + offset
        return pd.DataFrame(
            {
                "Open": base + 100,
                "High": base + 101,
                "Low": base + 99,
                "Close": base + 100,
                "Adj Close": base + 100,
                "Volume": (base + 1) * 1000,
            }
        )

    monkeypatch.setattr(
        price_momentum,
        "ensure_ohlcv_history",
        lambda symbols, **kwargs: captured.update({"symbols": list(symbols), **kwargs}) or {
            "AAPL": _frame(0.0),
            "TSLA": _frame(10.0),
            "SPY": _frame(5.0),
        },
    )
    monkeypatch.setattr(
        price_momentum,
        "_download_prices_batch",
        lambda symbols, period="380d": (_ for _ in ()).throw(AssertionError("raw yf path should not be used")),
    )

    signals = price_momentum.collect_price_momentum_signals([_universe_row("AAPL"), _universe_row("TSLA")])

    assert len(signals) == 2
    assert all(signal["source_status"] == "OK" for signal in signals)
    assert captured["symbols"] == ["AAPL", "TSLA", "SPY"]
    assert captured["min_bars"] == 90
    assert captured["full_period"] == "180d"
