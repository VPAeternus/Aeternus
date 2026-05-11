"""Tests for the Position Review Engine."""

from __future__ import annotations

import datetime as dt
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures — minimal AKG stub
# ---------------------------------------------------------------------------

class _StubAKG:
    """Minimal AKG stub with _nodes dict and thesis stress."""

    def __init__(self):
        self._nodes = {}

    def add_node(self, ticker, **kwargs):
        self._nodes[ticker] = {"ticker": ticker, **kwargs}

    def get_thesis_stress_report(self, ticker):
        node = self._nodes.get(ticker, {})
        level = node.get("_stub_stress_level", "NONE")
        return {"ticker": ticker, "stress_level": level, "claims_total": 0, "claims_stressed": 0, "stressed_claims": []}


def _make_position(symbol, entry_score=75, avg_price=100, mark_price=110, qty=10, days_ago=14):
    opened = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days_ago)).isoformat()
    return {
        "entry_aeternus_score": entry_score,
        "avg_price": avg_price,
        "last_mark_price": mark_price,
        "net_quantity": qty,
        "opened_at": opened,
    }


# ---------------------------------------------------------------------------
# Task 1 tests: write_pillar_scores
# ---------------------------------------------------------------------------

class TestWritePillarScores:

    def test_write_pillar_scores(self):
        """last_{pillar}_score fields are written to AKG node."""
        from tradingagents.graph.knowledge_graph import AeternusKnowledgeGraph

        akg = AeternusKnowledgeGraph.__new__(AeternusKnowledgeGraph)
        akg._nodes = {"AAPL": {"ticker": "AAPL", "node_type": "company"}}
        akg._updated_at = ""

        breakdown = {"fundamentals": 72.5, "momentum": 65.0, "sentiment": 80.3}
        akg.write_pillar_scores("AAPL", breakdown, "2026-03-05")

        node = akg._nodes["AAPL"]
        assert node["last_fundamentals_score"] == 72.5
        assert node["last_momentum_score"] == 65.0
        assert node["last_sentiment_score"] == 80.3
        assert node["last_pillar_scores_updated"] == "2026-03-05"

    def test_write_pillar_scores_skips_missing_ticker(self):
        """Does not crash if ticker is not in AKG."""
        from tradingagents.graph.knowledge_graph import AeternusKnowledgeGraph

        akg = AeternusKnowledgeGraph.__new__(AeternusKnowledgeGraph)
        akg._nodes = {}

        # Should not raise
        akg.write_pillar_scores("MISSING", {"fundamentals": 50}, "2026-03-05")
        assert "MISSING" not in akg._nodes

    def test_thesis_stress_works_after_pillar_write(self):
        """get_thesis_stress_report returns correct stress after write_pillar_scores."""
        from tradingagents.graph.knowledge_graph import AeternusKnowledgeGraph

        akg = AeternusKnowledgeGraph.__new__(AeternusKnowledgeGraph)
        akg._nodes = {"SMCI": {"ticker": "SMCI", "node_type": "company"}}
        akg._updated_at = ""

        # Set thesis claims with stress thresholds
        akg._nodes["SMCI"]["thesis_claims"] = [
            {"pillar": "fundamentals", "claim": "strong revenue", "entry_score": 80, "stress_threshold": 50},
            {"pillar": "momentum", "claim": "price trend", "entry_score": 70, "stress_threshold": 45},
            {"pillar": "sentiment", "claim": "bullish news", "entry_score": 75, "stress_threshold": 50},
        ]

        # Write scores — 2 below threshold
        akg.write_pillar_scores("SMCI", {"fundamentals": 40, "momentum": 30, "sentiment": 60}, "2026-03-05")

        report = akg.get_thesis_stress_report("SMCI")
        assert report["stress_level"] == "STRESS"  # 2 pillars below threshold
        assert report["claims_stressed"] == 2


# ---------------------------------------------------------------------------
# Task 2 tests: review_positions
# ---------------------------------------------------------------------------

