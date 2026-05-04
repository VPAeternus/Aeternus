from __future__ import annotations

from pathlib import Path

from tradingagents.research.fundamental_autoresearch.universe_builders import (
    load_research_universe,
)

_LARGE_CAP_V1 = [
    "AAPL",
    "MSFT",
    "AMZN",
    "GOOGL",
    "META",
    "NVDA",
    "AVGO",
    "BRK.B",
    "JPM",
    "V",
    "MA",
    "WMT",
    "COST",
    "XOM",
    "LLY",
    "UNH",
    "JNJ",
    "PG",
    "HD",
    "CRM",
    "ORCL",
    "NFLX",
    "ABBV",
    "KO",
    "PEP",
]


_DEFAULT_UNIVERSE_ROOT = Path("eval_results/fundamental_autoresearch/universes")


def get_v1_universe(name: str = "large_cap_v1") -> list[str]:
    if name == "large_cap_v1":
        return list(_LARGE_CAP_V1)
    if name == "liquid_core_v1":
        payload = load_research_universe(name, universe_root=str(_DEFAULT_UNIVERSE_ROOT))
        return [str(entry["ticker"]).upper() for entry in payload.get("entries", [])]
    raise ValueError(f"Unknown fundamental autoresearch universe: {name}")


def get_universe_sector_map(name: str) -> dict[str, str]:
    if name == "large_cap_v1":
        from tradingagents.research.fundamental_autoresearch.sector_map import get_large_cap_v1_sector_map

        return get_large_cap_v1_sector_map()
    if name == "liquid_core_v1":
        payload = load_research_universe(name, universe_root=str(_DEFAULT_UNIVERSE_ROOT))
        return {
            str(entry["ticker"]).upper(): str(entry.get("sector", "Unknown") or "Unknown")
            for entry in payload.get("entries", [])
        }
    raise ValueError(f"Unknown fundamental autoresearch universe: {name}")
