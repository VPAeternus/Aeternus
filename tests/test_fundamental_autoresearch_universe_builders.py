import json
from pathlib import Path

from tradingagents.research.fundamental_autoresearch.universe_builders import (
    load_research_universe,
    select_sector_balanced_universe,
    write_research_universe,
)


def test_select_sector_balanced_universe_applies_liquidity_and_sector_caps():
    rows = [
        {"ticker": "AAPL", "sector": "Technology", "avg_dollar_volume_60d": 100_000_000.0, "last_close": 200.0},
        {"ticker": "MSFT", "sector": "Technology", "avg_dollar_volume_60d": 90_000_000.0, "last_close": 300.0},
        {"ticker": "NVDA", "sector": "Technology", "avg_dollar_volume_60d": 80_000_000.0, "last_close": 800.0},
        {"ticker": "XOM", "sector": "Energy", "avg_dollar_volume_60d": 70_000_000.0, "last_close": 100.0},
        {"ticker": "CVX", "sector": "Energy", "avg_dollar_volume_60d": 60_000_000.0, "last_close": 150.0},
        {"ticker": "BAD", "sector": "Energy", "avg_dollar_volume_60d": 1_000_000.0, "last_close": 2.0},
    ]

    selected = select_sector_balanced_universe(
        rows,
        target_size=4,
        per_sector_cap=2,
        min_avg_dollar_volume=20_000_000.0,
        min_last_close=5.0,
    )

    assert [row["ticker"] for row in selected] == ["AAPL", "MSFT", "XOM", "CVX"]


def test_write_and_load_research_universe_round_trip(tmp_path: Path):
    entries = [
        {"ticker": "AAPL", "sector": "Technology", "avg_dollar_volume_60d": 100_000_000.0, "last_close": 200.0},
        {"ticker": "XOM", "sector": "Energy", "avg_dollar_volume_60d": 50_000_000.0, "last_close": 100.0},
    ]

    path = write_research_universe(
        entries,
        universe_root=str(tmp_path),
        name="liquid_core_v1",
        metadata={"source": "test"},
    )

    payload = load_research_universe("liquid_core_v1", universe_root=str(tmp_path))

    assert path == tmp_path / "liquid_core_v1.json"
    assert payload["count"] == 2
    assert payload["metadata"]["source"] == "test"
    assert payload["entries"][0]["ticker"] == "AAPL"
