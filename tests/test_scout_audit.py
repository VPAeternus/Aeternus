"""Tests for scout enrichment audit log."""

import json
import os
from pathlib import Path

from tradingagents.dealflow.pipeline import DealFlowPipeline


MOCK_BREAKOUT = {"alerts": [{"ticker": "AAPL", "score": 72.5, "near_high": 0.98}]}
MOCK_IV = {"force_queue": [{"ticker": "MSFT"}], "akg_enriched": ["MSFT"]}
MOCK_INSIDER = {
    "buy_clusters": [{"ticker": "NVDA", "cluster_score": 0.9, "distinct_insiders": 3}],
    "sell_clusters": [{"ticker": "TSLA", "cluster_score": 0.6, "distinct_insiders": 2}],
}


def test_build_scout_audit_extracts_symbols(tmp_path, monkeypatch):
    """Verify audit dict shape from mock scout results."""
    monkeypatch.chdir(tmp_path)
    p = DealFlowPipeline()
    audit = p._build_scout_audit("2026-03-06", MOCK_BREAKOUT, MOCK_IV, MOCK_INSIDER)

    assert audit["date"] == "2026-03-06"
    assert audit["breakout"]["count"] == 1
    assert audit["breakout"]["alerts"][0]["ticker"] == "AAPL"
    assert audit["iv"]["force_queue"] == ["MSFT"]
    assert audit["insider"]["buy_clusters"][0]["ticker"] == "NVDA"
    assert audit["insider"]["sell_clusters"][0]["ticker"] == "TSLA"


def test_scout_audit_written_to_disk(tmp_path, monkeypatch):
    """Verify audit JSON file is created on disk."""
    monkeypatch.chdir(tmp_path)
    p = DealFlowPipeline()
    p._build_scout_audit("2026-03-06", MOCK_BREAKOUT, MOCK_IV, {"buy_clusters": [], "sell_clusters": []})

    out = tmp_path / "eval_results" / "deal_flow" / "2026-03-06" / "scout_audit.json"
    assert out.exists()
    data = json.loads(out.read_text())
    assert data["breakout"]["alerts"][0]["ticker"] == "AAPL"
    assert data["insider"]["buy_clusters"] == []
