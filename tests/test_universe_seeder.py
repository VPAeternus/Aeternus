"""Tests for tradingagents/dealflow/sources/universe_seeder.py

All external fetches are mocked — no real network calls.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from tradingagents.dealflow.sources.universe_seeder import (
    _sanitize,
    _is_valid_ticker,
    fetch_sp500,
    fetch_nasdaq_listed,
    fetch_ark_holdings,
    load_growth_watchlist,
    build_full_seed_universe,
    seed_akg,
    get_static_etfs,
)


# ---------------------------------------------------------------------------
# 1. S&P 500 parsing
# ---------------------------------------------------------------------------

def test_fetch_sp500_parses_wikipedia_table():
    """Mock pd.read_html, verify tickers extracted and dot-replaced."""
    import pandas as pd

    fake_df = pd.DataFrame({"Symbol": ["AAPL", "BRK.B", "GOOGL", "^SKIP", "A/B"]})
    fake_table = [fake_df]

    with patch("tradingagents.dealflow.sources.universe_seeder.time.sleep"), \
         patch("pandas.read_html", return_value=fake_table):
        result = fetch_sp500()

    tickers = [t for t, _ in result]
    sources = [s for _, s in result]

    assert "AAPL" in tickers
    assert "BRK-B" in tickers  # dot replaced
    assert "GOOGL" in tickers
    # ^SKIP and A/B filtered out
    assert "^SKIP" not in tickers
    assert "A/B" not in tickers
    assert all(s == "sp500" for s in sources)


# ---------------------------------------------------------------------------
# 2. NASDAQ API parsing
# ---------------------------------------------------------------------------

def test_fetch_nasdaq_parses_api_response():
    """Mock requests.get with fake NASDAQ GitHub text file response."""
    fake_text = "NVDA\nMSFT\n TSLA \n\n^VIX\n"
    mock_resp = MagicMock()
    mock_resp.text = fake_text
    mock_resp.raise_for_status = MagicMock()

    with patch("requests.get", return_value=mock_resp), \
         patch("tradingagents.dealflow.sources.universe_seeder.time.sleep"):
        result = fetch_nasdaq_listed()

    tickers = [t for t, _ in result]
    assert "NVDA" in tickers
    assert "MSFT" in tickers
    assert "TSLA" in tickers  # stripped
    assert "" not in tickers
    assert "^VIX" not in tickers
    assert all(s == "nasdaq" for _, s in result)


# ---------------------------------------------------------------------------
# 3. ARK holdings CSV parsing
# ---------------------------------------------------------------------------

def test_fetch_ark_parses_csv():
    """Mock ARKK CSV response with ticker column."""
    fake_csv = textwrap.dedent("""\
        date,fund,company,ticker,cusip,shares,market_value,weight
        2026-03-01,ARKK,Tesla Inc,TSLA,88160R101,1000000,250000000,10.0
        2026-03-01,ARKK,Roku Inc,ROKU,77543R102,500000,50000000,5.0
        2026-03-01,ARKK,,, , ,  ,
    """)
    mock_resp = MagicMock()
    mock_resp.text = fake_csv
    mock_resp.raise_for_status = MagicMock()

    with patch("requests.get", return_value=mock_resp), \
         patch("tradingagents.dealflow.sources.universe_seeder.time.sleep"):
        result = fetch_ark_holdings()

    tickers = [t for t, _ in result]
    assert "TSLA" in tickers
    assert "ROKU" in tickers
    assert "" not in tickers
    assert all(s == "ark" for _, s in result)


# ---------------------------------------------------------------------------
# 4. Growth watchlist loads from JSON
# ---------------------------------------------------------------------------

def test_growth_watchlist_loads_json(tmp_path):
    """Write a temp JSON file and verify tickers are loaded correctly."""
    watchlist = {
        "description": "test",
        "tickers": ["IREN", "RKLB", "ionq", "BRK.B"]  # mixed case + dot
    }
    wl_path = tmp_path / "growth_watchlist.json"
    wl_path.write_text(json.dumps(watchlist), encoding="utf-8")

    result = load_growth_watchlist(path=wl_path)
    tickers = [t for t, _ in result]

    assert "IREN" in tickers
    assert "RKLB" in tickers
    assert "IONQ" in tickers   # uppercased
    assert "BRK-B" in tickers  # dot replaced
    assert all(s == "growth_watchlist" for _, s in result)


# ---------------------------------------------------------------------------
# 5. Missing growth watchlist returns empty list without crash
# ---------------------------------------------------------------------------

def test_growth_watchlist_missing_file_returns_empty(tmp_path):
    """Non-existent watchlist path returns [] without exception."""
    missing = tmp_path / "does_not_exist.json"
    result = load_growth_watchlist(path=missing)
    assert result == []


# ---------------------------------------------------------------------------
# 6. build_full_seed_universe deduplicates overlapping tickers
# ---------------------------------------------------------------------------

def test_build_full_seed_universe_dedupes():
    """Overlapping tickers from multiple sources get merged sources list."""
    # AAPL appears in sp500 and nasdaq; TSLA in nasdaq and ark
    with patch("tradingagents.dealflow.sources.universe_seeder.fetch_sp500",
               return_value=[("AAPL", "sp500"), ("MSFT", "sp500")]), \
         patch("tradingagents.dealflow.sources.universe_seeder.fetch_nasdaq_listed",
               return_value=[("AAPL", "nasdaq"), ("TSLA", "nasdaq")]), \
         patch("tradingagents.dealflow.sources.universe_seeder.fetch_russell2000",
               return_value=[]), \
         patch("tradingagents.dealflow.sources.universe_seeder.fetch_ark_holdings",
               return_value=[("TSLA", "ark")]), \
         patch("tradingagents.dealflow.sources.universe_seeder.load_growth_watchlist",
               return_value=[]), \
         patch("tradingagents.dealflow.sources.universe_seeder.get_static_etfs",
               return_value=[]), \
         patch("tradingagents.dealflow.sources.universe_seeder.DOW_30", []), \
         patch("tradingagents.dealflow.sources.universe_seeder.time.sleep"):
        universe = build_full_seed_universe()

    assert "AAPL" in universe
    assert set(universe["AAPL"]) >= {"sp500", "nasdaq"}

    assert "TSLA" in universe
    assert set(universe["TSLA"]) >= {"nasdaq", "ark"}

    assert "MSFT" in universe
    assert universe["MSFT"] == ["sp500"]


# ---------------------------------------------------------------------------
# 7. seed_akg adds new nodes
# ---------------------------------------------------------------------------

def test_seed_akg_adds_new_nodes():
    """New tickers should call akg.add_node."""
    mock_akg = MagicMock()
    mock_akg._nodes = {}  # empty — all tickers are new

    with patch("tradingagents.dealflow.sources.universe_seeder.build_full_seed_universe",
               return_value={"NVDA": ["sp500"], "AMD": ["nasdaq"]}), \
         patch("tradingagents.dealflow.sources.universe_seeder.AeternusKnowledgeGraph") as MockAKG:
        MockAKG.load.return_value = mock_akg
        result = seed_akg(dry_run=False)

    assert result["new_nodes_added"] == 2
    assert result["existing_updated"] == 0
    assert mock_akg.add_node.call_count == 2
    mock_akg.save.assert_called_once()


# ---------------------------------------------------------------------------
# 8. seed_akg updates existing node metadata without overwriting
# ---------------------------------------------------------------------------

def test_seed_akg_updates_existing_metadata():
    """Existing nodes get seed_sources appended, not overwritten."""
    mock_akg = MagicMock()
    mock_akg._nodes = {
        "AAPL": {"metadata": {"seed_sources": ["sp500"], "some_other_key": "preserved"}}
    }

    with patch("tradingagents.dealflow.sources.universe_seeder.build_full_seed_universe",
               return_value={"AAPL": ["sp500", "nasdaq"]}), \
         patch("tradingagents.dealflow.sources.universe_seeder.AeternusKnowledgeGraph") as MockAKG:
        MockAKG.load.return_value = mock_akg
        result = seed_akg(dry_run=False)

    assert result["new_nodes_added"] == 0
    assert result["existing_updated"] == 1
    # nasdaq was added; sp500 was not duplicated
    updated_sources = mock_akg._nodes["AAPL"]["metadata"]["seed_sources"]
    assert "nasdaq" in updated_sources
    assert updated_sources.count("sp500") == 1  # no duplication
    # other metadata preserved
    assert mock_akg._nodes["AAPL"]["metadata"]["some_other_key"] == "preserved"


# ---------------------------------------------------------------------------
# 9. seed_akg dry_run does not save
# ---------------------------------------------------------------------------

def test_seed_akg_dry_run_no_save():
    """In dry_run mode, akg.save() must NOT be called."""
    mock_akg = MagicMock()
    mock_akg._nodes = {}

    with patch("tradingagents.dealflow.sources.universe_seeder.build_full_seed_universe",
               return_value={"TSLA": ["nasdaq"]}), \
         patch("tradingagents.dealflow.sources.universe_seeder.AeternusKnowledgeGraph") as MockAKG:
        MockAKG.load.return_value = mock_akg
        result = seed_akg(dry_run=True)

    mock_akg.save.assert_not_called()
    assert result["new_nodes_added"] == 1


# ---------------------------------------------------------------------------
# 10. Ticker sanitization
# ---------------------------------------------------------------------------

def test_ticker_sanitization():
    """_sanitize and _is_valid_ticker enforce correct normalization."""
    # Dot replacement
    assert _sanitize("BRK.B") == "BRK-B"
    # Lowercase → upper
    assert _sanitize("aapl") == "AAPL"
    # Whitespace stripped
    assert _sanitize("  MSFT  ") == "MSFT"
    # Combined
    assert _sanitize(" brk.b ") == "BRK-B"

    # Valid tickers
    assert _is_valid_ticker("AAPL") is True
    assert _is_valid_ticker("BRK-B") is True
    assert _is_valid_ticker("GOOGL") is True

    # Invalid tickers
    assert _is_valid_ticker("^VIX") is False   # caret prefix
    assert _is_valid_ticker("A/B") is False    # slash
    assert _is_valid_ticker("") is False       # empty
    assert _is_valid_ticker("123456") is False  # >5 chars, no letters
