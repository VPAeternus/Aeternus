"""Tests for tradingagents/dealflow/sources/x_feed_scout.py

All xAI API calls are mocked — no real network calls.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from tradingagents.dealflow.sources.x_feed_scout import (
    _compute_batch_velocity_z,
    _detect_dormant_sector_outliers,
    _extract_json_payload,
    _is_valid_ticker,
    scan_x_feed,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_xai_response(tickers: list[dict], active_themes: list[dict] | None = None) -> MagicMock:
    """Build a mock xAI response with output_text containing the trending JSON.

    Each ticker dict should use buzz_rank (ordinal) and categorical sentiment.
    """
    import json
    payload = {"trending": tickers}
    if active_themes is not None:
        payload["active_themes"] = active_themes
    resp = MagicMock()
    resp.output_text = json.dumps(payload)
    return resp


def _make_client(response) -> MagicMock:
    """Build a mock OpenAI client whose .responses.create() returns `response`."""
    client = MagicMock()
    if isinstance(response, Exception):
        client.responses.create.side_effect = response
    else:
        client.responses.create.return_value = response
    return client


# ---------------------------------------------------------------------------
# 1. Returns tickers from single call
# ---------------------------------------------------------------------------

def test_scan_returns_tickers():
    """Single x_search call returns multiple tickers correctly."""
    resp = _make_xai_response([
        {"ticker": "NVDA", "buzz_rank": 1, "sentiment": "BULLISH", "context": "AI hype"},
        {"ticker": "AAPL", "buzz_rank": 2, "sentiment": "NEUTRAL", "context": "buyback"},
        {"ticker": "TSLA", "buzz_rank": 3, "sentiment": "BEARISH", "context": "delivery data"},
    ])

    mock_akg = MagicMock()
    mock_akg._nodes = {"NVDA": {}, "AAPL": {}, "TSLA": {}}

    with patch.dict(os.environ, {"XAI_API_KEY": "fake-key"}), \
         patch("tradingagents.dealflow.sources.x_feed_scout.OpenAI") as MockOpenAI, \
         patch("tradingagents.graph.knowledge_graph.AeternusKnowledgeGraph") as MockAKG:
        MockOpenAI.return_value = _make_client(resp)
        MockAKG.load.return_value = mock_akg

        result = scan_x_feed()

    assert result["ran"] is True
    assert result["calls_made"] == 1
    tickers = {t["ticker"] for t in result["tickers"]}
    assert tickers == {"NVDA", "AAPL", "TSLA"}


# ---------------------------------------------------------------------------
# 2. Crypto symbols are filtered out
# ---------------------------------------------------------------------------

def test_scan_skips_crypto():
    """BTC, ETH, SOL in the response → all filtered, not written to AKG."""
    resp = _make_xai_response([
        {"ticker": "BTC",  "buzz_rank": 1, "sentiment": "VERY_BULLISH", "context": "moon"},
        {"ticker": "ETH",  "buzz_rank": 2, "sentiment": "BULLISH", "context": "staking"},
        {"ticker": "SOL",  "buzz_rank": 3, "sentiment": "BULLISH", "context": "defi"},
        {"ticker": "NVDA", "buzz_rank": 4, "sentiment": "BULLISH", "context": "AI"},
    ])

    mock_akg = MagicMock()
    mock_akg._nodes = {"NVDA": {}}

    with patch.dict(os.environ, {"XAI_API_KEY": "fake-key"}), \
         patch("tradingagents.dealflow.sources.x_feed_scout.OpenAI") as MockOpenAI, \
         patch("tradingagents.graph.knowledge_graph.AeternusKnowledgeGraph") as MockAKG:
        MockOpenAI.return_value = _make_client(resp)
        MockAKG.load.return_value = mock_akg

        result = scan_x_feed()

    tickers = [t["ticker"] for t in result["tickers"]]
    assert "BTC" not in tickers
    assert "ETH" not in tickers
    assert "SOL" not in tickers
    assert "NVDA" in tickers


# ---------------------------------------------------------------------------
# 3. Invalid ticker formats are filtered out
# ---------------------------------------------------------------------------

def test_scan_skips_invalid_tickers():
    """TOOLONG (>5 chars), '123' (digits only), '' (empty) → all filtered."""
    resp = _make_xai_response([
        {"ticker": "TOOLONG", "buzz_rank": 1, "sentiment": "NEUTRAL", "context": "too long"},
        {"ticker": "123",     "buzz_rank": 2, "sentiment": "NEUTRAL", "context": "digits only"},
        {"ticker": "",        "buzz_rank": 3, "sentiment": "NEUTRAL", "context": "empty"},
        {"ticker": "AAPL",   "buzz_rank": 4, "sentiment": "BULLISH", "context": "valid"},
    ])

    mock_akg = MagicMock()
    mock_akg._nodes = {"AAPL": {}}

    with patch.dict(os.environ, {"XAI_API_KEY": "fake-key"}), \
         patch("tradingagents.dealflow.sources.x_feed_scout.OpenAI") as MockOpenAI, \
         patch("tradingagents.graph.knowledge_graph.AeternusKnowledgeGraph") as MockAKG:
        MockOpenAI.return_value = _make_client(resp)
        MockAKG.load.return_value = mock_akg

        result = scan_x_feed()

    tickers = [t["ticker"] for t in result["tickers"]]
    assert "TOOLONG" not in tickers
    assert "123" not in tickers
    assert "" not in tickers
    assert "AAPL" in tickers


# ---------------------------------------------------------------------------
# 4. New tickers → add_node; all tickers → update_node_field ×3
# ---------------------------------------------------------------------------

def test_scan_writes_to_akg():
    """New tickers get add_node; all tickers get enrich_node_cashtag + x_trending fields."""
    resp = _make_xai_response([
        {"ticker": "NEWCO", "buzz_rank": 2, "sentiment": "NEUTRAL", "context": "breakout"},
        {"ticker": "AAPL",  "buzz_rank": 1, "sentiment": "BULLISH", "context": "buyback"},
    ])

    mock_akg = MagicMock()
    mock_akg._nodes = {"AAPL": {}}  # AAPL exists, NEWCO is new

    with patch.dict(os.environ, {"XAI_API_KEY": "fake-key"}), \
         patch("tradingagents.dealflow.sources.x_feed_scout.OpenAI") as MockOpenAI, \
         patch("tradingagents.graph.knowledge_graph.AeternusKnowledgeGraph") as MockAKG:
        MockOpenAI.return_value = _make_client(resp)
        MockAKG.load.return_value = mock_akg

        result = scan_x_feed()

    # add_node called once for NEWCO only
    assert mock_akg.add_node.call_count == 1
    assert mock_akg.add_node.call_args[0][0] == "NEWCO"

    # enrich_node_cashtag called once per ticker (writes emergence fields)
    assert mock_akg.enrich_node_cashtag.call_count == 2

    # update_node_field called 3× per ticker = 6 total (x_trending audit fields)
    assert mock_akg.update_node_field.call_count == 6

    # compute_all_emergence_scores no longer called — enrich_node_cashtag handles it per-ticker
    mock_akg.compute_all_emergence_scores.assert_not_called()
    mock_akg.save.assert_called_once()

    assert result["new_nodes_created"] == 1
    assert result["existing_nodes_updated"] == 1


# ---------------------------------------------------------------------------
# 5. Dry-run → AKG never loaded, never saved
# ---------------------------------------------------------------------------

def test_scan_dry_run_no_save():
    """In dry_run mode, AKG.load() and akg.save() must NOT be called."""
    resp = _make_xai_response([
        {"ticker": "TSLA", "buzz_rank": 1, "sentiment": "BEARISH", "context": "delivery"},
    ])

    with patch.dict(os.environ, {"XAI_API_KEY": "fake-key"}), \
         patch("tradingagents.dealflow.sources.x_feed_scout.OpenAI") as MockOpenAI, \
         patch("tradingagents.graph.knowledge_graph.AeternusKnowledgeGraph") as MockAKG:
        MockOpenAI.return_value = _make_client(resp)

        result = scan_x_feed(dry_run=True)

    MockAKG.load.assert_not_called()
    assert result["ran"] is True
    assert result["reason"] == "dry_run"
    assert result["tickers_found"] == 1
    assert result["new_nodes_created"] == 0


# ---------------------------------------------------------------------------
# 6. No XAI_API_KEY → ran=False, reason=no_xai_api_key
# ---------------------------------------------------------------------------

def test_scan_no_api_key():
    """Without XAI_API_KEY, scan_x_feed returns ran=False immediately."""
    env = {k: v for k, v in os.environ.items() if k != "XAI_API_KEY"}
    with patch.dict(os.environ, env, clear=True):
        result = scan_x_feed()

    assert result["ran"] is False
    assert result["reason"] == "no_xai_api_key"
    assert result["calls_made"] == 0


# ---------------------------------------------------------------------------
# 7. API error → recorded in errors, calls_made=1, tickers empty
# ---------------------------------------------------------------------------

def test_scan_api_error_recorded():
    """If the x_search call raises, the error is recorded and result is graceful."""
    mock_akg = MagicMock()
    mock_akg._nodes = {}

    with patch.dict(os.environ, {"XAI_API_KEY": "fake-key"}), \
         patch("tradingagents.dealflow.sources.x_feed_scout.OpenAI") as MockOpenAI:
        MockOpenAI.return_value = _make_client(Exception("network error"))

        result = scan_x_feed()

    assert result["calls_made"] == 1
    assert len(result["errors"]) == 1
    assert "network error" in result["errors"][0]
    assert result["tickers_found"] == 0
    assert result["ran"] is True


# ---------------------------------------------------------------------------
# 8. Existing node → add_node NOT called; update_node_field IS called
# ---------------------------------------------------------------------------

def test_existing_node_not_recreated():
    """A ticker already in AKG must NOT trigger add_node, but must update trending fields."""
    resp = _make_xai_response([
        {"ticker": "AAPL", "buzz_rank": 1, "sentiment": "BULLISH", "context": "WWDC"},
    ])

    mock_akg = MagicMock()
    mock_akg._nodes = {"AAPL": {"node_type": "company"}}

    with patch.dict(os.environ, {"XAI_API_KEY": "fake-key"}), \
         patch("tradingagents.dealflow.sources.x_feed_scout.OpenAI") as MockOpenAI, \
         patch("tradingagents.graph.knowledge_graph.AeternusKnowledgeGraph") as MockAKG:
        MockOpenAI.return_value = _make_client(resp)
        MockAKG.load.return_value = mock_akg

        result = scan_x_feed()

    mock_akg.add_node.assert_not_called()
    mock_akg.enrich_node_cashtag.assert_called_once()
    assert mock_akg.update_node_field.call_count == 3
    assert result["new_nodes_created"] == 0
    assert result["existing_nodes_updated"] == 1
    assert result["tickers"][0]["is_new"] is False


# ---------------------------------------------------------------------------
# 9. _compute_batch_velocity_z — rank-based z ordering
# ---------------------------------------------------------------------------

def test_compute_batch_velocity_z():
    """Lowest buzz_rank (rank 1) = highest z, highest rank = lowest z."""
    tickers = {
        "NVDA": {"mentions_estimate": 1, "ticker": "NVDA"},  # rank 1 = loudest
        "AAPL": {"mentions_estimate": 2, "ticker": "AAPL"},  # rank 2
        "TSLA": {"mentions_estimate": 3, "ticker": "TSLA"},  # rank 3 = quietest
    }
    _compute_batch_velocity_z(tickers)
    assert tickers["NVDA"]["velocity_z"] > tickers["AAPL"]["velocity_z"]
    assert tickers["AAPL"]["velocity_z"] > tickers["TSLA"]["velocity_z"]
    # Rank 3 of 3 → negative z
    assert tickers["TSLA"]["velocity_z"] < 0


# ---------------------------------------------------------------------------
# 10. _compute_batch_velocity_z — uniform rank (all same)
# ---------------------------------------------------------------------------

def test_compute_batch_velocity_z_uniform():
    """All same buzz_rank → no differentiation → all z-scores = 0.0."""
    tickers = {
        "NVDA": {"mentions_estimate": 1, "ticker": "NVDA"},
        "AAPL": {"mentions_estimate": 1, "ticker": "AAPL"},
    }
    _compute_batch_velocity_z(tickers)
    assert tickers["NVDA"]["velocity_z"] == 0.0
    assert tickers["AAPL"]["velocity_z"] == 0.0


# ---------------------------------------------------------------------------
# 11. enrich_node_cashtag called with velocity_z and mapped sentiment
# ---------------------------------------------------------------------------

def test_scan_writes_emergence_fields():
    """Scout maps categorical sentiment to floats and passes to enrich_node_cashtag."""
    resp = _make_xai_response([
        {"ticker": "NVDA", "buzz_rank": 1, "sentiment": "VERY_BULLISH", "context": "AI"},
        {"ticker": "AAPL", "buzz_rank": 2, "sentiment": "BEARISH", "context": "miss"},
    ])

    mock_akg = MagicMock()
    mock_akg._nodes = {"NVDA": {}, "AAPL": {}}

    with patch.dict(os.environ, {"XAI_API_KEY": "fake-key"}), \
         patch("tradingagents.dealflow.sources.x_feed_scout.OpenAI") as MockOpenAI, \
         patch("tradingagents.graph.knowledge_graph.AeternusKnowledgeGraph") as MockAKG:
        MockOpenAI.return_value = _make_client(resp)
        MockAKG.load.return_value = mock_akg

        result = scan_x_feed()

    assert mock_akg.enrich_node_cashtag.call_count == 2

    calls = {c.kwargs["ticker"]: c.kwargs for c in mock_akg.enrich_node_cashtag.call_args_list}
    assert calls["NVDA"]["sentiment"] == 0.9   # VERY_BULLISH → 0.9
    assert calls["AAPL"]["sentiment"] == -0.5  # BEARISH → -0.5
    # NVDA has rank 1 → higher velocity_z than AAPL rank 2
    assert calls["NVDA"]["velocity_z"] > calls["AAPL"]["velocity_z"]


# ---------------------------------------------------------------------------
# 12. Missing sentiment defaults to NEUTRAL → 0.0
# ---------------------------------------------------------------------------

def test_scan_sentiment_defaults_to_zero():
    """Missing sentiment key in response → defaults to 0.0 (NEUTRAL)."""
    resp = _make_xai_response([
        {"ticker": "MSFT", "buzz_rank": 1, "context": "cloud"},  # no sentiment key
    ])

    mock_akg = MagicMock()
    mock_akg._nodes = {"MSFT": {}}

    with patch.dict(os.environ, {"XAI_API_KEY": "fake-key"}), \
         patch("tradingagents.dealflow.sources.x_feed_scout.OpenAI") as MockOpenAI, \
         patch("tradingagents.graph.knowledge_graph.AeternusKnowledgeGraph") as MockAKG:
        MockOpenAI.return_value = _make_client(resp)
        MockAKG.load.return_value = mock_akg

        result = scan_x_feed()

    calls = mock_akg.enrich_node_cashtag.call_args_list
    assert calls[0].kwargs["sentiment"] == 0.0


# ---------------------------------------------------------------------------
# 13. Active themes → activate_theme and activate_sector called
# ---------------------------------------------------------------------------

def test_scan_activates_themes():
    """Themes in active_themes are activated in AKG; result includes themes_activated."""
    resp = _make_xai_response(
        tickers=[{"ticker": "NVDA", "buzz_rank": 1, "sentiment": "BULLISH", "context": "AI"}],
        active_themes=[{
            "theme": "AI_infra",
            "sectors": ["Technology"],
            "conviction": 0.9,
            "reasoning": "capex",
        }],
    )

    mock_akg = MagicMock()
    mock_akg._nodes = {"NVDA": {}, "AI_infra": {"node_type": "theme"}, "Technology": {"node_type": "sector"}}
    mock_akg.get_nodes_by_type.return_value = []

    with patch.dict(os.environ, {"XAI_API_KEY": "fake-key"}), \
         patch("tradingagents.dealflow.sources.x_feed_scout.OpenAI") as MockOpenAI, \
         patch("tradingagents.graph.knowledge_graph.AeternusKnowledgeGraph") as MockAKG:
        MockOpenAI.return_value = _make_client(resp)
        MockAKG.load.return_value = mock_akg

        result = scan_x_feed()

    # activate_theme called with correct theme_id
    mock_akg.activate_theme.assert_called_once()
    call_kwargs = mock_akg.activate_theme.call_args
    assert call_kwargs.kwargs.get("theme_id") == "AI_infra" or call_kwargs.args[0] == "AI_infra"

    # activate_sector called with correct sector_id
    mock_akg.activate_sector.assert_called_once()
    sector_call_kwargs = mock_akg.activate_sector.call_args
    assert (sector_call_kwargs.kwargs.get("sector_id") == "Technology" or
            sector_call_kwargs.args[0] == "Technology")

    assert "AI_infra" in result["themes_activated"]


# ---------------------------------------------------------------------------
# 14. Stale themes (not in scan results) → deactivate_theme called
# ---------------------------------------------------------------------------

def test_scan_deactivates_stale_themes():
    """An existing active theme absent from scan results is deactivated."""
    resp = _make_xai_response(
        tickers=[{"ticker": "NVDA", "buzz_rank": 1, "sentiment": "BULLISH", "context": "AI"}],
        active_themes=[{
            "theme": "new_theme",
            "sectors": [],
            "conviction": 0.8,
            "reasoning": "emerging",
        }],
    )

    mock_akg = MagicMock()
    # old_theme exists as an active theme node; new_theme does not yet exist
    mock_akg._nodes = {"NVDA": {}, "new_theme": {"node_type": "theme", "id": "new_theme"}}
    # get_nodes_by_type returns old_theme as an active existing theme
    mock_akg.get_nodes_by_type.return_value = [
        {"id": "old_theme", "node_type": "theme", "active": True},
    ]

    with patch.dict(os.environ, {"XAI_API_KEY": "fake-key"}), \
         patch("tradingagents.dealflow.sources.x_feed_scout.OpenAI") as MockOpenAI, \
         patch("tradingagents.graph.knowledge_graph.AeternusKnowledgeGraph") as MockAKG:
        MockOpenAI.return_value = _make_client(resp)
        MockAKG.load.return_value = mock_akg

        result = scan_x_feed()

    mock_akg.deactivate_theme.assert_called_once()
    deactivate_call = mock_akg.deactivate_theme.call_args
    assert (deactivate_call.kwargs.get("theme_id") == "old_theme" or
            deactivate_call.args[0] == "old_theme")

    assert "old_theme" in result["themes_deactivated"]


# ---------------------------------------------------------------------------
# 15. New theme node created in AKG if not already present
# ---------------------------------------------------------------------------

def test_scan_creates_new_theme_node():
    """A theme not in akg._nodes triggers add_node with node_type='theme'."""
    resp = _make_xai_response(
        tickers=[{"ticker": "NVDA", "buzz_rank": 1, "sentiment": "BULLISH", "context": "AI"}],
        active_themes=[{
            "theme": "brand_new_theme",
            "sectors": [],
            "conviction": 0.7,
            "reasoning": "just discovered",
        }],
    )

    mock_akg = MagicMock()
    # brand_new_theme is NOT in _nodes — should trigger add_node
    mock_akg._nodes = {"NVDA": {}}
    mock_akg.get_nodes_by_type.return_value = []

    with patch.dict(os.environ, {"XAI_API_KEY": "fake-key"}), \
         patch("tradingagents.dealflow.sources.x_feed_scout.OpenAI") as MockOpenAI, \
         patch("tradingagents.graph.knowledge_graph.AeternusKnowledgeGraph") as MockAKG:
        MockOpenAI.return_value = _make_client(resp)
        MockAKG.load.return_value = mock_akg

        result = scan_x_feed()

    # add_node called at least once for brand_new_theme with node_type="theme"
    theme_node_calls = [
        c for c in mock_akg.add_node.call_args_list
        if (c.args and c.args[0] == "brand_new_theme") or
           c.kwargs.get("node_id") == "brand_new_theme"
    ]
    assert len(theme_node_calls) == 1
    call = theme_node_calls[0]
    node_type = call.kwargs.get("node_type") or (call.args[1] if len(call.args) > 1 else None)
    assert node_type == "theme"


# ---------------------------------------------------------------------------
# 16. No active_themes in response → no theme AKG calls
# ---------------------------------------------------------------------------

def test_scan_no_themes_in_response():
    """If active_themes is absent, no theme-related AKG calls are made."""
    resp = _make_xai_response(
        tickers=[{"ticker": "AAPL", "buzz_rank": 1, "sentiment": "BULLISH", "context": "buyback"}],
        # active_themes omitted → no theme key in JSON
    )

    mock_akg = MagicMock()
    mock_akg._nodes = {"AAPL": {}}
    mock_akg.get_nodes_by_type.return_value = []

    with patch.dict(os.environ, {"XAI_API_KEY": "fake-key"}), \
         patch("tradingagents.dealflow.sources.x_feed_scout.OpenAI") as MockOpenAI, \
         patch("tradingagents.graph.knowledge_graph.AeternusKnowledgeGraph") as MockAKG:
        MockOpenAI.return_value = _make_client(resp)
        MockAKG.load.return_value = mock_akg

        result = scan_x_feed()

    mock_akg.activate_theme.assert_not_called()
    mock_akg.activate_sector.assert_not_called()
    mock_akg.deactivate_theme.assert_not_called()
    assert result["themes_activated"] == []
    assert result["themes_deactivated"] == []
    # Existing ticker processing still works
    assert len(result["tickers"]) == 1
    assert result["tickers"][0]["ticker"] == "AAPL"


# ---------------------------------------------------------------------------
# 17. _detect_dormant_sector_outliers — flags high-velocity in inactive sectors
# ---------------------------------------------------------------------------

def test_detect_dormant_sector_outliers():
    """High velocity_z in inactive sector → flagged; active sector → not flagged."""
    mock_akg = MagicMock()
    mock_akg.get_active_sector_ids.return_value = {"Technology"}
    mock_akg.get_nodes_by_type.return_value = [
        {"id": "NVDA", "sector": "Technology", "cashtag_velocity_z": 5.0},   # active sector → skip
        {"id": "XYZ",  "sector": "Healthcare", "cashtag_velocity_z": 4.0},   # dormant + high vz → flag
        {"id": "ABC",  "sector": "Healthcare", "cashtag_velocity_z": 1.0},   # dormant but low vz → skip
        {"id": "NOPE", "sector": None,         "cashtag_velocity_z": 9.0},   # no sector → skip
    ]

    outliers = _detect_dormant_sector_outliers(mock_akg, {"sector_scout_outlier_velocity_z": 3.0})

    assert len(outliers) == 1
    assert outliers[0]["ticker"] == "XYZ"
    assert outliers[0]["sector"] == "Healthcare"
    assert outliers[0]["velocity_z"] == 4.0
    assert outliers[0]["flag_reason"] == "high_velocity_in_dormant_sector"
    mock_akg.update_node_field.assert_called_once_with("XYZ", "sector_outlier_flagged", True)


# ---------------------------------------------------------------------------
# 18. Local sentiment reversal detection — prior AKG sentiment differs
# ---------------------------------------------------------------------------

def test_scan_captures_sentiment_reversals():
    """Sentiment reversal detected locally when prior AKG sentiment differs by >= 0.4."""
    resp = _make_xai_response([
        {"ticker": "TSLA", "buzz_rank": 2, "sentiment": "BEARISH", "context": "earnings miss"},
        {"ticker": "NVDA", "buzz_rank": 1, "sentiment": "BULLISH", "context": "AI"},
    ])

    mock_akg = MagicMock()
    # TSLA has prior bullish sentiment (0.5) → new BEARISH (-0.5) = diff 1.0 >= 0.4
    # NVDA has no prior sentiment → no reversal
    mock_akg._nodes = {"TSLA": {"cashtag_sentiment": 0.5}, "NVDA": {}}
    mock_akg.get_nodes_by_type.return_value = []

    with patch.dict(os.environ, {"XAI_API_KEY": "fake-key"}), \
         patch("tradingagents.dealflow.sources.x_feed_scout.OpenAI") as MockOpenAI, \
         patch("tradingagents.graph.knowledge_graph.AeternusKnowledgeGraph") as MockAKG:
        MockOpenAI.return_value = _make_client(resp)
        MockAKG.load.return_value = mock_akg

        result = scan_x_feed()

    assert len(result["sentiment_reversals"]) == 1
    assert result["sentiment_reversals"][0]["ticker"] == "TSLA"
    assert result["sentiment_reversals"][0]["from_sentiment"] == 0.5
    assert result["sentiment_reversals"][0]["to_sentiment"] == -0.5

    # Verify AKG reversal fields written
    reversal_calls = [
        c for c in mock_akg.update_node_field.call_args_list
        if c[0][1] == "x_sentiment_reversal_from"
    ]
    assert len(reversal_calls) == 1
    assert reversal_calls[0][0][0] == "TSLA"
    assert reversal_calls[0][0][2] == 0.5


# ---------------------------------------------------------------------------
# 19. No prior sentiment in AKG → no reversal detected
# ---------------------------------------------------------------------------

def test_scan_skips_reversal_for_unknown_ticker():
    """Ticker exists in AKG but has no prior cashtag_sentiment → no reversal."""
    resp = _make_xai_response([
        {"ticker": "AAPL", "buzz_rank": 1, "sentiment": "VERY_BULLISH", "context": "strong"},
    ])

    mock_akg = MagicMock()
    # AAPL exists but has no cashtag_sentiment → no prior → no reversal
    mock_akg._nodes = {"AAPL": {}}
    mock_akg.get_nodes_by_type.return_value = []

    with patch.dict(os.environ, {"XAI_API_KEY": "fake-key"}), \
         patch("tradingagents.dealflow.sources.x_feed_scout.OpenAI") as MockOpenAI, \
         patch("tradingagents.graph.knowledge_graph.AeternusKnowledgeGraph") as MockAKG:
        MockOpenAI.return_value = _make_client(resp)
        MockAKG.load.return_value = mock_akg

        result = scan_x_feed()

    assert result["sentiment_reversals"] == []
    reversal_field_calls = [
        c for c in mock_akg.update_node_field.call_args_list
        if "reversal" in str(c[0][1])
    ]
    assert len(reversal_field_calls) == 0


# ---------------------------------------------------------------------------
# 20. No prior sentiment in AKG → no reversals (first run scenario)
# ---------------------------------------------------------------------------

def test_scan_no_reversals_in_response():
    """No prior sentiment in AKG → no reversals detected (first run)."""
    resp = _make_xai_response([
        {"ticker": "AAPL", "buzz_rank": 1, "sentiment": "BULLISH", "context": "steady"},
    ])

    mock_akg = MagicMock()
    # AAPL exists but no cashtag_sentiment → first run, no reversals
    mock_akg._nodes = {"AAPL": {}}
    mock_akg.get_nodes_by_type.return_value = []

    with patch.dict(os.environ, {"XAI_API_KEY": "fake-key"}), \
         patch("tradingagents.dealflow.sources.x_feed_scout.OpenAI") as MockOpenAI, \
         patch("tradingagents.graph.knowledge_graph.AeternusKnowledgeGraph") as MockAKG:
        MockOpenAI.return_value = _make_client(resp)
        MockAKG.load.return_value = mock_akg

        result = scan_x_feed()

    assert result["sentiment_reversals"] == []
