"""Tests for pipeline gap fixes: commodity ticker enrichment, insider sell AKG writes, T5_RESCAN."""

from __future__ import annotations

import datetime as dt
from unittest.mock import MagicMock, patch

import pytest

from tradingagents.graph.knowledge_graph import AeternusKnowledgeGraph


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fresh_akg() -> AeternusKnowledgeGraph:
    """Return a clean in-memory AKG (no disk I/O)."""
    return AeternusKnowledgeGraph()


# ---------------------------------------------------------------------------
# Gap 1: Commodity scout enriches triggered tickers
# ---------------------------------------------------------------------------

def test_commodity_scout_enriches_tickers():
    """After scan with AKG, triggered tickers must have cashtag_velocity_z on their node."""
    from tradingagents.dealflow.sources.commodity_shock_scout import ClusterAlert

    akg = _fresh_akg()

    alert = ClusterAlert(
        cluster_name="OIL_DISRUPTION",
        confidence=0.85,
        direction="up",
        triggered_instruments=["DHT", "NAT"],
        volume_z_max=2.5,
    )
    # Simulate the anomalies dict that scan_commodity_shock_clusters builds
    anomalies = {
        "DHT": {"volume_z": 2.5, "price_momentum": 0.03},
        "NAT": {"volume_z": 1.8, "price_momentum": 0.01},
    }

    # Exercise the same enrichment path used in scan_commodity_shock_clusters
    today_str = dt.date.today().isoformat()
    for inst_ticker in alert.triggered_instruments:
        inst_ticker = inst_ticker.upper().strip()
        if not inst_ticker:
            continue
        vol_z = float(anomalies.get(inst_ticker, {}).get("volume_z", 0) or 0)
        akg.enrich_node_cashtag(
            ticker=inst_ticker,
            velocity_z=vol_z,
            mentions_7d=0,
            velocity_trend=alert.direction or "neutral",
            sentiment=0.0,
            as_of_date=today_str,
        )

    # Verify nodes were created with the right fields
    assert "DHT" in akg._nodes
    assert akg._nodes["DHT"]["cashtag_velocity_z"] == 2.5
    assert akg._nodes["DHT"]["cashtag_last_updated"] == today_str

    assert "NAT" in akg._nodes
    assert akg._nodes["NAT"]["cashtag_velocity_z"] == 1.8


# ---------------------------------------------------------------------------
# Gap 2: Insider sell clusters write to AKG
# ---------------------------------------------------------------------------

def test_insider_sell_enriches_akg():
    """enrich_node_insider_sell writes score + seller_count fields."""
    akg = _fresh_akg()
    today_str = dt.date.today().isoformat()

    akg.enrich_node_insider_sell(
        ticker="IRWD", score=72.0, seller_count=4, as_of_date=today_str,
    )

    node = akg._nodes["IRWD"]
    assert node["signal_insider_sell_score"] == 72.0
    assert node["signal_insider_sell_count"] == 4
    assert node["signal_insider_sell_updated"] == today_str


def test_insider_sell_triggers_emergence():
    """A node enriched with insider sell signal must be at least ROCKY (n_sources >= 1)."""
    akg = _fresh_akg()
    today_str = dt.date.today().isoformat()

    akg.enrich_node_insider_sell(
        ticker="VERA", score=65.0, seller_count=3, as_of_date=today_str,
    )

    node = akg._nodes["VERA"]
    assert node.get("emergence_tier") in ("ROCKY", "ATMOSPHERE", "HABITABLE")
    assert node.get("emergence_n_sources", 0) >= 1


# ---------------------------------------------------------------------------
# Gap 3: T5_RESCAN — get_rescan_candidates + universe integration
# ---------------------------------------------------------------------------

def test_rescan_candidates_finds_scored_with_recent():
    """SCORED node with fresh signal_*_updated must appear in rescan candidates."""
    akg = _fresh_akg()
    akg.add_node("AAPL", node_type="company")
    node = akg._nodes["AAPL"]
    node["aeternus_score"] = 80.0
    node["emergence_tier"] = "SCORED"
    node["signal_insider_sell_updated"] = dt.date.today().isoformat()
    node["signal_insider_sell_score"] = 55.0

    candidates = akg.get_rescan_candidates(max_age_days=7)
    tickers = [c["id"] for c in candidates]
    assert "AAPL" in tickers


def test_rescan_candidates_ignores_stale():
    """SCORED node with old signal_*_updated must NOT appear in rescan candidates."""
    akg = _fresh_akg()
    akg.add_node("MSFT", node_type="company")
    node = akg._nodes["MSFT"]
    node["aeternus_score"] = 75.0
    node["emergence_tier"] = "SCORED"
    node["signal_insider_sell_updated"] = "2025-01-01"  # very old
    node["signal_insider_sell_score"] = 40.0

    candidates = akg.get_rescan_candidates(max_age_days=7)
    tickers = [c["id"] for c in candidates]
    assert "MSFT" not in tickers


