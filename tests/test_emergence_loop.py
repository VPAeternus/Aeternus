"""End-to-end loop integration test — proves the emergence chain is connected.

Walks a single ticker through every stage with mocked data, no API calls:

  seed node → scout enrichment → emergence_score computed → tier progresses
    → pipeline reads HABITABLE via get_emerging_planets() → scoring sees emergence signal
    → analysis produces score → record_rating() writes back → tier = SCORED
"""

from tradingagents.graph.knowledge_graph import AeternusKnowledgeGraph


def test_full_emergence_loop():
    """A ticker goes from DARK seed to SCORED in one continuous chain."""
    akg = AeternusKnowledgeGraph()

    # --- Stage 1: Seed ---
    akg.add_node("TESTCO", node_type="company", metadata={"seed_sources": ["sp500"]})
    node = akg._nodes["TESTCO"]
    assert node.get("emergence_tier") is None or node["emergence_tier"] == "DARK"

    # --- Stage 2: Scout enrichment (simulates x_feed_scout writing) ---
    akg.enrich_node_cashtag(
        ticker="TESTCO",
        velocity_z=3.0,
        mentions_7d=800,
        velocity_trend="rising",
        sentiment=0.7,
        as_of_date="2026-03-03T12:00:00Z",
    )
    node = akg._nodes["TESTCO"]

    # Emergence score should be computed
    assert node.get("emergence_score") is not None
    assert node["emergence_score"] > 0

    # Tier should have progressed past DARK
    # velocity_z=3.0 >= 2.0 AND sentiment=0.7 >= 0.5 → HABITABLE
    assert node["emergence_tier"] == "HABITABLE"

    # --- Stage 3: Pipeline reads via get_emerging_planets() ---
    emerging = akg.get_emerging_planets(min_tier="ATMOSPHERE", top_k=10)
    tickers = [p["id"] for p in emerging]
    assert "TESTCO" in tickers, f"TESTCO should be in emerging planets, got: {tickers}"

    # Verify the emergence signal data is present
    testco_planet = [p for p in emerging if p["id"] == "TESTCO"][0]
    assert testco_planet["emergence_score"] > 0.3
    assert testco_planet["emergence_tier"] == "HABITABLE"

    # --- Stage 4: Simulate what pipeline.py does — create emergence signal ---
    emergence_signal = {
        "symbol": testco_planet["id"],
        "signal_family": "emergence",
        "raw_score": round(testco_planet["emergence_score"] * 100, 2),
        "z_score": 0.0,
        "direction": "BULLISH",
        "evidence_count": 2,
        "freshness_hours": 0.0,
        "source_status": "OK",
        "source_name": "akg_emergence",
    }
    assert emergence_signal["raw_score"] > 30.0
    assert emergence_signal["symbol"] == "TESTCO"

    # --- Stage 5: Verify scoring recognizes emergence as a signal family ---
    from tradingagents.dealflow.scoring import (
        CORE_SIGNAL_FAMILIES,
        GATING_FAMILIES,
        CORE_SCORE_WEIGHTS,
    )
    assert "emergence" in CORE_SIGNAL_FAMILIES
    assert "emergence" in GATING_FAMILIES
    assert CORE_SCORE_WEIGHTS.get("emergence", 0) > 0

    # --- Stage 6: Analysis writes back via record_rating() ---
    akg.record_rating("TESTCO", {
        "aeternus_score": 78.5,
        "rating": "Buy",
        "date": "2026-03-03",
        "confidence": 4,
        "catalyst": "Scout-discovered trending ticker with strong momentum",
    })
    node = akg._nodes["TESTCO"]

    # Tier must be SCORED now
    assert node["emergence_tier"] == "SCORED"
    assert node["last_aeternus_score"] == 78.5
    assert node["last_aeternus_rating"] == "Buy"

    # Score history should have the entry
    assert len(node.get("score_history", [])) == 1
    assert node["score_history"][0]["score"] == 78.5


def test_dark_node_not_in_emerging_planets():
    """A DARK node without enrichment should NOT appear in get_emerging_planets()."""
    akg = AeternusKnowledgeGraph()
    akg.add_node("DARKCO", node_type="company")
    akg.compute_emergence_score("DARKCO")

    emerging = akg.get_emerging_planets(min_tier="ATMOSPHERE", top_k=50)
    tickers = [p["id"] for p in emerging]
    assert "DARKCO" not in tickers


def test_scored_node_excluded_from_emerging():
    """A SCORED node should NOT appear in get_emerging_planets()."""
    akg = AeternusKnowledgeGraph()
    akg.add_node("DONECO", node_type="company")
    akg.enrich_node_cashtag(
        ticker="DONECO", velocity_z=3.0, mentions_7d=500,
        velocity_trend="rising", sentiment=0.6, as_of_date="2026-03-03",
    )
    # Score it — should move to SCORED
    akg.record_rating("DONECO", {"aeternus_score": 85.0, "rating": "Strong Buy"})
    assert akg._nodes["DONECO"]["emergence_tier"] == "SCORED"

    emerging = akg.get_emerging_planets(min_tier="ATMOSPHERE", top_k=50)
    tickers = [p["id"] for p in emerging]
    assert "DONECO" not in tickers


def test_breakout_scanner_includes_habitable():
    """Breakout scanner universe includes HABITABLE nodes even with low centrality."""
    from unittest.mock import patch, MagicMock

    akg = AeternusKnowledgeGraph()
    # Low centrality node — would be excluded by old centrality-only gate
    akg.add_node("LOWCENT", node_type="company")
    akg._nodes["LOWCENT"]["centrality"] = 0.01  # Below 0.05 threshold
    akg.enrich_node_cashtag(
        ticker="LOWCENT", velocity_z=3.0, mentions_7d=600,
        velocity_trend="rising", sentiment=0.8, as_of_date="2026-03-03",
    )
    assert akg._nodes["LOWCENT"]["emergence_tier"] == "HABITABLE"

    # High centrality node — always included
    akg.add_node("HIGHCENT", node_type="company")
    akg._nodes["HIGHCENT"]["centrality"] = 0.5

    with patch(
        "tradingagents.graph.knowledge_graph.AeternusKnowledgeGraph.load",
        return_value=akg,
    ):
        from tradingagents.dealflow.sources.breakout_scanner import _get_scan_universe
        universe = _get_scan_universe()

    assert "LOWCENT" in universe, "HABITABLE node should be in scan universe despite low centrality"
    assert "HIGHCENT" in universe, "High centrality node should still be included"