class TestReviewPositions:

    def test_review_hold(self):
        """Position above V3 hurdle with no stress -> HOLD."""
        from tradingagents.graph.position_review import review_positions

        positions = {"PLTR": _make_position("PLTR", entry_score=78)}
        akg = _StubAKG()
        akg._nodes["PLTR"] = {"last_aeternus_score": 75}

        results = review_positions(positions, akg=akg)
        assert len(results) == 1
        assert results[0]["recommendation"] == "HOLD"
        assert results[0]["symbol"] == "PLTR"

    def test_review_exit_low_score(self):
        """Position below V3 hurdle -> EXIT."""
        from tradingagents.graph.position_review import review_positions

        positions = {"SOFI": _make_position("SOFI", entry_score=65)}
        akg = _StubAKG()
        akg._nodes["SOFI"] = {"last_aeternus_score": 50}

        results = review_positions(positions, akg=akg)
        assert results[0]["recommendation"] == "EXIT"
        assert "below V3" in results[0]["reason"]

    def test_review_exit_thesis_critical(self):
        """Position with 3+ stressed pillars -> EXIT."""
        from tradingagents.graph.position_review import review_positions

        positions = {"SMCI": _make_position("SMCI", entry_score=71)}
        akg = _StubAKG()
        akg._nodes["SMCI"] = {"last_aeternus_score": 65, "_stub_stress_level": "CRITICAL"}

        results = review_positions(positions, akg=akg)
        assert results[0]["recommendation"] == "EXIT"
        assert "pillars stressed" in results[0]["reason"]

    def test_review_watch_score_decay(self):
        """Score dropped 20%+ from entry -> WATCH."""
        from tradingagents.graph.position_review import review_positions

        positions = {"COIN": _make_position("COIN", entry_score=80)}
        akg = _StubAKG()
        # 80 -> 63 = 21.25% decay, but still above V3 hurdle
        akg._nodes["COIN"] = {"last_aeternus_score": 63}

        results = review_positions(positions, akg=akg)
        assert results[0]["recommendation"] == "WATCH"
        assert "down" in results[0]["reason"]

    def test_review_rotate_opportunity(self):
        """Better researched candidate -> ROTATE."""
        from tradingagents.graph.position_review import review_positions

        positions = {"SOFI": _make_position("SOFI", entry_score=70)}
        akg = _StubAKG()
        akg._nodes["SOFI"] = {"last_aeternus_score": 68}

        candidates = [{"symbol": "NVDA", "aeternus_score": 92}]

        results = review_positions(positions, akg=akg, pipeline_candidates=candidates)
        assert results[0]["recommendation"] == "ROTATE"
        assert results[0]["rotate_to"] == "NVDA"

    def test_review_no_akg_falls_back(self):
        """Without AKG, uses entry_score as current and gets HOLD."""
        from tradingagents.graph.position_review import review_positions

        positions = {"AAPL": _make_position("AAPL", entry_score=78)}
        results = review_positions(positions, akg=None)
        assert results[0]["recommendation"] == "HOLD"
        assert results[0]["current_score"] == 78.0

    def test_review_sort_order(self):
        """EXIT comes before WATCH comes before HOLD in output."""
        from tradingagents.graph.position_review import review_positions

        positions = {
            "A": _make_position("A", entry_score=78),
            "B": _make_position("B", entry_score=65),
            "C": _make_position("C", entry_score=71),
        }
        akg = _StubAKG()
        akg._nodes["A"] = {"last_aeternus_score": 75}        # HOLD
        akg._nodes["B"] = {"last_aeternus_score": 50}        # EXIT (below hurdle)
        akg._nodes["C"] = {"last_aeternus_score": 65, "_stub_stress_level": "STRESS"}  # WATCH

        results = review_positions(positions, akg=akg)
        recs = [r["recommendation"] for r in results]
        assert recs == ["EXIT", "WATCH", "HOLD"]


# ---------------------------------------------------------------------------
# Task 4 test: morning brief integration
# ---------------------------------------------------------------------------

class TestMorningBriefHealth:

    def test_morning_brief_includes_health(self):
        """Morning brief output has position_health key."""
        from tradingagents.graph.morning_brief import build_morning_brief

        # Run with default paths (no positions file = empty positions = empty health)
        brief = build_morning_brief(
            positions_path="/tmp/nonexistent_positions.json",
            orders_path="/tmp/nonexistent.json",
            hwm_path="/tmp/nonexistent.json",
            deal_flow_path="/tmp/nonexistent_dir/",
            track_record_path="/tmp/nonexistent.json",
        )
        assert "position_health" in brief
        assert "total_held" in brief["position_health"]
        assert "actions" in brief["position_health"]
        assert "alerts" in brief["position_health"]