def test_t5_rescan_in_universe():
    """T5_RESCAN tickers appear in build_filtered_universe() output."""
    from tradingagents.dealflow.akg_universe import build_filtered_universe

    akg = MagicMock()

    today_str = dt.date.today().isoformat()
    nodes = {
        "NVDA": {
            "id": "NVDA", "node_type": "company", "asset_class": "Equity",
            "sector_gics": "Technology", "sector": "semis_ai_infrastructure",
            "liquidity_score": 99.0, "aliases": [], "centrality": 1.0,
            "aeternus_score": 85, "emergence_tier": "SCORED", "emergence_score": 0.8,
        },
        "RESCAN_TICKER": {
            "id": "RESCAN_TICKER", "node_type": "company", "asset_class": "Equity",
            "sector_gics": "Energy", "sector": "oil_gas",
            "liquidity_score": 50.0, "aliases": [], "centrality": 0.01,
            "aeternus_score": 60, "emergence_tier": "SCORED", "emergence_score": 0.4,
            "signal_insider_sell_updated": today_str,
            "signal_insider_sell_score": 70.0,
        },
    }
    akg._nodes = nodes

    akg.get_supply_chain_neighbors = lambda ticker, direction="both": []
    akg.get_centrality_scores = lambda: {k: v.get("centrality", 0) for k, v in nodes.items()}
    akg.get_emerging_planets = lambda min_score=0.3, min_tier="ATMOSPHERE", max_aeternus_score=None, top_k=50: []
    akg.get_dark_nodes = lambda min_centrality=0.3: []
    akg.get_rescan_candidates = lambda max_age_days=7: [nodes["RESCAN_TICKER"]]
    akg.get_open_positions = lambda: []

    with patch("tradingagents.dealflow.akg_universe._build_anchor_set", return_value=["NVDA"]):
        rows, tier_map = build_filtered_universe(akg)

    assert "RESCAN_TICKER" in tier_map
    assert tier_map["RESCAN_TICKER"] == "T5_RESCAN"
    symbols = [r["symbol"] for r in rows]
    assert "RESCAN_TICKER" in symbols


def test_t6_portfolio_in_universe():
    """Open positions must always appear in the universe as T6_PORTFOLIO."""
    from tradingagents.dealflow.akg_universe import build_filtered_universe

    akg = MagicMock()

    nodes = {
        "NVDA": {
            "id": "NVDA", "node_type": "company", "asset_class": "Equity",
            "sector_gics": "Technology", "sector": "semis_ai_infrastructure",
            "liquidity_score": 99.0, "aliases": [], "centrality": 1.0,
            "aeternus_score": 85, "emergence_tier": "SCORED", "emergence_score": 0.8,
        },
        "SMALLCAP": {
            "id": "SMALLCAP", "node_type": "company", "asset_class": "Equity",
            "sector_gics": "Healthcare", "sector": "biotech",
            "liquidity_score": 20.0, "aliases": [], "centrality": 0.001,
            "aeternus_score": 70, "emergence_tier": "SCORED", "emergence_score": 0.3,
            "current_position": {"shares": 100, "entry_price": 15.0, "entry_date": "2026-02-20"},
        },
    }
    akg._nodes = nodes

    akg.get_supply_chain_neighbors = lambda ticker, direction="both": []
    akg.get_centrality_scores = lambda: {k: v.get("centrality", 0) for k, v in nodes.items()}
    akg.get_emerging_planets = lambda min_score=0.3, min_tier="ATMOSPHERE", max_aeternus_score=None, top_k=50: []
    akg.get_dark_nodes = lambda min_centrality=0.3: []
    akg.get_rescan_candidates = lambda max_age_days=7: []
    akg.get_open_positions = lambda: [nodes["SMALLCAP"]]

    with patch("tradingagents.dealflow.akg_universe._build_anchor_set", return_value=["NVDA"]):
        rows, tier_map = build_filtered_universe(akg)

    assert "SMALLCAP" in tier_map
    assert tier_map["SMALLCAP"] == "T6_PORTFOLIO"
    symbols = [r["symbol"] for r in rows]
    assert "SMALLCAP" in symbols


def test_get_open_positions():
    """get_open_positions returns only nodes with current_position set."""
    akg = _fresh_akg()
    akg.add_node("HELD", node_type="company")
    akg._nodes["HELD"]["current_position"] = {"shares": 50, "entry_price": 100.0, "entry_date": "2026-03-01"}
    akg.add_node("EMPTY", node_type="company")

    positions = akg.get_open_positions()
    tickers = [p["id"] for p in positions]
    assert "HELD" in tickers
    assert "EMPTY" not in tickers
