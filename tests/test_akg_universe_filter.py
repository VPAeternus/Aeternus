"""Tests for the centrality-gated universe filter (akg_universe.py)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers: build a minimal mock AKG with 5 nodes and supply-chain edges
# ---------------------------------------------------------------------------

def _make_mock_akg():
    """5-node AKG: NVDA(anchor), TSM(1-hop), AXTI(2-hop/emerging), CRDO(dark), ZZZZ(nothing)."""
    akg = MagicMock()

    nodes = {
        "NVDA": {
            "id": "NVDA", "node_type": "company", "asset_class": "Equity",
            "sector_gics": "Technology", "sector": "semis_ai_infrastructure",
            "liquidity_score": 99.0, "aliases": [], "centrality": 1.0,
            "aeternus_score": 85, "emergence_tier": "SCORED", "emergence_score": 0.0,
        },
        "TSM": {
            "id": "TSM", "node_type": "company", "asset_class": "Equity",
            "sector_gics": "Technology", "sector": "semis_ai_infrastructure",
            "liquidity_score": 80.0, "aliases": [], "centrality": 0.7,
            "aeternus_score": 72, "emergence_tier": "SCORED", "emergence_score": 0.0,
        },
        "AXTI": {
            "id": "AXTI", "node_type": "company", "asset_class": "Equity",
            "sector_gics": "Technology", "sector": "semis_ai_infrastructure",
            "liquidity_score": 30.0, "aliases": [], "centrality": 0.06,
            "aeternus_score": None, "emergence_tier": "ATMOSPHERE", "emergence_score": 0.6,
        },
        "CRDO": {
            "id": "CRDO", "node_type": "company", "asset_class": "Equity",
            "sector_gics": "Technology", "sector": "semis_ai_infrastructure",
            "liquidity_score": 40.0, "aliases": [], "centrality": 0.35,
            "aeternus_score": None, "emergence_tier": "DARK", "emergence_score": 0.0,
        },
        "ZZZZ": {
            "id": "ZZZZ", "node_type": "company", "asset_class": "Equity",
            "sector_gics": "Unclassified Equity", "sector": "",
            "liquidity_score": 10.0, "aliases": [], "centrality": 0.001,
            "aeternus_score": None, "emergence_tier": "DARK", "emergence_score": 0.0,
        },
        # Non-company node (should be ignored)
        "SECTOR_TECH": {
            "id": "SECTOR_TECH", "node_type": "sector",
        },
    }
    akg._nodes = nodes

    # Supply chain: NVDA -> TSM (downstream), TSM -> AXTI (downstream)
    def get_neighbors(ticker, direction="both"):
        if ticker == "NVDA":
            return [{"ticker": "TSM", "direction": "downstream", "weight": 1.0, "evidence_count": 3}]
        if ticker == "TSM":
            return [
                {"ticker": "NVDA", "direction": "upstream", "weight": 1.0, "evidence_count": 3},
                {"ticker": "AXTI", "direction": "downstream", "weight": 0.5, "evidence_count": 1},
            ]
        if ticker == "AXTI":
            return [{"ticker": "TSM", "direction": "upstream", "weight": 0.5, "evidence_count": 1}]
        return []

    akg.get_supply_chain_neighbors = get_neighbors

    # Centrality scores — already set on nodes, just return dict
    def get_centrality():
        return {nid: n.get("centrality", 0) for nid, n in nodes.items() if n.get("node_type") == "company"}
    akg.get_centrality_scores = get_centrality

    # Emerging planets — AXTI qualifies
    def get_emerging(min_score=0.3, min_tier="ATMOSPHERE", max_aeternus_score=None, top_k=50):
        return [{"id": "AXTI", "emergence_score": 0.6, "emergence_tier": "ATMOSPHERE",
                 "cashtag_sentiment": 0.0, "n_signal_sources": 1}]
    akg.get_emerging_planets = get_emerging

    # Dark nodes — CRDO qualifies (centrality=0.35, no score)
    def get_dark(min_centrality=0.3):
        return [n for n in nodes.values()
                if n.get("node_type") == "company"
                and float(n.get("centrality", 0)) >= min_centrality
                and n.get("aeternus_score") is None]
    akg.get_dark_nodes = get_dark

    return akg


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestAnchorCache:
    """Tests for _load_anchor_cache / _build_anchor_set."""

    def test_cache_hit_fresh(self, tmp_path, monkeypatch):
        """Fresh cache file should return symbols without calling yfinance."""
        from tradingagents.dealflow import akg_universe

        cache_path = tmp_path / "anchor_set_cache.json"
        cache_path.write_text(json.dumps({
            "cached_at": time.time(),
            "symbols": ["AAPL", "MSFT", "NVDA"],
        }))
        monkeypatch.setattr(akg_universe, "_ANCHOR_CACHE_PATH", cache_path)

        result = akg_universe._load_anchor_cache(ttl_days=7)
        assert result == ["AAPL", "MSFT", "NVDA"]

    def test_cache_stale(self, tmp_path, monkeypatch):
        """Cache older than TTL should return None."""
        from tradingagents.dealflow import akg_universe

        cache_path = tmp_path / "anchor_set_cache.json"
        cache_path.write_text(json.dumps({
            "cached_at": time.time() - 8 * 86400,  # 8 days old
            "symbols": ["AAPL"],
        }))
        monkeypatch.setattr(akg_universe, "_ANCHOR_CACHE_PATH", cache_path)

        result = akg_universe._load_anchor_cache(ttl_days=7)
        assert result is None

    def test_anchor_fallback_on_yfinance_error(self, tmp_path, monkeypatch):
        """yfinance failure should fall back to DOW_30."""
        from tradingagents.dealflow import akg_universe

        cache_path = tmp_path / "anchor_set_cache.json"
        monkeypatch.setattr(akg_universe, "_ANCHOR_CACHE_PATH", cache_path)

        # Make yfinance import fail
        import yfinance as yf
        original_ticker = yf.Ticker
        monkeypatch.setattr(yf, "Ticker", MagicMock(side_effect=Exception("yfinance down")))

        result = akg_universe._build_anchor_set(ttl_days=7)

        # Should at least contain DOW_30 (30 symbols)
        from tradingagents.dealflow.sources.universe_seeder import DOW_30
        for sym in DOW_30:
            assert sym in result


class TestBuildFilteredUniverse:
    """Tests for the 4-tier filtered universe builder."""

    def test_tier_assignment_5_node_akg(self, tmp_path, monkeypatch):
        """NVDA=T1, TSM=T2, AXTI=T3, CRDO=T4, ZZZZ=excluded."""
        from tradingagents.dealflow import akg_universe

        # Point cache to tmp so _build_anchor_set writes there
        cache_path = tmp_path / "anchor_set_cache.json"
        monkeypatch.setattr(akg_universe, "_ANCHOR_CACHE_PATH", cache_path)

        akg = _make_mock_akg()

        # Patch _build_anchor_set to return just NVDA (simulates it being in SPY/DOW)
        monkeypatch.setattr(akg_universe, "_build_anchor_set", lambda ttl_days=7: ["NVDA"])

        rows, tier_map = akg_universe.build_filtered_universe(akg=akg, config={})

        assert tier_map.get("NVDA") == "T1_ANCHOR"
        assert tier_map.get("TSM") == "T2_NEIGHBOR"
        assert tier_map.get("AXTI") == "T3_SCOUT"
        assert tier_map.get("CRDO") == "T4_DARK"
        assert "ZZZZ" not in tier_map

        symbols = {r["symbol"] for r in rows}
        assert "NVDA" in symbols
        assert "TSM" in symbols
        assert "AXTI" in symbols
        assert "CRDO" in symbols
        assert "ZZZZ" not in symbols

    def test_filter_disabled_returns_all(self, monkeypatch):
        """filter_enabled=False should return all company nodes."""
        from tradingagents.dealflow import akg_universe

        akg = _make_mock_akg()
        monkeypatch.setattr(
            "tradingagents.graph.knowledge_graph.AeternusKnowledgeGraph.load",
            lambda: akg,
        )

        rows = akg_universe.build_universe_from_akg(
            config={"dealflow_universe_filter_enabled": False},
        )

        symbols = {r["symbol"] for r in rows}
        # All 5 company nodes should be present
        assert "NVDA" in symbols
        assert "TSM" in symbols
        assert "AXTI" in symbols
        assert "CRDO" in symbols
        assert "ZZZZ" in symbols

    def test_filter_enabled_reduces_universe(self, tmp_path, monkeypatch):
        """filter_enabled=True should produce fewer rows than total nodes."""
        from tradingagents.dealflow import akg_universe

        cache_path = tmp_path / "anchor_set_cache.json"
        monkeypatch.setattr(akg_universe, "_ANCHOR_CACHE_PATH", cache_path)

        akg = _make_mock_akg()
        monkeypatch.setattr(
            "tradingagents.graph.knowledge_graph.AeternusKnowledgeGraph.load",
            lambda: akg,
        )
        monkeypatch.setattr(akg_universe, "_build_anchor_set", lambda ttl_days=7: ["NVDA"])

        filtered = akg_universe.build_universe_from_akg(
            config={"dealflow_universe_filter_enabled": True},
        )
        unfiltered = akg_universe.build_universe_from_akg(
            config={"dealflow_universe_filter_enabled": False},
        )

        assert len(filtered) < len(unfiltered)

    def test_no_duplicates(self, tmp_path, monkeypatch):
        """Filtered universe should have no duplicate symbols."""
        from tradingagents.dealflow import akg_universe

        cache_path = tmp_path / "anchor_set_cache.json"
        monkeypatch.setattr(akg_universe, "_ANCHOR_CACHE_PATH", cache_path)

        akg = _make_mock_akg()
        monkeypatch.setattr(akg_universe, "_build_anchor_set", lambda ttl_days=7: ["NVDA"])

        rows, _ = akg_universe.build_filtered_universe(akg=akg, config={})
        symbols = [r["symbol"] for r in rows]
        assert len(symbols) == len(set(symbols))

    def test_extra_symbols_manual_tier(self, tmp_path, monkeypatch):
        """Extra symbols should be tagged MANUAL and included."""
        from tradingagents.dealflow import akg_universe

        cache_path = tmp_path / "anchor_set_cache.json"
        monkeypatch.setattr(akg_universe, "_ANCHOR_CACHE_PATH", cache_path)

        akg = _make_mock_akg()
        monkeypatch.setattr(akg_universe, "_build_anchor_set", lambda ttl_days=7: ["NVDA"])

        rows, tier_map = akg_universe.build_filtered_universe(
            akg=akg,
            extra_symbols=["BE", "PLTR"],
            config={},
        )

        # BE and PLTR are not in the mock AKG, so they get MANUAL tier
        assert tier_map.get("BE") == "MANUAL"
        assert tier_map.get("PLTR") == "MANUAL"

        # They should appear in rows as default Equity entries
        symbols = {r["symbol"] for r in rows}
        assert "BE" in symbols
        assert "PLTR" in symbols

    def test_technical_ignition_symbols_get_dedicated_tier(self, tmp_path, monkeypatch):
        """Technical ignition scout symbols should be included without being mislabeled as MANUAL."""
        from tradingagents.dealflow import akg_universe

        cache_path = tmp_path / "anchor_set_cache.json"
        monkeypatch.setattr(akg_universe, "_ANCHOR_CACHE_PATH", cache_path)

        akg = _make_mock_akg()
        monkeypatch.setattr(akg_universe, "_build_anchor_set", lambda ttl_days=7: ["NVDA"])

        rows, tier_map = akg_universe.build_filtered_universe(
            akg=akg,
            technical_ignition_symbols=["BE", "PLTR"],
            config={},
        )

        assert tier_map.get("BE") == "T3D_TECHNICAL_IGNITION"
        assert tier_map.get("PLTR") == "T3D_TECHNICAL_IGNITION"
        assert "MANUAL" not in {tier_map.get("BE"), tier_map.get("PLTR")}

        symbols = {r["symbol"] for r in rows}
        assert "BE" in symbols
        assert "PLTR" in symbols

    def test_earnings_options_symbols_get_dedicated_tier(self, tmp_path, monkeypatch):
        """Manual earnings/options scout symbols should be included without being mislabeled as MANUAL."""
        from tradingagents.dealflow import akg_universe

        cache_path = tmp_path / "anchor_set_cache.json"
        monkeypatch.setattr(akg_universe, "_ANCHOR_CACHE_PATH", cache_path)

        akg = _make_mock_akg()
        monkeypatch.setattr(akg_universe, "_build_anchor_set", lambda ttl_days=7: ["NVDA"])

        rows, tier_map = akg_universe.build_filtered_universe(
            akg=akg,
            earnings_options_symbols=["MU", "BE"],
            config={},
        )

        assert tier_map.get("MU") == "T3E_EARNINGS_OPTIONS"
        assert tier_map.get("BE") == "T3E_EARNINGS_OPTIONS"
        assert "MANUAL" not in {tier_map.get("MU"), tier_map.get("BE")}

        symbols = {r["symbol"] for r in rows}
        assert "MU" in symbols
        assert "BE" in symbols
