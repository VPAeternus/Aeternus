"""Tests for pass 14 — Unusual Options Activity scanner."""

import json
from unittest.mock import MagicMock, patch

import pytest


OPTIONS_FLOW_JSON = json.dumps({
    "trending": [
        {"ticker": "NVDA", "buzz_rank": 1, "sentiment": "BULLISH", "velocity": "ACCELERATING", "catalyst": "Massive call sweeps ahead of earnings", "sector": "Technology"},
        {"ticker": "TSLA", "buzz_rank": 2, "sentiment": "NEUTRAL", "velocity": "STEADY", "catalyst": "Dark pool prints above ask", "sector": "Consumer Discretionary"},
    ],
    "options_flow": [
        {"ticker": "NVDA", "flow_type": "sweep", "direction": "calls", "expiry_bucket": "weekly", "premium_size": "whale", "accounts_flagged": 3, "detail": "$2M in NVDA 950C weeklies swept at ask"},
        {"ticker": "TSLA", "flow_type": "dark_pool", "direction": "mixed", "expiry_bucket": "monthly", "premium_size": "large", "accounts_flagged": 1, "detail": "500k share dark pool print at $182"},
    ],
})


def test_options_flow_prompt_exists():
    from tradingagents.dealflow.sources.x_feed_manual import generate_prompts

    prompts = generate_prompts()
    pass_14 = [p for p in prompts if p[0] == 14]
    assert len(pass_14) == 1
    pnum, label, text = pass_14[0]
    assert label == "Unusual Options Activity"
    assert "sweep" in text.lower()
    assert "dark pool" in text.lower()
    assert "options_flow" in text


def test_options_flow_parse():
    from tradingagents.dealflow.sources.x_feed_manual import parse_pass

    entries = parse_pass(OPTIONS_FLOW_JSON, 14)
    assert len(entries) == 2
    assert entries[0]["ticker"] == "NVDA"
    assert entries[0]["source_pass_type"] == "options_flow"
    assert entries[0]["pass_number"] == 14
    assert entries[1]["ticker"] == "TSLA"


def test_options_flow_ingest_extracts_flow(tmp_path, monkeypatch):
    from tradingagents.dealflow.sources import x_feed_manual as mod

    monkeypatch.setattr(mod, "_merged_path", lambda d: str(tmp_path / "merged.json"))
    monkeypatch.setattr(mod, "_raw_dir", lambda d: str(tmp_path / "raw"))

    result = mod.ingest_pass("2026-03-06", OPTIONS_FLOW_JSON, 14, dry_run=True)

    assert result["pass_num"] == 14
    assert result["tickers_parsed"] == 2
    assert len(result["options_flow"]) == 2
    assert result["options_flow"][0]["ticker"] == "NVDA"
    assert result["options_flow"][0]["flow_type"] == "sweep"
    assert result["options_flow"][1]["direction"] == "mixed"


def test_options_flow_akg_fields(tmp_path, monkeypatch):
    from tradingagents.dealflow.sources import x_feed_manual as mod

    # Mock AKG
    mock_akg = MagicMock()
    mock_akg._nodes = {}
    mock_load = MagicMock(return_value=mock_akg)

    with patch("tradingagents.graph.knowledge_graph.AeternusKnowledgeGraph.load", mock_load):
        entries = [
            {"ticker": "NVDA", "mentions_estimate": 1, "velocity_z": 1.5, "velocity_trend": "rising", "sentiment": 0.5, "pass_number": 14, "catalyst": "Call sweeps"},
            {"ticker": "TSLA", "mentions_estimate": 2, "velocity_z": 0.3, "velocity_trend": "stable", "sentiment": 0.0, "pass_number": 14, "catalyst": "Dark pool"},
        ]
        flow = [
            {"ticker": "NVDA", "flow_type": "sweep", "direction": "calls", "expiry_bucket": "weekly", "premium_size": "whale", "accounts_flagged": 3, "detail": "$2M call sweep"},
            {"ticker": "TSLA", "flow_type": "dark_pool", "direction": "mixed", "expiry_bucket": "monthly", "premium_size": "large", "accounts_flagged": 1, "detail": "500k DP print"},
        ]

        result = mod.write_akg(entries, "2026-03-06", options_flow=flow)

    assert result["written"] == 2
    assert result["new"] == 2  # both new nodes

    # Verify options_flow_at and options_flow_data written
    update_calls = mock_akg.update_node_field.call_args_list
    flow_at_calls = [(c[0][0], c[0][1]) for c in update_calls if c[0][1] == "options_flow_at"]
    flow_data_calls = [(c[0][0], c[0][1]) for c in update_calls if c[0][1] == "options_flow_data"]

    assert len(flow_at_calls) == 2
    assert ("NVDA", "options_flow_at") in flow_at_calls
    assert ("TSLA", "options_flow_at") in flow_at_calls
    assert len(flow_data_calls) == 2


def test_options_flow_no_flow_entries_no_akg_flow_fields(tmp_path, monkeypatch):
    """When options_flow is empty, no flow fields should be written."""
    from tradingagents.dealflow.sources import x_feed_manual as mod

    mock_akg = MagicMock()
    mock_akg._nodes = {"AAPL": {}}
    mock_load = MagicMock(return_value=mock_akg)

    with patch("tradingagents.graph.knowledge_graph.AeternusKnowledgeGraph.load", mock_load):
        entries = [
            {"ticker": "AAPL", "mentions_estimate": 1, "velocity_z": 0.0, "velocity_trend": "stable", "sentiment": 0.0, "pass_number": 1, "catalyst": "iPhone"},
        ]
        mod.write_akg(entries, "2026-03-06", options_flow=[])

    update_calls = mock_akg.update_node_field.call_args_list
    flow_fields = [c for c in update_calls if "options_flow" in str(c[0][1])]
    assert len(flow_fields) == 0
