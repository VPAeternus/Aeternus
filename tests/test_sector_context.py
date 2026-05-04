from pathlib import Path

import tradingagents.graph.sector_context as sector_context_module
from tradingagents.graph.sector_context import SectorContext


def test_sector_context_uses_baseline_when_yfinance_unavailable(monkeypatch):
    class _FailTicker:
        def __init__(self, symbol):  # pylint: disable=unused-argument
            raise RuntimeError("network unavailable")

    monkeypatch.setattr(sector_context_module.yf, "Ticker", _FailTicker)

    context = SectorContext()
    assert context.get_sector("AAPL") == "Technology"


def test_sector_context_normalizes_symbol_variants(monkeypatch):
    class _FailTicker:
        def __init__(self, symbol):  # pylint: disable=unused-argument
            raise RuntimeError("network unavailable")

    monkeypatch.setattr(sector_context_module.yf, "Ticker", _FailTicker)

    context = SectorContext()
    assert context.get_sector("BRK.B") == "Financials"


def test_sector_context_uses_dealflow_sector_cache(monkeypatch, tmp_path: Path):
    cache_path = tmp_path / "sector_cache.json"
    cache_path.write_text('{"TE": "Industrials"}')
    monkeypatch.setattr(sector_context_module, "SECTOR_CACHE_PATH", cache_path)

    class _EmptyTicker:
        def __init__(self, symbol):  # pylint: disable=unused-argument
            self.info = {}

    monkeypatch.setattr(sector_context_module.yf, "Ticker", _EmptyTicker)

    context = SectorContext()
    assert context.get_sector("TE") == "Industrials"
