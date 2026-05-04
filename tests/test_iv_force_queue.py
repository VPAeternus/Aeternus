"""Tests for IV force-queue injection into deep analysis reserve slots (S-083)."""

from unittest.mock import MagicMock, patch

import pytest

from tradingagents.dealflow.pipeline import DealFlowPipeline


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _minimal_config(**overrides):
    cfg = {
        "dealflow_deep_k": 12,
        "dealflow_deep_core_quota": 4,
        "dealflow_deep_momentum_quota": 4,
        "dealflow_deep_reserve_quota": 4,
        "dealflow_manual_watchlist_path": "/nonexistent/watchlist.json",
    }
    cfg.update(overrides)
    return cfg


def _make_item(symbol, lane="CORE", source="AUTO", triage=70.0, run_id="test-run"):
    return {
        "queue_id": f"{run_id}:{symbol}",
        "symbol": symbol,
        "asset_class": "Equity",
        "sector": "Technology",
        "lane": lane,
        "deal_flow_score": 60.0,
        "momentum_score": 65.0,
        "asymmetry_score": 55.0,
        "subscores": {},
        "thesis_tags": ["balanced"],
        "risk_tags": [],
        "evidence": {"active_families": 3, "evidence_count": 8, "freshness_hours": 2.0},
        "why_now": "test",
        "source": source,
        "source_detail": "AUTO_MODEL" if source == "AUTO" else "MANUAL_WATCHLIST",
        "manual_note": "",
        "research_playbook": "growth_conviction",
        "triage_score": triage,
        "selected_for_deep": False,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestIVForceQueueInjection:
    """IV force-queue candidates appear in research queue reserve slots."""

    def test_iv_candidates_appear_with_correct_source(self):
        """IV candidates are added to items with source=IV_FORCE_QUEUE."""
        pipe = DealFlowPipeline(config=_minimal_config())
        pipe._iv_force_queue = [{"symbol": "NFLX", "reason": "IV underpriced"}]

        items = [_make_item("AAPL"), _make_item("MSFT")]
        selected_ids = [items[0]["queue_id"]]

        items_out, ids_out = pipe._inject_force_queue_candidates(
            items=items, selected_ids=selected_ids,
            deep_k=12, reserve_quota=4, run_id="test-run",
        )

        nflx_items = [i for i in items_out if i["symbol"] == "NFLX"]
        assert len(nflx_items) == 1
        assert nflx_items[0]["source"] == "IV_FORCE_QUEUE"
        assert nflx_items[0]["lane"] == "RESERVE"
        assert nflx_items[0]["queue_id"] in ids_out

    def test_iv_candidates_selected_for_deep(self):
        """IV candidates get selected_for_deep=True within reserve quota."""
        pipe = DealFlowPipeline(config=_minimal_config())
        pipe._iv_force_queue = [
            {"symbol": "NFLX"},
            {"symbol": "AMZN"},
        ]

        items = [_make_item("AAPL"), _make_item("MSFT")]
        selected_ids = [items[0]["queue_id"], items[1]["queue_id"]]

        items_out, ids_out = pipe._inject_force_queue_candidates(
            items=items, selected_ids=selected_ids,
            deep_k=12, reserve_quota=4, run_id="test-run",
        )

        nflx = next(i for i in items_out if i["symbol"] == "NFLX")
        amzn = next(i for i in items_out if i["symbol"] == "AMZN")
        assert nflx["selected_for_deep"] is True
        assert amzn["selected_for_deep"] is True
        assert nflx["queue_id"] in ids_out
        assert amzn["queue_id"] in ids_out

    def test_auto_candidates_not_displaced(self):
        """Auto-ranked candidates (8 slots) are never displaced by IV injection."""
        pipe = DealFlowPipeline(config=_minimal_config())
        pipe._iv_force_queue = [{"symbol": "NFLX"}]

        # 8 auto candidates already selected
        auto_symbols = ["AAPL", "MSFT", "GOOG", "NVDA", "META", "TSLA", "AMD", "CRM"]
        items = [_make_item(s, triage=90.0 - i) for i, s in enumerate(auto_symbols)]
        selected_ids = [item["queue_id"] for item in items]
        original_selected = list(selected_ids)

        items_out, ids_out = pipe._inject_force_queue_candidates(
            items=items, selected_ids=selected_ids,
            deep_k=12, reserve_quota=4, run_id="test-run",
        )

        # All original auto selections still present
        for orig_id in original_selected:
            assert orig_id in ids_out, f"{orig_id} was displaced"

        # IV candidate was added (not replacing anyone)
        assert "test-run:NFLX" in ids_out
        assert len(ids_out) == 9  # 8 auto + 1 IV

    def test_reserve_quota_respects_manual_count(self):
        """Reserve quota shared: manual(2) + IV overflow(3) → only 2 IV selected."""
        pipe = DealFlowPipeline(config=_minimal_config(dealflow_deep_reserve_quota=4))
        pipe._iv_force_queue = [
            {"symbol": "NFLX"},
            {"symbol": "AMZN"},
            {"symbol": "DIS"},
        ]

        # 2 manual items already selected for deep
        items = [
            _make_item("AAPL", source="MANUAL", triage=80.0),
            _make_item("GOOG", source="MANUAL", triage=75.0),
            _make_item("MSFT", source="AUTO", triage=90.0),
        ]
        selected_ids = [items[0]["queue_id"], items[1]["queue_id"], items[2]["queue_id"]]

        items_out, ids_out = pipe._inject_force_queue_candidates(
            items=items, selected_ids=selected_ids,
            deep_k=12, reserve_quota=4, run_id="test-run",
        )

        iv_selected = [
            i for i in items_out
            if i.get("source") == "IV_FORCE_QUEUE" and i["queue_id"] in set(ids_out)
        ]
        # 4 reserve - 2 manual = 2 available for IV
        assert len(iv_selected) == 2
        # DIS should NOT be selected (3rd IV candidate, only 2 slots)
        dis_items = [i for i in items_out if i["symbol"] == "DIS"]
        if dis_items:
            assert dis_items[0]["queue_id"] not in set(ids_out)

    def test_existing_symbol_promoted_not_duplicated(self):
        """If an IV candidate symbol is already in the queue, promote it instead of duplicating."""
        pipe = DealFlowPipeline(config=_minimal_config())
        pipe._iv_force_queue = [{"symbol": "MSFT"}]

        items = [_make_item("AAPL", triage=90.0), _make_item("MSFT", triage=60.0)]
        selected_ids = [items[0]["queue_id"]]  # Only AAPL selected

        items_out, ids_out = pipe._inject_force_queue_candidates(
            items=items, selected_ids=selected_ids,
            deep_k=12, reserve_quota=4, run_id="test-run",
        )

        # MSFT should be promoted to selected, not duplicated
        msft_items = [i for i in items_out if i["symbol"] == "MSFT"]
        assert len(msft_items) == 1  # No duplication
        assert msft_items[0]["queue_id"] in ids_out  # Promoted to selected
