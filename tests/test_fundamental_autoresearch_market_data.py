import pandas as pd

from tradingagents.research.fundamental_autoresearch.market_data import (
    _yf_ticker,
    attach_forward_returns,
    download_adjusted_close_history,
)


def test_attach_forward_returns_uses_first_tradable_session_on_or_after_effective_date():
    index = pd.bdate_range("2026-01-30", periods=300)
    close_map = {
        "AAPL": pd.Series(range(100, 400), index=index, dtype=float),
    }
    rows = [
        {
            "ticker": "AAPL",
            "effective_market_date": "2026-01-31",
        }
    ]

    enriched = attach_forward_returns(rows, close_map=close_map)

    base = close_map["AAPL"].iloc[1]
    assert enriched[0]["return_20d"] == (close_map["AAPL"].iloc[21] / base) - 1.0
    assert enriched[0]["return_60d"] == (close_map["AAPL"].iloc[61] / base) - 1.0
    assert enriched[0]["return_120d"] == (close_map["AAPL"].iloc[121] / base) - 1.0
    assert enriched[0]["return_252d"] == (close_map["AAPL"].iloc[253] / base) - 1.0


def test_attach_forward_returns_returns_none_when_price_history_missing():
    rows = [
        {
            "ticker": "AAPL",
            "effective_market_date": "2026-01-31",
        }
    ]

    enriched = attach_forward_returns(rows, close_map={})

    assert enriched[0]["return_20d"] is None
    assert enriched[0]["return_60d"] is None
    assert enriched[0]["return_120d"] is None
    assert enriched[0]["return_252d"] is None


def test_download_adjusted_close_history_maps_dot_tickers_to_yfinance_alias(monkeypatch):
    index = pd.bdate_range("2026-01-30", periods=5)
    frame = pd.concat(
        {
            "Close": pd.DataFrame(
                {
                    _yf_ticker("BRK.B"): [500.0, 505.0, 510.0, 515.0, 520.0],
                },
                index=index,
            )
        },
        axis=1,
    )

    def _fake_download(*, tickers, **kwargs):
        assert tickers == ["BRK-B"]
        return frame

    monkeypatch.setattr("yfinance.download", _fake_download)

    close_map = download_adjusted_close_history(
        [{"ticker": "BRK.B", "effective_market_date": "2026-01-30"}]
    )

    assert "BRK.B" in close_map
    assert list(close_map["BRK.B"]) == [500.0, 505.0, 510.0, 515.0, 520.0]
