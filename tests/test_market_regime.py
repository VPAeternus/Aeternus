import pandas as pd

from tradingagents.graph.market_regime import MarketRegimeProvider


def _mk_df(values):
    idx = pd.date_range("2024-01-01", periods=len(values), freq="D")
    return pd.DataFrame({"Close": values}, index=idx)


def test_market_regime_returns_none_when_insufficient_history():
    def downloader(symbol, period, interval, progress):
        return _mk_df([100.0] * 100)

    provider = MarketRegimeProvider(downloader=downloader)
    assert provider.get_market_regime_snapshot() is None


def test_market_regime_snapshot_success():
    spy_values = [100.0 + (i * 0.5) for i in range(260)]
    vix_values = [17.0 + ((i % 5) * 0.1) for i in range(260)]

    def downloader(symbol, period, interval, progress):
        if symbol == "SPY":
            return _mk_df(spy_values)
        if symbol == "^VIX":
            return _mk_df(vix_values)
        raise AssertionError("Unexpected symbol")

    provider = MarketRegimeProvider(downloader=downloader)
    snapshot = provider.get_market_regime_snapshot()

    assert snapshot is not None
    assert snapshot["spy_close"] > 0
    assert snapshot["spy_sma20"] > 0
    assert snapshot["spy_sma200"] > 0
    assert snapshot["spy_sma200_5d_ago"] > 0
    assert snapshot["vix_close"] > 0

    expected_dev = ((snapshot["spy_close"] - snapshot["spy_sma20"]) / snapshot["spy_sma20"]) * 100.0
    assert abs(snapshot["spy_deviation_pct"] - expected_dev) < 1e-9
