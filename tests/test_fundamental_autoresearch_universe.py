import json
from pathlib import Path

import pytest

from tradingagents.research.fundamental_autoresearch import universe as universe_module
from tradingagents.research.fundamental_autoresearch.universe import (
    get_universe_sector_map,
    get_v1_universe,
)


def test_get_v1_universe_returns_deterministic_large_cap_proxy():
    first = get_v1_universe()
    second = get_v1_universe()

    assert first == second
    assert len(first) >= 20
    assert "AAPL" in first
    assert "MSFT" in first


def test_get_v1_universe_supports_named_universe():
    symbols = get_v1_universe("large_cap_v1")

    assert symbols[0] == "AAPL"
    assert "BRK.B" in symbols


def test_get_v1_universe_loads_liquid_core_artifact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    universe_root = tmp_path / "universes"
    universe_root.mkdir()
    (universe_root / "liquid_core_v1.json").write_text(
        json.dumps(
            {
                "name": "liquid_core_v1",
                "count": 2,
                "entries": [
                    {"ticker": "AAPL", "sector": "Technology"},
                    {"ticker": "XOM", "sector": "Energy"},
                ],
            }
        )
    )
    monkeypatch.setattr(universe_module, "_DEFAULT_UNIVERSE_ROOT", universe_root)

    symbols = get_v1_universe("liquid_core_v1")

    assert symbols == ["AAPL", "XOM"]


def test_get_universe_sector_map_reads_liquid_core_artifact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    universe_root = tmp_path / "universes"
    universe_root.mkdir()
    (universe_root / "liquid_core_v1.json").write_text(
        json.dumps(
            {
                "name": "liquid_core_v1",
                "count": 2,
                "entries": [
                    {"ticker": "AAPL", "sector": "Technology"},
                    {"ticker": "XOM", "sector": "Energy"},
                ],
            }
        )
    )
    monkeypatch.setattr(universe_module, "_DEFAULT_UNIVERSE_ROOT", universe_root)

    sector_map = get_universe_sector_map("liquid_core_v1")

    assert sector_map == {"AAPL": "Technology", "XOM": "Energy"}


def test_get_v1_universe_rejects_unknown_name():
    with pytest.raises(ValueError, match="Unknown fundamental autoresearch universe"):
        get_v1_universe("does_not_exist")
