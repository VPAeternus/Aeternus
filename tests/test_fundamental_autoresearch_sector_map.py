from tradingagents.research.fundamental_autoresearch.sector_map import get_large_cap_v1_sector_map


def test_get_large_cap_v1_sector_map_contains_expected_symbols():
    sector_map = get_large_cap_v1_sector_map()

    assert sector_map["AAPL"] == "Technology"
    assert sector_map["BRK.B"] == "Financials"
    assert sector_map["NFLX"] == "Communication Services"
    assert sector_map["XOM"] == "Energy"
    assert len(sector_map) == 25
