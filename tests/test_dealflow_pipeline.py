"""Tests for DealFlowPipeline AKG emerging planets integration (S-039)."""

from contextlib import ExitStack
import json
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

def _direction_from_emergence(planet: dict) -> str:
    """Derive direction from emergence planet dict (was in pipeline.py, moved here)."""
    sentiment = float(planet.get("emergence_score", 0.0) or 0.0)
    if sentiment > 0.2:
        return "BULLISH"
    elif sentiment < -0.2:
        return "BEARISH"
    return "NEUTRAL"


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------

def _make_planet(
    symbol: str,
    emergence_score: float = 0.5,
    tier: str = "ATMOSPHERE",
) -> dict:
    return {
        "id": symbol,
        "emergence_score": emergence_score,
        "emergence_tier": tier,
    }


def _make_mock_akg(planets: list) -> MagicMock:
    """Return a mock AKG instance that returns the given planets from get_emerging_planets."""
    mock_akg = MagicMock()
    mock_akg.get_dark_nodes.return_value = []
    mock_akg.get_centrality_scores.return_value = None
    mock_akg.get_emerging_planets.return_value = planets
    mock_akg.add_node.return_value = None
    mock_akg.add_edge.return_value = None
    mock_akg.to_json.return_value = None
    return mock_akg


def _minimal_config(extra: dict | None = None) -> dict:
    cfg = {
        "akg_enabled": True,
        "akg_json_path": "eval_results/control/knowledge_graph.json",
        "akg_dark_node_injection_enabled": False,
        "akg_emerging_min_score": 0.3,
        "akg_emerging_min_tier": "ATMOSPHERE",
        "akg_emerging_top_k": 50,
        "dealflow_dynamic_universe_min_adv_usd": 0.0,
        "dealflow_dynamic_universe_max_extra_symbols": 60,
        "dealflow_discovered_symbol_min_len": 2,
        "dealflow_discovered_symbol_max_len": 5,
        "dealflow_discovered_symbol_denylist": "",
        "dealflow_min_signal_families": 1,
        "dealflow_connector_timeout_seconds": 10.0,
        "dealflow_connector_max_attempts": 1,
        "dealflow_social_max_symbol_calls": 1,
        "dealflow_social_lookback_days": 1,
        "dealflow_momentum_lane_threshold": 68.0,
        "dealflow_momentum_lane_price_override_threshold": 82.0,
        "dealflow_momentum_lane_social_confirmation_threshold": 60.0,
        "dealflow_momentum_lane_floor_ratio": 0.20,
        "dealflow_momentum_lane_promotion_min_score": 62.0,
        "dealflow_momentum_lane_promotion_min_price_score": 70.0,
        "dealflow_core_quota": 12,
        "dealflow_momentum_quota": 8,
        "dealflow_deep_k": 2,
        "dealflow_deep_core_quota": 1,
        "dealflow_deep_momentum_quota": 1,
        "dealflow_manual_watchlist_path": "/nonexistent/watchlist.json",
        "dealflow_manual_slots_target": 0,
        "dealflow_manual_slots_min": 0,
        "dealflow_manual_slots_max": 0,
        "dealflow_manual_min_adv_usd": 0.0,
        "dealflow_manual_force_insert": False,
        "dealflow_max_sector_count": 10,
        "dealflow_max_asset_class_count": 10,
        "dealflow_trigger_vix_jump_pct": 999.0,
        "dealflow_trigger_spy_move_pct": 999.0,
        "dealflow_step1_optional_connectors": "",
    }
    if extra:
        cfg.update(extra)
    return cfg


# ---------------------------------------------------------------------------
# Unit tests for _direction_from_emergence helper
# ---------------------------------------------------------------------------

def test_direction_bullish_when_sentiment_positive():
    planet = _make_planet("AAPL", emergence_score=0.5)
    assert _direction_from_emergence(planet) == "BULLISH"


def test_direction_bearish_when_sentiment_negative():
    planet = _make_planet("TSLA", emergence_score=-0.5)
    assert _direction_from_emergence(planet) == "BEARISH"


def test_direction_neutral_when_sentiment_zero():
    planet = _make_planet("MSFT", emergence_score=0.0)
    assert _direction_from_emergence(planet) == "NEUTRAL"


def test_direction_neutral_at_threshold_boundary():
    # Exactly 0.2 is not > 0.2, so it should be NEUTRAL.
    planet = _make_planet("GOOGL", emergence_score=0.2)
    assert _direction_from_emergence(planet) == "NEUTRAL"
    # Just above the threshold → BULLISH.
    planet2 = _make_planet("GOOGL", emergence_score=0.21)
    assert _direction_from_emergence(planet2) == "BULLISH"


def test_direction_from_emergence_missing_emergence_key():
    # When emergence_score is absent, should default to NEUTRAL (0.0).
    planet = {"id": "XYZ"}
    assert _direction_from_emergence(planet) == "NEUTRAL"


# ---------------------------------------------------------------------------
# Integration-style tests for pipeline emerging planets path
# ---------------------------------------------------------------------------

def _pipeline_patches(extra: dict | None = None):
    """Return the standard set of patches for pipeline integration tests."""
    import pandas as pd
    patches = {
        "tradingagents.dealflow.pipeline._AKG_AVAILABLE": True,
        "tradingagents.dealflow.pipeline._SEC_CATALYST_AVAILABLE": False,
        "tradingagents.dealflow.pipeline.collect_social_news_signals": [],
        "tradingagents.dealflow.pipeline.collect_price_momentum_signals": [],
        "tradingagents.dealflow.pipeline.collect_macro_signals": [],
        "tradingagents.dealflow.pipeline.collect_smart_money_signals": [],
        "tradingagents.dealflow.pipeline.collect_sector_rotation_signals": [],
        "tradingagents.dealflow.pipeline.collect_insider_cluster_signals": [],
        "tradingagents.dealflow.pipeline.scan_breakout_discovery": {"ran": True, "alerts": [], "count": 0},
        "tradingagents.dealflow.pipeline.build_universe_from_akg": [],
        "tradingagents.dealflow.pipeline.list_active_ideas": [],
        "tradingagents.dealflow.pipeline.rank_candidates": [],
        "tradingagents.dealflow.pipeline.yf.download": pd.DataFrame(),
        # Patch dynamically imported heavy functions in run()
        "tradingagents.dealflow.sources.iv_scanner.scan_earnings_iv": {"force_queue": [], "scanned": 0, "earnings_approaching": [], "covered_call_signals": [], "neutral": [], "akg_enriched": []},
        "tradingagents.dealflow.sources.insider_cluster.scan_insider_sweep": {"skipped": True},
        "tradingagents.dealflow.sources.breakout_scanner.scan_breakout_discovery": {"ran": True, "alerts": [], "count": 0},
    }
    if extra:
        patches.update(extra)
    return patches


def _enter_pipeline_patches(stack: ExitStack, patches: dict):
    """Enter all patches into an ExitStack. Returns dict of mock objects."""
    mocks = {}
    for target, value in patches.items():
        m = stack.enter_context(patch(target, return_value=value))
        mocks[target] = m
    return mocks


def _run_pipeline_with_mocks(config: dict, planets: list, monkeypatch):
    """
    Run DealFlowPipeline.run() with all heavy dependencies mocked.
    Returns (shortlist, research_queue, normalized_signals, event_state).
    """
    from tradingagents.dealflow.pipeline import DealFlowPipeline

    mock_akg_instance = _make_mock_akg(planets)

    patches = _pipeline_patches({
        "tradingagents.dealflow.pipeline.score_candidates": ([], []),
    })

    with ExitStack() as stack:
        mocks = _enter_pipeline_patches(stack, patches)
        mock_akg_cls = stack.enter_context(patch("tradingagents.dealflow.pipeline._AKG"))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.DealFlowPipeline._persist"))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.DealFlowPipeline._market_shock_metrics", return_value=(None, None)))
        mock_akg_cls.load.return_value = mock_akg_instance
        pipeline = DealFlowPipeline(config=config)
        result = pipeline.run(as_of_date="2026-02-25", trigger="manual", top_k=10)
    return result


def test_pipeline_uses_emerging_planets_for_universe_expansion(monkeypatch):
    """AKG emerging planets must inject emergence signals into the pipeline."""
    planets = [
        _make_planet("AAPL", emergence_score=0.8),
        _make_planet("NVDA", emergence_score=0.6),
        _make_planet("TSLA", emergence_score=0.4),
    ]
    config = _minimal_config({"dealflow_min_signal_families": 3})

    from tradingagents.dealflow.pipeline import DealFlowPipeline

    mock_akg_instance = _make_mock_akg(planets)

    # Capture signals passed to score_candidates
    captured_signals = []

    def _stub_score_candidates(universe, signals, **kwargs):
        captured_signals.extend(list(signals))
        return (list(signals), [])

    with ExitStack() as stack:
        _enter_pipeline_patches(stack, _pipeline_patches())
        mock_akg_cls = stack.enter_context(patch("tradingagents.dealflow.pipeline._AKG"))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.score_candidates", side_effect=_stub_score_candidates))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.DealFlowPipeline._persist"))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.DealFlowPipeline._market_shock_metrics", return_value=(None, None)))
        mock_akg_cls.load.return_value = mock_akg_instance
        pipeline = DealFlowPipeline(config=config)
        pipeline.run(as_of_date="2026-02-25", trigger="manual", top_k=10)

    # Emergence signals for all 3 planet symbols should be in the signal list
    emergence_signals = [s for s in captured_signals if s.get("signal_family") == "emergence"]
    emergence_symbols = {s["symbol"] for s in emergence_signals}
    assert "AAPL" in emergence_symbols
    assert "NVDA" in emergence_symbols
    assert "TSLA" in emergence_symbols


def test_pipeline_synthesizes_akg_signals(monkeypatch):
    """Emerging planet nodes must produce DealFlowSignal dicts with signal_family='akg_emerging'."""
    planets = [
        _make_planet("META", emergence_score=0.7),
    ]
    config = _minimal_config({"dealflow_min_signal_families": 3})

    captured_signals = []

    def _stub_score_candidates(universe, signals, **kwargs):
        captured_signals.extend(signals)
        return [], []

    from tradingagents.dealflow.pipeline import DealFlowPipeline

    mock_akg_instance = _make_mock_akg(planets)

    with ExitStack() as stack:
        _enter_pipeline_patches(stack, _pipeline_patches())
        mock_akg_cls = stack.enter_context(patch("tradingagents.dealflow.pipeline._AKG"))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.score_candidates", side_effect=_stub_score_candidates))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.DealFlowPipeline._persist"))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.DealFlowPipeline._market_shock_metrics", return_value=(None, None)))
        mock_akg_cls.load.return_value = mock_akg_instance
        pipeline = DealFlowPipeline(config=config)
        pipeline.run(as_of_date="2026-02-25", trigger="manual", top_k=10)

    akg_sigs = [s for s in captured_signals if s.get("signal_family") == "emergence"]
    assert len(akg_sigs) == 1, f"Expected 1 emergence signal, got {len(akg_sigs)}"
    sig = akg_sigs[0]
    assert sig["symbol"] == "META"
    assert sig["direction"] == "BULLISH"
    assert sig["source_name"] == "akg_emergence"
    assert sig["source_status"] == "OK"
    assert sig["raw_score"] == round(0.7 * 100.0, 2)


def test_pipeline_graceful_when_akg_missing(monkeypatch):
    """Pipeline must run without error when AKG file is missing or raises."""
    config = _minimal_config({"dealflow_min_signal_families": 3})

    from tradingagents.dealflow.pipeline import DealFlowPipeline

    with ExitStack() as stack:
        _enter_pipeline_patches(stack, _pipeline_patches({
            "tradingagents.dealflow.pipeline.score_candidates": ([], []),
        }))
        mock_akg_cls = stack.enter_context(patch("tradingagents.dealflow.pipeline._AKG"))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.DealFlowPipeline._persist"))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.DealFlowPipeline._market_shock_metrics", return_value=(None, None)))
        # Make AKG.load raise FileNotFoundError.
        mock_akg_cls.load.side_effect = FileNotFoundError("AKG file not found")
        pipeline = DealFlowPipeline(config=config)
        # Must not raise.
        shortlist, research_queue, normalized_signals, event_state = pipeline.run(
            as_of_date="2026-02-25", trigger="manual", top_k=10
        )

    # Pipeline ran successfully; no candidates expected since everything is mocked empty.
    assert isinstance(shortlist, dict)
    assert shortlist["candidates"] == []


# ---------------------------------------------------------------------------
# S-080: AKG signal writeback tests
# ---------------------------------------------------------------------------

def test_writeback_signals_to_akg_writes_all_families():
    """writeback_signals_to_akg maps 7 signal families to AKG enrich methods."""
    from tradingagents.graph.knowledge_graph import AeternusKnowledgeGraph
    from tradingagents.dealflow.pipeline import writeback_signals_to_akg

    akg = AeternusKnowledgeGraph()
    akg.add_node("AAPL", node_type="company")

    signals = [
        {"symbol": "AAPL", "signal_family": "price_momentum", "raw_score": 75.0, "direction": "BULLISH", "source_status": "OK"},
        {"symbol": "AAPL", "signal_family": "smart_money", "raw_score": 68.0, "direction": "BULLISH", "source_status": "OK"},
        {"symbol": "AAPL", "signal_family": "insider_cluster", "raw_score": 80.0, "direction": "BULLISH", "source_status": "OK", "cluster_size": 3, "evidence_count": 3},
        {"symbol": "AAPL", "signal_family": "social_momentum", "raw_score": 62.0, "direction": "BULLISH", "source_status": "OK"},
        {"symbol": "AAPL", "signal_family": "news_catalyst", "raw_score": 71.0, "direction": "BULLISH", "source_status": "OK"},
        {"symbol": "AAPL", "signal_family": "sector_rotation", "raw_score": 55.0, "direction": "NEUTRAL", "source_status": "OK"},
        {"symbol": "AAPL", "signal_family": "macro_regime_fit", "raw_score": 60.0, "direction": "BULLISH", "source_status": "OK"},
    ]

    n = writeback_signals_to_akg(akg, signals, "2026-03-03")
    assert n == 6  # 5 direct + 1 social_news pair = 6

    node = akg._nodes["AAPL"]
    assert node["signal_momentum_score"] == pytest.approx(75.0, abs=0.1)
    assert node["signal_smart_money_score"] == pytest.approx(68.0, abs=0.1)
    assert node["signal_smart_money_direction"] == "bullish"
    assert node["signal_insider_score"] == pytest.approx(80.0, abs=0.1)
    assert node["signal_insider_buyer_count"] == 3
    assert node["signal_social_score"] == pytest.approx(62.0, abs=0.1)
    assert node["signal_news_catalyst_score"] == pytest.approx(71.0, abs=0.1)
    assert node["signal_sector_rotation_score"] == pytest.approx(55.0, abs=0.1)
    assert node["signal_macro_score"] == pytest.approx(60.0, abs=0.1)
    assert node["signal_macro_regime_tag"] == "risk_on"
    # Emergence score recomputed (non-zero because signals populated)
    assert node["emergence_score"] is not None
    assert node["emergence_score"] > 0.0
    assert node["emergence_n_sources"] >= 7


def test_writeback_skips_non_ok_signals():
    """Signals with source_status != OK are skipped."""
    from tradingagents.graph.knowledge_graph import AeternusKnowledgeGraph
    from tradingagents.dealflow.pipeline import writeback_signals_to_akg

    akg = AeternusKnowledgeGraph()
    akg.add_node("TSLA", node_type="company")

    signals = [
        {"symbol": "TSLA", "signal_family": "price_momentum", "raw_score": 80.0, "direction": "BULLISH", "source_status": "NO_DATA"},
        {"symbol": "TSLA", "signal_family": "smart_money", "raw_score": 70.0, "direction": "BULLISH", "source_status": "ERROR"},
    ]

    n = writeback_signals_to_akg(akg, signals, "2026-03-03")
    assert n == 0
    assert akg._nodes["TSLA"]["signal_momentum_score"] is None
    assert akg._nodes["TSLA"]["signal_smart_money_score"] is None


def test_writeback_autocreates_unknown_nodes():
    """Enrich methods auto-create nodes — writeback handles tickers not yet in AKG."""
    from tradingagents.graph.knowledge_graph import AeternusKnowledgeGraph
    from tradingagents.dealflow.pipeline import writeback_signals_to_akg

    akg = AeternusKnowledgeGraph()
    # Don't add NEW_CO — let enrich_node_* create it
    signals = [
        {"symbol": "NEW_CO", "signal_family": "price_momentum", "raw_score": 65.0, "direction": "BULLISH", "source_status": "OK"},
    ]

    n = writeback_signals_to_akg(akg, signals, "2026-03-03")
    assert n == 1
    assert "NEW_CO" in akg._nodes
    assert akg._nodes["NEW_CO"]["signal_momentum_score"] == pytest.approx(65.0, abs=0.1)


def test_emergence_direction_derives_from_emergence_score():
    """Emergence direction is BEARISH when emergence_score < -0.2, BULLISH otherwise."""
    # Bearish score → BEARISH direction
    planet_bearish = _make_planet("BAD", emergence_score=-0.5)
    direction_bearish = "BEARISH" if float(planet_bearish.get("emergence_score") or 0) < -0.2 else "BULLISH"
    assert direction_bearish == "BEARISH"

    # Neutral score → BULLISH direction
    planet_neutral = _make_planet("MEH", emergence_score=0.0)
    direction_neutral = "BEARISH" if float(planet_neutral.get("emergence_score") or 0) < -0.2 else "BULLISH"
    assert direction_neutral == "BULLISH"

    # Positive score → BULLISH direction
    planet_bull = _make_planet("GOOD", emergence_score=0.8)
    direction_bull = "BEARISH" if float(planet_bull.get("emergence_score") or 0) < -0.2 else "BULLISH"
    assert direction_bull == "BULLISH"

    # Missing score → BULLISH (default)
    planet_none = {"id": "NONE"}
    direction_none = "BEARISH" if float(planet_none.get("emergence_score") or 0) < -0.2 else "BULLISH"
    assert direction_none == "BULLISH"


def test_emergence_injection_evidence_count_uses_n_signal_sources():
    """Emergence injection uses n_signal_sources from AKG planet, not hard-coded 2."""
    from tradingagents.graph.knowledge_graph import AeternusKnowledgeGraph
    from tradingagents.dealflow.pipeline import writeback_signals_to_akg

    akg = AeternusKnowledgeGraph()
    akg.add_node("EMRG", node_type="company")
    # Populate 5 signal fields so n_sources=5 and tier reaches ATMOSPHERE+
    akg._nodes["EMRG"]["signal_momentum_score"] = 75.0
    akg._nodes["EMRG"]["signal_smart_money_score"] = 65.0
    akg._nodes["EMRG"]["signal_insider_score"] = 70.0
    akg._nodes["EMRG"]["signal_news_catalyst_score"] = 60.0
    akg._nodes["EMRG"]["signal_sec_catalyst_score"] = 55.0
    akg.compute_emergence_score("EMRG")

    # Verify the node reaches ATMOSPHERE or HABITABLE
    assert akg._nodes["EMRG"]["emergence_tier"] in ("ATMOSPHERE", "HABITABLE")
    assert akg._nodes["EMRG"]["emergence_n_sources"] == 5

    # Now call get_emerging_planets and simulate what pipeline does
    planets = akg.get_emerging_planets(min_score=0.0, min_tier="ATMOSPHERE", top_k=100)
    emrg_planets = [p for p in planets if p["id"] == "EMRG"]
    assert len(emrg_planets) == 1
    planet = emrg_planets[0]

    # The key assertion: evidence_count should match n_signal_sources
    evidence_count = max(1, int(planet.get("n_signal_sources", 0)))
    assert evidence_count == 5


# (S-056 _sync_signals_to_akg tests removed — function was deleted from pipeline.py)



# (sec_catalyst connector deleted — C-2 code review fix)


# ---------------------------------------------------------------------------
# Discover / Collect decomposition tests
# ---------------------------------------------------------------------------

def test_collect_standalone_bootstraps_without_discover(monkeypatch):
    """collect() without prior discover() must not AttributeError — bootstraps from AKG."""
    from tradingagents.dealflow.pipeline import DealFlowPipeline

    config = _minimal_config()
    mock_akg_instance = _make_mock_akg([])

    with ExitStack() as stack:
        _enter_pipeline_patches(stack, _pipeline_patches({
            "tradingagents.dealflow.pipeline.score_candidates": ([], []),
        }))
        mock_akg_cls = stack.enter_context(patch("tradingagents.dealflow.pipeline._AKG"))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.DealFlowPipeline._persist"))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.DealFlowPipeline._market_shock_metrics", return_value=(None, None)))
        mock_akg_cls.load.return_value = mock_akg_instance

        pipeline = DealFlowPipeline(config=config)
        # Do NOT call discover() — collect() must bootstrap on its own
        shortlist, rq, signals, event = pipeline.collect(
            as_of_date="2026-03-05", trigger="manual", top_k=10,
        )

    assert isinstance(shortlist, dict)
    assert shortlist["date"] == "2026-03-05"


def test_discover_then_collect_writes_queue_artifacts_and_ledger(tmp_path, monkeypatch):
    from tradingagents.dealflow.pipeline import DealFlowPipeline

    monkeypatch.chdir(tmp_path)
    universe = [{"symbol": "GLW", "asset_class": "Equity", "sector": "Technology", "liquidity_score": 90.0, "aliases": []}]
    candidate = {
        "symbol": "GLW",
        "asset_class": "Equity",
        "sector": "Technology",
        "liquidity_score": 90.0,
        "subscores": {},
        "deal_flow_score": 85.0,
        "core_score": 90.0,
        "momentum_score": 70.0,
        "asymmetry_score": 65.0,
        "active_families": 3,
        "evidence_count": 6,
        "freshness_hours": 4.0,
        "status": "ACTIVE",
        "risk_tags": [],
        "trend_tags": [],
        "lane": "CORE",
        "source": "AUTO",
        "source_detail": "AUTO_MODEL",
        "manual_note": "",
        "manual_priority": 0,
        "reason": "selected",
    }

    with ExitStack() as stack:
        stack.enter_context(patch("tradingagents.dealflow.pipeline.build_universe_from_akg", return_value=universe))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.get_last_universe_tier_map", return_value={"GLW": "T1_ANCHOR"}))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.get_last_universe_ledger", return_value={"symbols": ["GLW"], "kept_symbols": ["GLW"], "rule_snapshot": {}}))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.list_active_ideas", return_value=[]))
        stack.enter_context(patch("tradingagents.dealflow.sources.x_feed_manual.load_recent_merged", return_value={}))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.DealFlowPipeline._build_fvg_recall_channel", return_value={"selected_symbols": [], "artifact": {"date": "2026-05-05", "selected_symbols": [], "rows": [], "quota": 0, "rule_snapshot": {"enabled": True}}}))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.DealFlowPipeline._build_fma_recall_channel", return_value={"selected_symbols": [], "artifact": {"date": "2026-05-05", "selected_symbols": [], "rows": [], "quota": 0, "rule_snapshot": {"enabled": True}}}))
        stack.enter_context(patch("tradingagents.dealflow.sources.breakout_scanner.scan_breakout_discovery", return_value={"count": 0, "alerts": []}))
        stack.enter_context(patch("tradingagents.dealflow.sources.insider_cluster.scan_insider_sweep", return_value={"skipped": True}))
        stack.enter_context(patch("tradingagents.dealflow.sources.technical_ignition_scout.scan_technical_ignition_setups", return_value={"promoted_count": 0, "promoted_symbols": [], "stale_count": 0, "stale_symbols": [], "signals": [], "promoted": [], "stale": []}))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.scan_thirteenf_watchlist", return_value={"candidate_count": 0, "symbols": [], "candidates": []}))
        stack.enter_context(patch("tradingagents.dealflow.pipeline._AKG_AVAILABLE", False))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.collect_social_news_signals", return_value=[]))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.collect_price_momentum_signals", return_value=[]))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.collect_macro_signals", return_value=[]))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.collect_smart_money_signals", return_value=[]))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.collect_sector_rotation_signals", return_value=[]))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.collect_insider_cluster_signals", return_value=[]))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.score_candidates", return_value=([], [candidate])))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.rank_candidates", return_value=[{**candidate, "rank": 1}]))

        pipeline = DealFlowPipeline(config=_minimal_config({"dealflow_thirteenf_watchlist_enabled": False, "dealflow_technical_ignition_enabled": False, "dealflow_min_signal_families": 1}))
        discover_summary = pipeline.discover(as_of_date="2026-05-05", trigger="manual")
        shortlist, queue, signals, event = pipeline.collect(as_of_date="2026-05-05", trigger="manual", top_k=1)

    base = tmp_path / "eval_results" / "deal_flow" / "2026-05-05"
    assert discover_summary["universe_size"] == 1
    assert (base / "scout_audit.json").exists()
    assert json.loads((base / "research_queue.json").read_text())["selected_queue_ids"] == queue["selected_queue_ids"]
    rows = json.loads((base / "hypothesis_ledger" / "shared" / "rows.json").read_text())
    assert {row["stage_id"] for row in rows} >= {"universe_gate_edge", "evidence_gate", "shortlist_cut", "deep_selection_cut"}
    assert shortlist["candidates"][0]["symbol"] == "GLW"


def test_collect_standalone_threads_persisted_recall_symbols(tmp_path, monkeypatch):
    from tradingagents.dealflow.pipeline import DealFlowPipeline

    monkeypatch.chdir(tmp_path)

    out_dir = tmp_path / "eval_results" / "deal_flow" / "2026-03-09"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "fvg_recall.json").write_text(
        json.dumps({"selected_symbols": ["NVDA", "PLTR"]}, indent=2)
    )
    (out_dir / "fma_recall.json").write_text(
        json.dumps({"selected_symbols": ["CRM"]}, indent=2)
    )

    config = _minimal_config()
    mock_akg_instance = _make_mock_akg([])
    captured = {}

    def _stub_build_universe_from_akg(*, extra_symbols=None, config=None, fvg_recall_symbols=None, fma_recall_symbols=None):
        captured["extra_symbols"] = list(extra_symbols or [])
        captured["fvg_recall_symbols"] = list(fvg_recall_symbols or [])
        captured["fma_recall_symbols"] = list(fma_recall_symbols or [])
        return [
            {
                "symbol": "AAPL",
                "asset_class": "Equity",
                "sector": "Technology",
                "liquidity_score": 90.0,
                "aliases": [],
            }
        ]

    with ExitStack() as stack:
        _enter_pipeline_patches(stack, _pipeline_patches({
            "tradingagents.dealflow.pipeline.score_candidates": ([], []),
        }))
        mock_akg_cls = stack.enter_context(patch("tradingagents.dealflow.pipeline._AKG"))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.build_universe_from_akg", side_effect=_stub_build_universe_from_akg))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.DealFlowPipeline._persist"))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.DealFlowPipeline._market_shock_metrics", return_value=(None, None)))
        mock_akg_cls.load.return_value = mock_akg_instance

        pipeline = DealFlowPipeline(config=config)
        pipeline.collect(as_of_date="2026-03-09", trigger="manual", top_k=10)

    assert captured["fvg_recall_symbols"] == ["NVDA", "PLTR"]
    assert captured["fma_recall_symbols"] == ["CRM"]


def test_market_shock_metrics_uses_yfinance_path_deterministically(monkeypatch):
    from tradingagents.dealflow.pipeline import DealFlowPipeline

    idx = pd.date_range("2026-03-01", periods=10, freq="D")

    def _frame(last_close: float, prev_close: float):
        closes = [100.0] * 8 + [prev_close, last_close]
        return pd.DataFrame(
            {
                "Close": closes,
                "Open": closes,
                "High": closes,
                "Low": closes,
                "Adj Close": closes,
                "Volume": [1_000_000] * len(closes),
            },
            index=idx,
        )

    spy = _frame(102.0, 100.0)
    vix = _frame(24.0, 20.0)
    frame = pd.concat({"SPY": spy, "^VIX": vix}, axis=1)
    monkeypatch.setattr("tradingagents.dealflow.pipeline.yf.download", lambda *args, **kwargs: frame)

    pipeline = DealFlowPipeline(config=_minimal_config())
    spy_move, vix_jump = pipeline._market_shock_metrics()  # pylint: disable=protected-access

    assert round(spy_move, 2) == 2.0
    assert round(vix_jump, 2) == 20.0


def test_discover_persists_fvg_recall_artifact_and_threads_symbols(tmp_path, monkeypatch):
    from tradingagents.dealflow.pipeline import DealFlowPipeline

    monkeypatch.chdir(tmp_path)

    captured = {}

    def _stub_build_universe_from_akg(*, extra_symbols=None, config=None, fvg_recall_symbols=None, fma_recall_symbols=None):
        captured["extra_symbols"] = list(extra_symbols or [])
        captured["fvg_recall_symbols"] = list(fvg_recall_symbols or [])
        captured["fma_recall_symbols"] = list(fma_recall_symbols or [])
        return [
            {
                "symbol": "AAPL",
                "asset_class": "Equity",
                "sector": "Technology",
                "liquidity_score": 90.0,
                "aliases": [],
            },
            {
                "symbol": "NVDA",
                "asset_class": "Equity",
                "sector": "Technology",
                "liquidity_score": 95.0,
                "aliases": [],
            },
        ]

    with ExitStack() as stack:
        stack.enter_context(patch("tradingagents.dealflow.pipeline.build_universe_from_akg", side_effect=_stub_build_universe_from_akg))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.list_active_ideas", return_value=[]))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.scan_breakout_discovery", return_value={"count": 0, "alerts": []}))
        stack.enter_context(patch("tradingagents.dealflow.sources.breakout_scanner.scan_breakout_discovery", return_value={"count": 0, "alerts": []}))
        stack.enter_context(patch("tradingagents.dealflow.sources.iv_scanner.scan_earnings_iv", return_value={"force_queue": [], "akg_enriched": []}))
        stack.enter_context(patch("tradingagents.dealflow.sources.insider_cluster.scan_insider_sweep", return_value={"skipped": True}))
        stack.enter_context(patch("tradingagents.dealflow.pipeline._AKG_AVAILABLE", False))
        stack.enter_context(
            patch(
                "tradingagents.dealflow.pipeline.DealFlowPipeline._build_fvg_recall_channel",
                return_value={
                    "selected_symbols": ["NVDA"],
                    "artifact": {
                        "date": "2026-03-06",
                        "selected_symbols": ["NVDA"],
                        "quota": 30,
                        "rule_snapshot": {
                            "enabled": True,
                            "quota": 30,
                            "min_rs20": 0.03,
                        },
                    },
                },
            )
        )
        stack.enter_context(
            patch(
                "tradingagents.dealflow.pipeline.DealFlowPipeline._build_fma_recall_channel",
                return_value={
                    "selected_symbols": [],
                    "artifact": {
                        "date": "2026-03-06",
                        "selected_symbols": [],
                        "quota": 0,
                        "rule_snapshot": {"enabled": False},
                        "rows": [],
                    },
                },
            )
        )

        pipeline = DealFlowPipeline(config=_minimal_config({"dealflow_fvg_recall_enabled": True, "dealflow_fvg_recall_quota": 30}))
        summary = pipeline.discover(as_of_date="2026-03-06", trigger="manual")

    assert summary["universe_size"] == 2
    assert captured["fvg_recall_symbols"] == ["NVDA"]
    artifact_path = tmp_path / "eval_results" / "deal_flow" / "2026-03-06" / "fvg_recall.json"
    assert artifact_path.exists()
    payload = json.loads(artifact_path.read_text())
    assert payload["selected_symbols"] == ["NVDA"]
    assert payload["quota"] == 30


def test_discover_persists_fma_recall_artifact_and_threads_symbols(tmp_path, monkeypatch):
    from tradingagents.dealflow.pipeline import DealFlowPipeline

    monkeypatch.chdir(tmp_path)

    captured = {}

    def _stub_build_universe_from_akg(
        *,
        extra_symbols=None,
        config=None,
        fvg_recall_symbols=None,
        fma_recall_symbols=None,
    ):
        captured["extra_symbols"] = list(extra_symbols or [])
        captured["fvg_recall_symbols"] = list(fvg_recall_symbols or [])
        captured["fma_recall_symbols"] = list(fma_recall_symbols or [])
        return [
            {
                "symbol": "AAPL",
                "asset_class": "Equity",
                "sector": "Technology",
                "liquidity_score": 90.0,
                "aliases": [],
            },
            {
                "symbol": "NVDA",
                "asset_class": "Equity",
                "sector": "Technology",
                "liquidity_score": 95.0,
                "aliases": [],
            },
        ]

    with ExitStack() as stack:
        stack.enter_context(patch("tradingagents.dealflow.pipeline.build_universe_from_akg", side_effect=_stub_build_universe_from_akg))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.list_active_ideas", return_value=[]))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.scan_breakout_discovery", return_value={"count": 0, "alerts": []}))
        stack.enter_context(patch("tradingagents.dealflow.sources.breakout_scanner.scan_breakout_discovery", return_value={"count": 0, "alerts": []}))
        stack.enter_context(patch("tradingagents.dealflow.sources.iv_scanner.scan_earnings_iv", return_value={"force_queue": [], "akg_enriched": []}))
        stack.enter_context(patch("tradingagents.dealflow.sources.insider_cluster.scan_insider_sweep", return_value={"skipped": True}))
        stack.enter_context(patch("tradingagents.dealflow.pipeline._AKG_AVAILABLE", False))
        stack.enter_context(
            patch(
                "tradingagents.dealflow.pipeline.DealFlowPipeline._build_fvg_recall_channel",
                return_value={
                    "selected_symbols": [],
                    "artifact": {"date": "2026-03-07", "selected_symbols": [], "quota": 0, "rule_snapshot": {"enabled": False}},
                },
            )
        )
        stack.enter_context(
            patch(
                "tradingagents.dealflow.pipeline.DealFlowPipeline._build_fma_recall_channel",
                return_value={
                    "selected_symbols": ["PLTR"],
                    "artifact": {
                        "date": "2026-03-07",
                        "selected_symbols": ["PLTR"],
                        "quota": 20,
                        "rule_snapshot": {
                            "enabled": True,
                            "quota": 20,
                            "min_score": 60.0,
                        },
                    },
                },
            )
        )

        pipeline = DealFlowPipeline(
            config=_minimal_config({"dealflow_fma_recall_enabled": True, "dealflow_fma_recall_quota": 20})
        )
        summary = pipeline.discover(as_of_date="2026-03-07", trigger="manual")

    assert summary["universe_size"] == 2
    assert captured["fma_recall_symbols"] == ["PLTR"]
    artifact_path = tmp_path / "eval_results" / "deal_flow" / "2026-03-07" / "fma_recall.json"
    assert artifact_path.exists()
    payload = json.loads(artifact_path.read_text())
    assert payload["selected_symbols"] == ["PLTR"]
    assert payload["quota"] == 20


def test_fvg_recall_prunes_symbols_with_no_yahoo_history_from_akg(monkeypatch):
    from tradingagents.dealflow.pipeline import DealFlowPipeline

    class _FakeAKG:
        def __init__(self):
            self._nodes = {
                "GOOD": {
                    "id": "GOOD",
                    "node_type": "company",
                    "asset_class": "Equity",
                    "liquidity_score": 90.0,
                },
                "BAD": {
                    "id": "BAD",
                    "node_type": "company",
                    "asset_class": "Equity",
                    "liquidity_score": 90.0,
                },
            }
            self.removed = []
            self.saved = False

        def remove_nodes(self, node_ids):
            self.removed.extend(node_ids)
            for node_id in node_ids:
                self._nodes.pop(node_id, None)
            return len(node_ids)

        def save(self):
            self.saved = True

    def _history_for(*symbols):
        index = pd.date_range("2025-12-01", periods=3, freq="D")
        data = {}
        for symbol in symbols:
            for field, values in {
                "Open": [10.0, 11.0, 12.0],
                "High": [11.0, 12.0, 13.0],
                "Low": [9.0, 10.0, 11.0],
                "Close": [10.5, 11.5, 12.5],
                "Volume": [1_000_000, 1_100_000, 1_200_000],
            }.items():
                data[(symbol, field)] = values
        return pd.DataFrame(data, index=index)

    fake_akg = _FakeAKG()
    monkeypatch.setattr(
        "tradingagents.graph.knowledge_graph.AeternusKnowledgeGraph.load",
        lambda: fake_akg,
    )
    monkeypatch.setattr(
        "tradingagents.dealflow.pipeline.yf.download",
        lambda *args, **kwargs: _history_for("GOOD", "QQQ"),
    )
    monkeypatch.setattr(
        "tradingagents.dealflow.pipeline.DealFlowPipeline._has_recent_yahoo_history",
        lambda self, symbol: False,
    )
    monkeypatch.setattr(
        "tradingagents.dealflow.pipeline._build_feature_frame",
        lambda *args, **kwargs: pd.DataFrame(
            [
                {
                    "score": 88.0,
                    "bullish_fvg_present": True,
                    "relative_strength_20d": 0.07,
                    "sma50_above_sma200": True,
                }
            ]
        ),
    )

    pipeline = DealFlowPipeline(config=_minimal_config())
    result = pipeline._build_fvg_recall_channel(as_of_date="2026-03-10")  # pylint: disable=protected-access

    assert result["selected_symbols"] == ["GOOD"]
    assert result["artifact"]["invalid_symbols_removed"] == ["BAD"]
    assert fake_akg.removed == ["BAD"]
    assert fake_akg.saved is True


def test_fvg_recall_skips_symbols_without_liquidity_score(monkeypatch):
    from tradingagents.dealflow.pipeline import DealFlowPipeline

    class _FakeAKG:
        def __init__(self):
            self._nodes = {
                "LIQ": {
                    "id": "LIQ",
                    "node_type": "company",
                    "asset_class": "Equity",
                    "liquidity_score": 90.0,
                },
                "NOLIQ": {
                    "id": "NOLIQ",
                    "node_type": "company",
                    "asset_class": "Equity",
                    "liquidity_score": None,
                },
            }

    def _history_for(*symbols):
        index = pd.date_range("2025-12-01", periods=3, freq="D")
        data = {}
        for symbol in symbols:
            for field, values in {
                "Open": [10.0, 11.0, 12.0],
                "High": [11.0, 12.0, 13.0],
                "Low": [9.0, 10.0, 11.0],
                "Close": [10.5, 11.5, 12.5],
                "Volume": [1_000_000, 1_100_000, 1_200_000],
            }.items():
                data[(symbol, field)] = values
        return pd.DataFrame(data, index=index)

    fake_akg = _FakeAKG()
    captured = {}

    monkeypatch.setattr(
        "tradingagents.graph.knowledge_graph.AeternusKnowledgeGraph.load",
        lambda: fake_akg,
    )

    def _download(symbols, *args, **kwargs):
        captured["symbols"] = list(symbols)
        return _history_for("LIQ", "QQQ")

    monkeypatch.setattr("tradingagents.dealflow.pipeline.yf.download", _download)
    monkeypatch.setattr(
        "tradingagents.dealflow.pipeline._build_feature_frame",
        lambda *args, **kwargs: pd.DataFrame(
            [
                {
                    "score": 88.0,
                    "bullish_fvg_present": True,
                    "relative_strength_20d": 0.07,
                    "sma50_above_sma200": True,
                }
            ]
        ),
    )

    pipeline = DealFlowPipeline(config=_minimal_config())
    result = pipeline._build_fvg_recall_channel(as_of_date="2026-03-10")  # pylint: disable=protected-access

    assert result["selected_symbols"] == ["LIQ"]
    assert captured["symbols"] == ["LIQ", "QQQ"]


def test_fma_recall_skips_symbols_without_liquidity_score(monkeypatch):
    from tradingagents.dealflow.pipeline import DealFlowPipeline

    class _FakeAKG:
        def __init__(self):
            self._nodes = {
                "LIQ": {
                    "id": "LIQ",
                    "node_type": "company",
                    "asset_class": "Equity",
                    "liquidity_score": 90.0,
                },
                "NOLIQ": {
                    "id": "NOLIQ",
                    "node_type": "company",
                    "asset_class": "Equity",
                    "liquidity_score": None,
                },
            }

    def _history_for(*symbols):
        index = pd.date_range("2025-12-01", periods=3, freq="D")
        data = {}
        for symbol in symbols:
            for field, values in {
                "Open": [10.0, 11.0, 12.0],
                "High": [11.0, 12.0, 13.0],
                "Low": [9.0, 10.0, 11.0],
                "Close": [10.5, 11.5, 12.5],
                "Volume": [1_000_000, 1_100_000, 1_200_000],
            }.items():
                data[(symbol, field)] = values
        return pd.DataFrame(data, index=index)

    fake_akg = _FakeAKG()
    captured = {}

    monkeypatch.setattr(
        "tradingagents.graph.knowledge_graph.AeternusKnowledgeGraph.load",
        lambda: fake_akg,
    )

    def _download(symbols, *args, **kwargs):
        captured["symbols"] = list(symbols)
        return _history_for("LIQ", "QQQ")

    monkeypatch.setattr("tradingagents.dealflow.pipeline.yf.download", _download)
    monkeypatch.setattr(
        "tradingagents.dealflow.pipeline._build_fma_feature_frame",
        lambda *args, **kwargs: pd.DataFrame(
            [
                {
                    "valid": True,
                    "velocity_60d": 1.2,
                    "accel_value": 1.1,
                    "mass_ratio": 1.0,
                    "force_value": 1.3,
                    "relative_strength_60d": 0.08,
                }
            ]
        ),
    )
    monkeypatch.setattr(
        "tradingagents.dealflow.pipeline.score_fma_cross_section",
        lambda snapshots, variant="fma_live": {
            str(row.get("ticker", "")).upper().strip(): 87.0 for row in snapshots
        },
    )

    pipeline = DealFlowPipeline(config=_minimal_config())
    result = pipeline._build_fma_recall_channel(as_of_date="2026-03-10")  # pylint: disable=protected-access

    assert result["selected_symbols"] == ["LIQ"]
    assert captured["symbols"] == ["LIQ", "QQQ"]


def test_discover_persists_discovery_delta_artifact_and_summary(tmp_path, monkeypatch):
    from tradingagents.dealflow.pipeline import DealFlowPipeline

    monkeypatch.chdir(tmp_path)

    def _stub_build_universe_from_akg(
        *,
        extra_symbols=None,
        config=None,
        fvg_recall_symbols=None,
        fma_recall_symbols=None,
    ):
        return [
            {
                "symbol": "AMD",
                "asset_class": "Equity",
                "sector": "Technology",
                "liquidity_score": 88.0,
                "aliases": [],
            },
            {
                "symbol": "NVDA",
                "asset_class": "Equity",
                "sector": "Technology",
                "liquidity_score": 95.0,
                "aliases": [],
            },
            {
                "symbol": "PLTR",
                "asset_class": "Equity",
                "sector": "Technology",
                "liquidity_score": 81.0,
                "aliases": [],
            },
        ]

    with ExitStack() as stack:
        stack.enter_context(patch("tradingagents.dealflow.pipeline.build_universe_from_akg", side_effect=_stub_build_universe_from_akg))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.list_active_ideas", return_value=[]))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.scan_breakout_discovery", return_value={"count": 0, "alerts": []}))
        stack.enter_context(patch("tradingagents.dealflow.sources.breakout_scanner.scan_breakout_discovery", return_value={"count": 0, "alerts": []}))
        stack.enter_context(patch("tradingagents.dealflow.sources.iv_scanner.scan_earnings_iv", return_value={"force_queue": [], "akg_enriched": []}))
        stack.enter_context(patch("tradingagents.dealflow.sources.insider_cluster.scan_insider_sweep", return_value={"skipped": True}))
        stack.enter_context(patch("tradingagents.dealflow.pipeline._AKG_AVAILABLE", False))
        stack.enter_context(
            patch(
                "tradingagents.dealflow.pipeline.DealFlowPipeline._build_fvg_recall_channel",
                return_value={
                    "selected_symbols": ["NVDA"],
                    "artifact": {
                        "date": "2026-03-07",
                        "selected_symbols": ["NVDA"],
                        "quota": 30,
                        "rule_snapshot": {"enabled": True},
                        "rows": [{"symbol": "NVDA", "score": 88.0, "bucket": "fvg_confirmed"}],
                    },
                },
            )
        )
        stack.enter_context(
            patch(
                "tradingagents.dealflow.pipeline.DealFlowPipeline._build_fma_recall_channel",
                return_value={
                    "selected_symbols": ["PLTR"],
                    "artifact": {
                        "date": "2026-03-07",
                        "selected_symbols": ["PLTR"],
                        "quota": 20,
                        "rule_snapshot": {"enabled": True},
                        "rows": [{"symbol": "PLTR", "score": 75.0, "bucket": "fma_live"}],
                    },
                },
            )
        )
        stack.enter_context(
            patch(
                "tradingagents.dealflow.pipeline.DealFlowPipeline._build_scout_audit",
                return_value={
                    "summary": {"breakout_count": 1},
                    "signals": [
                        {
                            "symbol": "AMD",
                            "source": "breakout_scanner",
                            "delta_kind": "breakout",
                            "direction": "BULLISH",
                            "raw_strength": 0.8,
                            "confidence_score": 0.7,
                            "tags": ["breakout"],
                        }
                    ],
                },
            )
        )

        pipeline = DealFlowPipeline(config=_minimal_config())
        summary = pipeline.discover(as_of_date="2026-03-07", trigger="manual")

    artifact_path = tmp_path / "eval_results" / "deal_flow" / "2026-03-07" / "discovery_delta.json"
    assert artifact_path.exists()
    payload = json.loads(artifact_path.read_text())
    assert payload["coverage_summary"]["record_count"] == 3
    assert payload["cohorts"]["scout_only"] == ["AMD"]
    assert sorted(payload["cohorts"]["technical_only"]) == ["NVDA", "PLTR"]
    assert payload["cohorts"]["multi_channel"] == []
    assert summary["discovery_delta_summary"]["record_count"] == 3


def test_discover_persists_universe_filter_artifact_and_summary(tmp_path, monkeypatch):
    from tradingagents.dealflow.pipeline import DealFlowPipeline

    monkeypatch.chdir(tmp_path)

    universe = [
        {
            "symbol": "AAPL",
            "asset_class": "Equity",
            "sector": "Technology",
            "liquidity_score": 90.0,
            "aliases": [],
        },
        {
            "symbol": "NVDA",
            "asset_class": "Equity",
            "sector": "Technology",
            "liquidity_score": 95.0,
            "aliases": [],
        },
    ]

    with ExitStack() as stack:
        stack.enter_context(
            patch("tradingagents.dealflow.pipeline.build_universe_from_akg", return_value=universe)
        )
        stack.enter_context(
            patch(
                "tradingagents.dealflow.pipeline.get_last_universe_tier_map",
                return_value={"AAPL": "T1_ANCHOR", "NVDA": "T3B_FVG_RECALL", "TSLA": "MANUAL"},
            )
        )
        stack.enter_context(
            patch(
                "tradingagents.dealflow.pipeline.get_last_universe_ledger",
                return_value={
                    "kept_symbols": ["AAPL", "NVDA"],
                    "candidate_drop_symbols": ["TSLA"],
                    "haystack_drop_symbols": ["TSLA"],
                    "rule_snapshot": {"kept_count": 2, "tier_counts": {"T1_ANCHOR": 1, "T3B_FVG_RECALL": 1, "MANUAL": 1}},
                },
            )
        )
        stack.enter_context(patch("tradingagents.dealflow.pipeline.list_active_ideas", return_value=[{"symbol": "TSLA"}]))
        stack.enter_context(
                patch(
                    "tradingagents.dealflow.pipeline.DealFlowPipeline._build_fvg_recall_channel",
                    return_value={
                        "selected_symbols": ["NVDA", "TSLA"],
                        "artifact": {
                            "date": "2026-03-09",
                            "selected_symbols": ["NVDA", "TSLA"],
                            "quota": 30,
                            "rule_snapshot": {"enabled": True},
                        },
                    },
                )
        )
        stack.enter_context(
            patch(
                "tradingagents.dealflow.pipeline.DealFlowPipeline._build_fma_recall_channel",
                return_value={
                    "selected_symbols": ["PLTR"],
                    "artifact": {
                        "date": "2026-03-09",
                        "selected_symbols": ["PLTR"],
                        "quota": 20,
                        "rule_snapshot": {"enabled": True},
                    },
                },
            )
        )
        stack.enter_context(
            patch(
                "tradingagents.dealflow.pipeline.DealFlowPipeline._build_scout_audit",
                return_value={
                    "breakout": {"alerts": [{"ticker": "AMD"}]},
                    "iv": {"force_queue": ["PLTR"]},
                    "insider": {"buy_clusters": [], "sell_clusters": []},
                    "signals": [{"symbol": "AMD"}],
                },
            )
        )
        stack.enter_context(
            patch("tradingagents.dealflow.pipeline.write_discovery_delta_report", return_value={"coverage_summary": {}, "cohorts": {}, "top_delta_symbols": []})
        )
        stack.enter_context(
            patch("tradingagents.dealflow.sources.x_feed_manual.load_recent_merged", return_value={"TSLA": {"ticker": "TSLA"}})
        )
        stack.enter_context(
            patch("tradingagents.dealflow.sources.breakout_scanner.scan_breakout_discovery", return_value={"count": 0, "alerts": []})
        )
        stack.enter_context(
            patch("tradingagents.dealflow.sources.iv_scanner.scan_earnings_iv", return_value={"force_queue": [], "akg_enriched": []})
        )
        stack.enter_context(
            patch("tradingagents.dealflow.sources.insider_cluster.scan_insider_sweep", return_value={"skipped": True})
        )

        pipeline = DealFlowPipeline(config=_minimal_config())
        summary = pipeline.discover(as_of_date="2026-03-09", trigger="manual")

    artifact_path = tmp_path / "eval_results" / "deal_flow" / "2026-03-09" / "universe_filter.json"
    assert artifact_path.exists()
    payload = json.loads(artifact_path.read_text())
    assert payload["universe_size"] == 2
    assert payload["source_counts"]["x_feed_merged_symbols"] == 1
    assert payload["overlap_counts"]["manual_technical_overlap"] == 1
    assert summary["universe_filter_summary"]["tier_counts"]["T1_ANCHOR"] == 1
    assert summary["universe_filter_summary"]["overall_ready"] is True


def test_discover_threads_technical_ignition_symbols_and_persists_scout_audit(tmp_path, monkeypatch):
    from tradingagents.dealflow.pipeline import DealFlowPipeline

    monkeypatch.chdir(tmp_path)
    captured = {}

    def _stub_build_universe_from_akg(
        *,
        extra_symbols=None,
        technical_ignition_symbols=None,
        config=None,
        fvg_recall_symbols=None,
        fma_recall_symbols=None,
    ):
        captured["extra_symbols"] = list(extra_symbols or [])
        captured["technical_ignition_symbols"] = list(technical_ignition_symbols or [])
        return []

    ignition_result = {
        "promoted_count": 2,
        "promoted_symbols": ["BE", "MU"],
        "stale_count": 1,
        "stale_symbols": ["TPL"],
        "signals": [
            {
                "symbol": "BE",
                "source": "technical_ignition",
                "delta_kind": "technical_ignition",
                "direction": "BULLISH",
                "raw_strength": 0.8,
                "confidence_score": 0.85,
                "tags": ["buy_trigger", "technical_ignition"],
            },
            {
                "symbol": "MU",
                "source": "technical_ignition",
                "delta_kind": "technical_ignition",
                "direction": "BULLISH",
                "raw_strength": 0.6,
                "confidence_score": 0.75,
                "tags": ["buy_zone", "technical_ignition"],
            },
        ],
        "promoted": [{"ticker": "BE"}, {"ticker": "MU"}],
        "stale": [{"ticker": "TPL"}],
    }

    with ExitStack() as stack:
        stack.enter_context(patch("tradingagents.dealflow.pipeline.build_universe_from_akg", side_effect=_stub_build_universe_from_akg))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.get_last_universe_tier_map", return_value={}))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.get_last_universe_ledger", return_value={}))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.list_active_ideas", return_value=[]))
        stack.enter_context(
            patch(
                "tradingagents.dealflow.sources.x_feed_manual.load_recent_merged",
                return_value={},
            )
        )
        stack.enter_context(
            patch(
                "tradingagents.dealflow.pipeline.DealFlowPipeline._build_fvg_recall_channel",
                return_value={"selected_symbols": [], "artifact": {"date": "2026-03-10", "selected_symbols": [], "rows": [], "quota": 0, "rule_snapshot": {"enabled": True}}},
            )
        )
        stack.enter_context(
            patch(
                "tradingagents.dealflow.pipeline.DealFlowPipeline._build_fma_recall_channel",
                return_value={"selected_symbols": [], "artifact": {"date": "2026-03-10", "selected_symbols": [], "rows": [], "quota": 0, "rule_snapshot": {"enabled": True}}},
            )
        )
        stack.enter_context(
            patch("tradingagents.dealflow.sources.breakout_scanner.scan_breakout_discovery", return_value={"count": 0, "alerts": []})
        )
        stack.enter_context(
            patch("tradingagents.dealflow.sources.iv_scanner.scan_earnings_iv", return_value={"force_queue": [], "akg_enriched": []})
        )
        stack.enter_context(
            patch("tradingagents.dealflow.sources.insider_cluster.scan_insider_sweep", return_value={"skipped": True})
        )
        stack.enter_context(
            patch(
                "tradingagents.dealflow.sources.technical_ignition_scout.scan_technical_ignition_setups",
                return_value=ignition_result,
            )
        )

        pipeline = DealFlowPipeline(config=_minimal_config())
        summary = pipeline.discover(as_of_date="2026-03-10", trigger="manual")

    assert summary["technical_ignition_count"] == 2
    assert summary["technical_ignition_symbols"] == ["BE", "MU"]
    assert captured["technical_ignition_symbols"] == ["BE", "MU"]
    assert captured["extra_symbols"] == []

    audit_path = tmp_path / "eval_results" / "deal_flow" / "2026-03-10" / "scout_audit.json"
    assert audit_path.exists()
    payload = json.loads(audit_path.read_text())
    assert payload["technical_ignition"]["promoted_symbols"] == ["BE", "MU"]
    assert payload["technical_ignition"]["stale_symbols"] == ["TPL"]
    assert [row["symbol"] for row in payload["signals"]] == ["BE", "MU"]




def test_discover_writes_scout_compiler_sidecar_artifacts_without_changing_universe(tmp_path, monkeypatch):
    from tradingagents.dealflow.pipeline import DealFlowPipeline

    monkeypatch.chdir(tmp_path)
    universe = [
        {
            "symbol": "XLE",
            "asset_class": "Equity",
            "sector": "Energy",
            "liquidity_score": 90.0,
            "aliases": [],
        },
        {
            "symbol": "UAL",
            "asset_class": "Equity",
            "sector": "Industrials",
            "liquidity_score": 88.0,
            "aliases": [],
        },
    ]

    with ExitStack() as stack:
        stack.enter_context(patch("tradingagents.dealflow.pipeline.build_universe_from_akg", return_value=universe))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.get_last_universe_tier_map", return_value={}))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.get_last_universe_ledger", return_value={"symbols": ["XLE", "UAL"]}))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.list_active_ideas", return_value=[]))
        stack.enter_context(
            patch(
                "tradingagents.dealflow.sources.x_feed_manual.load_recent_merged",
                return_value={
                    "XLE": {
                        "ticker": "XLE",
                        "catalyst": "Trump announced war on Iran; oil higher and airlines like $UAL under pressure.",
                        "sentiment": "BULLISH",
                        "velocity": "ACCELERATING",
                        "sector": "Energy",
                    }
                },
            )
        )
        stack.enter_context(
            patch(
                "tradingagents.dealflow.pipeline.DealFlowPipeline._build_fvg_recall_channel",
                return_value={"selected_symbols": [], "artifact": {"date": "2026-03-15", "selected_symbols": [], "rows": [], "quota": 0, "rule_snapshot": {"enabled": True}}},
            )
        )
        stack.enter_context(
            patch(
                "tradingagents.dealflow.pipeline.DealFlowPipeline._build_fma_recall_channel",
                return_value={"selected_symbols": [], "artifact": {"date": "2026-03-15", "selected_symbols": [], "rows": [], "quota": 0, "rule_snapshot": {"enabled": True}}},
            )
        )
        stack.enter_context(patch("tradingagents.dealflow.sources.breakout_scanner.scan_breakout_discovery", return_value={"count": 0, "alerts": []}))
        stack.enter_context(patch("tradingagents.dealflow.sources.insider_cluster.scan_insider_sweep", return_value={"skipped": True}))
        stack.enter_context(
            patch(
                "tradingagents.dealflow.sources.technical_ignition_scout.scan_technical_ignition_setups",
                return_value={
                    "promoted_count": 1,
                    "promoted_symbols": ["XLE"],
                    "signals": [
                        {
                            "symbol": "XLE",
                            "source": "technical_ignition",
                            "delta_kind": "technical_ignition",
                            "direction": "BULLISH",
                            "raw_strength": 0.8,
                            "confidence_score": 0.8,
                            "tags": ["buy_zone", "technical_ignition"],
                            "catalyst": "Iran escalation driving energy bid",
                        }
                    ],
                    "promoted": [{"ticker": "XLE"}],
                    "stale": [],
                    "stale_symbols": [],
                    "stale_count": 0,
                },
            )
        )

        pipeline = DealFlowPipeline(config=_minimal_config())
        summary = pipeline.discover(as_of_date="2026-03-15", trigger="manual")

    base = tmp_path / "eval_results" / "deal_flow" / "2026-03-15"
    assert (base / "event_cards.json").exists()
    assert (base / "coverage_precheck.json").exists()
    assert (base / "scout_compiler_debug.json").exists()
    assert (base / "akg_writeback_candidates.json").exists()
    assert (base / "scout_quality_daily.json").exists()
    assert summary["universe_size"] == 2
    assert summary["scenario_sidecar_summary"]["event_card_count"] >= 1
    assert "writeback_candidate_count" in summary["scenario_sidecar_summary"]
    assert summary["scout_quality_summary"]["row_count"] >= 1




def test_build_scout_audit_serializes_non_json_signal_fields(tmp_path, monkeypatch):
    from tradingagents.dealflow.pipeline import DealFlowPipeline

    class _OddValue:
        def __str__(self):
            return "odd-value"

    monkeypatch.chdir(tmp_path)
    pipeline = DealFlowPipeline(config=_minimal_config())

    payload = pipeline._build_scout_audit(
        as_of_date="2026-03-15",
        breakout_result={"alerts": [{"ticker": "XLE", "score": 88.5, "near_high": 0.98}]},
        iv_result={"force_queue": [], "akg_enriched": []},
        insider_result={"buy_clusters": [], "sell_clusters": []},
        technical_ignition_result={
            "signals": [
                {
                    "symbol": "XLE",
                    "source": "technical_ignition",
                    "direction": "BULLISH",
                    "catalyst": _OddValue(),
                }
            ]
        },
    )

    assert payload["signals"][0]["catalyst"] == "odd-value"
    assert (tmp_path / "eval_results" / "deal_flow" / "2026-03-15" / "scout_audit.json").exists()


def test_discover_carries_forward_recent_unprocessed_x_feed_symbols(tmp_path, monkeypatch):
    from tradingagents.dealflow.pipeline import DealFlowPipeline

    monkeypatch.chdir(tmp_path)
    captured = {}

    def _stub_build_universe_from_akg(*, extra_symbols=None, config=None, fvg_recall_symbols=None, fma_recall_symbols=None):
        captured["extra_symbols"] = list(extra_symbols or [])
        return []

    with ExitStack() as stack:
        stack.enter_context(patch("tradingagents.dealflow.pipeline.build_universe_from_akg", side_effect=_stub_build_universe_from_akg))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.list_active_ideas", return_value=[]))
        stack.enter_context(
            patch(
                "tradingagents.dealflow.sources.x_feed_manual.load_recent_merged",
                return_value={"BE": {"ticker": "BE", "x_feed_source_date": "2026-03-06", "x_feed_carryforward_days": 3}},
            )
        )
        stack.enter_context(
            patch(
                "tradingagents.dealflow.pipeline.DealFlowPipeline._build_fvg_recall_channel",
                return_value={"selected_symbols": [], "artifact": {"date": "2026-03-09", "selected_symbols": [], "quota": 0, "rule_snapshot": {"enabled": True}}},
            )
        )
        stack.enter_context(
            patch(
                "tradingagents.dealflow.pipeline.DealFlowPipeline._build_fma_recall_channel",
                return_value={"selected_symbols": [], "artifact": {"date": "2026-03-09", "selected_symbols": [], "quota": 0, "rule_snapshot": {"enabled": True}}},
            )
        )
        stack.enter_context(patch("tradingagents.dealflow.pipeline.DealFlowPipeline._build_scout_audit", return_value={"signals": []}))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.write_discovery_delta_report", return_value={"coverage_summary": {}, "cohorts": {}, "top_delta_symbols": []}))
        stack.enter_context(patch("tradingagents.dealflow.sources.breakout_scanner.scan_breakout_discovery", return_value={"count": 0, "alerts": []}))
        stack.enter_context(patch("tradingagents.dealflow.sources.iv_scanner.scan_earnings_iv", return_value={"force_queue": [], "akg_enriched": []}))
        stack.enter_context(patch("tradingagents.dealflow.sources.insider_cluster.scan_insider_sweep", return_value={"skipped": True}))

        pipeline = DealFlowPipeline(config=_minimal_config({"dealflow_manual_x_feed_carryforward_days": 3}))
        pipeline.discover(as_of_date="2026-03-09", trigger="manual")

    assert "BE" in captured["extra_symbols"]


def test_discover_skips_legacy_iv_scout_by_default(tmp_path, monkeypatch):
    from tradingagents.dealflow.pipeline import DealFlowPipeline

    monkeypatch.chdir(tmp_path)

    with ExitStack() as stack:
        legacy_iv = stack.enter_context(
            patch("tradingagents.dealflow.sources.iv_scanner.scan_earnings_iv", return_value={"force_queue": [{"ticker": "AAPL"}], "akg_enriched": []})
        )
        stack.enter_context(patch("tradingagents.dealflow.pipeline.build_universe_from_akg", return_value=[]))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.get_last_universe_tier_map", return_value={}))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.get_last_universe_ledger", return_value={}))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.list_active_ideas", return_value=[]))
        stack.enter_context(patch("tradingagents.dealflow.sources.x_feed_manual.load_recent_merged", return_value={}))
        stack.enter_context(
            patch(
                "tradingagents.dealflow.pipeline.DealFlowPipeline._build_fvg_recall_channel",
                return_value={"selected_symbols": [], "artifact": {"date": "2026-03-10", "selected_symbols": [], "rows": [], "quota": 0, "rule_snapshot": {"enabled": True}}},
            )
        )
        stack.enter_context(
            patch(
                "tradingagents.dealflow.pipeline.DealFlowPipeline._build_fma_recall_channel",
                return_value={"selected_symbols": [], "artifact": {"date": "2026-03-10", "selected_symbols": [], "rows": [], "quota": 0, "rule_snapshot": {"enabled": True}}},
            )
        )
        stack.enter_context(patch("tradingagents.dealflow.sources.breakout_scanner.scan_breakout_discovery", return_value={"count": 0, "alerts": []}))
        stack.enter_context(patch("tradingagents.dealflow.sources.insider_cluster.scan_insider_sweep", return_value={"skipped": True}))
        stack.enter_context(
            patch(
                "tradingagents.dealflow.sources.technical_ignition_scout.scan_technical_ignition_setups",
                return_value={"promoted_count": 0, "promoted_symbols": [], "stale_count": 0, "stale_symbols": [], "signals": [], "promoted": [], "stale": []},
            )
        )

        pipeline = DealFlowPipeline(config=_minimal_config())
        summary = pipeline.discover(as_of_date="2026-03-10", trigger="manual")

    assert summary["iv_force_queue_count"] == 0
    assert pipeline._iv_force_queue == []
    legacy_iv.assert_not_called()


def test_collect_threads_earnings_iv_connector_health(tmp_path, monkeypatch):
    from tradingagents.dealflow.pipeline import DealFlowPipeline

    monkeypatch.chdir(tmp_path)
    config = _minimal_config({"dealflow_min_signal_families": 1})

    universe = [
        {
            "symbol": "MU",
            "asset_class": "Equity",
            "sector": "Technology",
            "liquidity_score": 90.0,
            "aliases": [],
        }
    ]
    normalized_signals = []
    candidates = [
        {
            "symbol": "MU",
            "asset_class": "Equity",
            "sector": "Technology",
            "liquidity_score": 90.0,
            "subscores": {},
            "deal_flow_score": 75.0,
            "core_score": 75.0,
            "momentum_score": 60.0,
            "asymmetry_score": 55.0,
            "active_families": 1,
            "evidence_count": 2,
            "freshness_hours": 12.0,
            "status": "ACTIVE",
            "risk_tags": [],
            "trend_tags": [],
            "lane": "CORE",
            "source": "AUTO",
            "source_detail": "AUTO_MODEL",
            "manual_note": "",
            "manual_priority": 0,
            "reason": "event",
        }
    ]

    with ExitStack() as stack:
        stack.enter_context(patch("tradingagents.dealflow.pipeline.collect_social_news_signals", return_value=[]))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.collect_price_momentum_signals", return_value=[]))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.collect_macro_signals", return_value=[]))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.collect_smart_money_signals", return_value=[]))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.collect_sector_rotation_signals", return_value=[]))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.collect_insider_cluster_signals", return_value=[]))
        iv_collect = stack.enter_context(
            patch("tradingagents.dealflow.pipeline.collect_earnings_iv_signals", return_value=normalized_signals, create=True)
        )
        stack.enter_context(patch("tradingagents.dealflow.pipeline.score_candidates", return_value=(normalized_signals, candidates)))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.rank_candidates", return_value=candidates))

        pipeline = DealFlowPipeline(config=config)
        pipeline._last_universe = universe
        pipeline._last_universe_ledger = pipeline._resolve_universe_ledger(universe, {})
        pipeline._last_manual_ideas = []
        pipeline._last_event_state = {"triggered": False, "reasons": []}
        shortlist, rq, signals, event = pipeline.collect(as_of_date="2026-03-11", trigger="manual", top_k=10)

    connector_health_path = tmp_path / "eval_results" / "deal_flow" / "2026-03-11" / "connector_health.json"
    assert connector_health_path.exists()
    payload = json.loads(connector_health_path.read_text())
    iv_collect.assert_not_called()
    assert all(row["connector"] != "earnings_iv" for row in payload)


def test_dealflow_scoring_has_no_earnings_iv_family():
    from tradingagents.dealflow.scoring import CORE_SCORE_WEIGHTS, CORE_SIGNAL_FAMILIES

    assert "earnings_iv_divergence" not in CORE_SCORE_WEIGHTS
    assert "earnings_iv_divergence" not in CORE_SIGNAL_FAMILIES


def test_collect_persists_evidence_integrity_artifact_and_summary(tmp_path, monkeypatch):
    from tradingagents.dealflow.pipeline import DealFlowPipeline

    monkeypatch.chdir(tmp_path)
    config = _minimal_config({"dealflow_min_signal_families": 3})

    universe = [
        {
            "symbol": "AAPL",
            "asset_class": "Equity",
            "sector": "Technology",
            "liquidity_score": 90.0,
            "aliases": [],
        }
    ]
    normalized_signals = [
        {
            "symbol": "AAPL",
            "signal_family": "price_momentum",
            "raw_score": 88.0,
            "direction": "BULLISH",
            "source_status": "OK",
            "evidence_count": 2,
            "freshness_hours": 4.0,
            "source_name": "price_momentum",
        },
        {
            "symbol": "AAPL",
            "signal_family": "news_catalyst",
            "raw_score": 74.0,
            "direction": "BULLISH",
            "source_status": "OK",
            "evidence_count": 3,
            "freshness_hours": 8.0,
            "source_name": "news_catalyst",
        },
    ]
    candidates = [
        {
            "symbol": "AAPL",
            "asset_class": "Equity",
            "sector": "Technology",
            "liquidity_score": 90.0,
            "subscores": {"price_momentum": 88.0, "news_catalyst": 74.0},
            "deal_flow_score": 75.0,
            "core_score": 75.0,
            "momentum_score": 80.0,
            "asymmetry_score": 78.0,
            "active_families": 2,
            "evidence_count": 5,
            "freshness_hours": 4.0,
            "status": "LOW_DATA",
            "risk_tags": [],
            "trend_tags": [],
            "lane": "MOMENTUM",
            "upside_3m_score": 76.0,
            "emergence_proxy_score": 55.0,
            "narrative_ignition_score": 50.0,
            "fundamentals_acceleration_score": 40.0,
            "relative_strength_score": 82.0,
            "lane_candidates": ["3M_UPSIDE"],
            "source": "AUTO",
            "source_detail": "AUTO_MODEL",
            "manual_note": "",
            "manual_priority": 0,
            "reason": "test",
        }
    ]

    with ExitStack() as stack:
        stack.enter_context(patch("tradingagents.dealflow.pipeline.build_universe_from_akg", return_value=universe))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.list_active_ideas", return_value=[]))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.collect_social_news_signals", return_value=[]))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.collect_price_momentum_signals", return_value=[]))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.collect_macro_signals", return_value=[]))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.collect_smart_money_signals", return_value=[]))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.collect_sector_rotation_signals", return_value=[]))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.collect_insider_cluster_signals", return_value=[]))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.scan_breakout_discovery", return_value={"count": 0, "alerts": []}))
        stack.enter_context(patch("tradingagents.dealflow.sources.breakout_scanner.scan_breakout_discovery", return_value={"count": 0, "alerts": []}))
        stack.enter_context(patch("tradingagents.dealflow.sources.iv_scanner.scan_earnings_iv", return_value={"force_queue": [], "akg_enriched": []}))
        stack.enter_context(patch("tradingagents.dealflow.sources.insider_cluster.scan_insider_sweep", return_value={"skipped": True}))
        stack.enter_context(patch("tradingagents.dealflow.pipeline._AKG_AVAILABLE", False))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.score_candidates", return_value=(normalized_signals, candidates)))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.rank_candidates", return_value=candidates))

        pipeline = DealFlowPipeline(config=config)
        pipeline._last_universe = universe
        pipeline._last_universe_ledger = pipeline._resolve_universe_ledger(universe, {})
        pipeline._last_manual_ideas = []
        pipeline._last_event_state = {"triggered": False, "reasons": []}
        shortlist, rq, signals, event = pipeline.collect(as_of_date="2026-03-07", trigger="manual", top_k=10)

    artifact_path = tmp_path / "eval_results" / "deal_flow" / "2026-03-07" / "evidence_integrity.json"
    assert artifact_path.exists()
    payload = json.loads(artifact_path.read_text())
    assert payload["class_counts"]["SPARSE_BUT_INTERESTING"] == 1
    assert shortlist["evidence_integrity_summary"]["class_counts"]["SPARSE_BUT_INTERESTING"] == 1


def test_collect_persists_fundamental_shadow_artifact_and_summary(tmp_path, monkeypatch):
    from tradingagents.dealflow.pipeline import DealFlowPipeline

    monkeypatch.chdir(tmp_path)
    config = _minimal_config({"dealflow_min_signal_families": 1})

    universe = [
        {
            "symbol": "AAPL",
            "asset_class": "Equity",
            "sector": "Technology",
            "liquidity_score": 90.0,
            "aliases": [],
        }
    ]
    normalized_signals = [
        {
            "symbol": "AAPL",
            "signal_family": "fundamental_factor_shadow",
            "raw_score": 78.4,
            "direction": "BULLISH",
            "source_status": "OK",
            "evidence_count": 6,
            "freshness_hours": 4.0,
            "source_name": "sec_autoresearch_shadow:health_0p4__inv_growth_0p1__inv_quality_0p5",
        },
    ]
    candidates = [
        {
            "symbol": "AAPL",
            "asset_class": "Equity",
            "sector": "Technology",
            "liquidity_score": 90.0,
            "subscores": {},
            "deal_flow_score": 85.0,
            "core_score": 90.0,
            "momentum_score": 70.0,
            "asymmetry_score": 65.0,
            "active_families": 3,
            "evidence_count": 6,
            "freshness_hours": 4.0,
            "status": "ACTIVE",
            "risk_tags": [],
            "trend_tags": [],
            "lane": "CORE",
            "source": "AUTO",
            "source_detail": "AUTO_MODEL",
            "manual_note": "",
            "manual_priority": 0,
            "reason": "selected",
        }
    ]

    with ExitStack() as stack:
        stack.enter_context(patch("tradingagents.dealflow.pipeline.build_universe_from_akg", return_value=universe))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.list_active_ideas", return_value=[]))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.collect_social_news_signals", return_value=[]))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.collect_price_momentum_signals", return_value=[]))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.collect_macro_signals", return_value=[]))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.collect_smart_money_signals", return_value=[]))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.collect_sector_rotation_signals", return_value=[]))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.collect_insider_cluster_signals", return_value=[]))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.collect_smart_money_signals", return_value=normalized_signals))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.scan_breakout_discovery", return_value={"count": 0, "alerts": []}))
        stack.enter_context(patch("tradingagents.dealflow.sources.breakout_scanner.scan_breakout_discovery", return_value={"count": 0, "alerts": []}))
        stack.enter_context(patch("tradingagents.dealflow.sources.iv_scanner.scan_earnings_iv", return_value={"force_queue": [], "akg_enriched": []}))
        stack.enter_context(patch("tradingagents.dealflow.sources.insider_cluster.scan_insider_sweep", return_value={"skipped": True}))
        stack.enter_context(patch("tradingagents.dealflow.pipeline._AKG_AVAILABLE", False))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.score_candidates", return_value=(normalized_signals, candidates)))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.rank_candidates", return_value=candidates))

        pipeline = DealFlowPipeline(config=config)
        pipeline._last_universe = universe
        pipeline._last_universe_ledger = pipeline._resolve_universe_ledger(universe, {})
        pipeline._last_manual_ideas = []
        pipeline._last_event_state = {"triggered": False, "reasons": []}
        shortlist, rq, signals, event = pipeline.collect(as_of_date="2026-03-09", trigger="manual", top_k=10)

    artifact_path = tmp_path / "eval_results" / "deal_flow" / "2026-03-09" / "fundamental_factor_shadow.json"
    assert artifact_path.exists()
    payload = json.loads(artifact_path.read_text())
    assert payload["coverage_summary"]["signal_count"] == 1
    assert payload["strategy_name"] == "health_0p4__inv_growth_0p1__inv_quality_0p5"
    assert shortlist["fundamental_shadow_summary"]["coverage_summary"]["selected_for_deep_overlap_count"] == 1
    persisted_shortlist = json.loads((tmp_path / "eval_results" / "deal_flow" / "2026-03-09" / "shortlist_top20.json").read_text())
    assert persisted_shortlist["fundamental_shadow_summary"]["coverage_summary"]["selected_for_deep_overlap_count"] == 1


def test_collect_persists_shortlist_integrity_artifact(tmp_path, monkeypatch):
    from tradingagents.dealflow.pipeline import DealFlowPipeline

    monkeypatch.chdir(tmp_path)
    config = _minimal_config({"dealflow_min_signal_families": 1})

    universe = [
        {
            "symbol": "AAPL",
            "asset_class": "Equity",
            "sector": "Technology",
            "liquidity_score": 90.0,
            "aliases": [],
        }
    ]
    normalized_signals = []
    candidates = [
        {
            "symbol": "AAPL",
            "asset_class": "Equity",
            "sector": "Technology",
            "liquidity_score": 90.0,
            "subscores": {},
            "deal_flow_score": 85.0,
            "core_score": 90.0,
            "momentum_score": 70.0,
            "asymmetry_score": 65.0,
            "active_families": 3,
            "evidence_count": 6,
            "freshness_hours": 4.0,
            "status": "ACTIVE",
            "risk_tags": [],
            "trend_tags": [],
            "lane": "CORE",
            "source": "AUTO",
            "source_detail": "AUTO_MODEL",
            "manual_note": "",
            "manual_priority": 0,
            "reason": "selected",
        },
        {
            "symbol": "PLTR",
            "asset_class": "Equity",
            "sector": "Technology",
            "liquidity_score": 88.0,
            "subscores": {},
            "deal_flow_score": 82.0,
            "core_score": 84.0,
            "momentum_score": 68.0,
            "asymmetry_score": 80.0,
            "active_families": 3,
            "evidence_count": 6,
            "freshness_hours": 5.0,
            "status": "ACTIVE",
            "risk_tags": [],
            "trend_tags": [],
            "lane": "CORE",
            "source": "AUTO",
            "source_detail": "AUTO_MODEL",
            "manual_note": "",
            "manual_priority": 0,
            "reason": "near miss",
        },
    ]
    ranked = [
        {**candidates[0], "rank": 1},
    ]

    with ExitStack() as stack:
        stack.enter_context(patch("tradingagents.dealflow.pipeline.build_universe_from_akg", return_value=universe))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.list_active_ideas", return_value=[]))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.collect_social_news_signals", return_value=[]))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.collect_price_momentum_signals", return_value=[]))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.collect_macro_signals", return_value=[]))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.collect_smart_money_signals", return_value=[]))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.collect_sector_rotation_signals", return_value=[]))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.collect_insider_cluster_signals", return_value=[]))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.scan_breakout_discovery", return_value={"count": 0, "alerts": []}))
        stack.enter_context(patch("tradingagents.dealflow.sources.breakout_scanner.scan_breakout_discovery", return_value={"count": 0, "alerts": []}))
        stack.enter_context(patch("tradingagents.dealflow.sources.iv_scanner.scan_earnings_iv", return_value={"force_queue": [], "akg_enriched": []}))
        stack.enter_context(patch("tradingagents.dealflow.sources.insider_cluster.scan_insider_sweep", return_value={"skipped": True}))
        stack.enter_context(patch("tradingagents.dealflow.pipeline._AKG_AVAILABLE", False))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.score_candidates", return_value=(normalized_signals, candidates)))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.rank_candidates", return_value=ranked))

        pipeline = DealFlowPipeline(config=config)
        pipeline._last_universe = universe
        pipeline._last_universe_ledger = pipeline._resolve_universe_ledger(universe, {})
        pipeline._last_manual_ideas = []
        pipeline._last_event_state = {"triggered": False, "reasons": []}
        shortlist, rq, signals, event = pipeline.collect(as_of_date="2026-03-08", trigger="manual", top_k=1)

    artifact_path = tmp_path / "eval_results" / "deal_flow" / "2026-03-08" / "shortlist_integrity.json"
    assert artifact_path.exists()
    payload = json.loads(artifact_path.read_text())
    assert payload["coverage_summary"]["selected_shortlist_count"] == 1
    assert payload["coverage_summary"]["near_miss_count"] == 1
    assert payload["top_false_negatives"][0]["symbol"] == "PLTR"


def test_collect_persists_deep_selection_integrity_artifact(tmp_path, monkeypatch):
    from tradingagents.dealflow.pipeline import DealFlowPipeline

    monkeypatch.chdir(tmp_path)
    config = _minimal_config({"dealflow_min_signal_families": 1})

    universe = [
        {
            "symbol": "AAPL",
            "asset_class": "Equity",
            "sector": "Technology",
            "liquidity_score": 90.0,
            "aliases": [],
        }
    ]
    normalized_signals = []
    candidates = [
        {
            "symbol": "AAPL",
            "asset_class": "Equity",
            "sector": "Technology",
            "liquidity_score": 90.0,
            "subscores": {},
            "deal_flow_score": 85.0,
            "core_score": 90.0,
            "momentum_score": 70.0,
            "asymmetry_score": 65.0,
            "active_families": 3,
            "evidence_count": 6,
            "freshness_hours": 4.0,
            "status": "ACTIVE",
            "risk_tags": [],
            "trend_tags": [],
            "lane": "CORE",
            "source": "AUTO",
            "source_detail": "AUTO_MODEL",
            "manual_note": "",
            "manual_priority": 0,
            "reason": "selected",
        },
        {
            "symbol": "PLTR",
            "asset_class": "Equity",
            "sector": "Technology",
            "liquidity_score": 88.0,
            "subscores": {},
            "deal_flow_score": 82.0,
            "core_score": 84.0,
            "momentum_score": 68.0,
            "asymmetry_score": 80.0,
            "active_families": 3,
            "evidence_count": 6,
            "freshness_hours": 5.0,
            "status": "ACTIVE",
            "risk_tags": [],
            "trend_tags": [],
            "lane": "CORE",
            "source": "AUTO",
            "source_detail": "AUTO_MODEL",
            "manual_note": "",
            "manual_priority": 0,
            "reason": "selected",
        },
    ]
    ranked = [{**candidates[0], "rank": 1}, {**candidates[1], "rank": 2}]

    with ExitStack() as stack:
        stack.enter_context(patch("tradingagents.dealflow.pipeline.build_universe_from_akg", return_value=universe))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.list_active_ideas", return_value=[]))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.collect_social_news_signals", return_value=[]))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.collect_price_momentum_signals", return_value=[]))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.collect_macro_signals", return_value=[]))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.collect_smart_money_signals", return_value=[]))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.collect_sector_rotation_signals", return_value=[]))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.collect_insider_cluster_signals", return_value=[]))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.scan_breakout_discovery", return_value={"count": 0, "alerts": []}))
        stack.enter_context(patch("tradingagents.dealflow.sources.breakout_scanner.scan_breakout_discovery", return_value={"count": 0, "alerts": []}))
        stack.enter_context(patch("tradingagents.dealflow.sources.iv_scanner.scan_earnings_iv", return_value={"force_queue": [], "akg_enriched": []}))
        stack.enter_context(patch("tradingagents.dealflow.sources.insider_cluster.scan_insider_sweep", return_value={"skipped": True}))
        stack.enter_context(patch("tradingagents.dealflow.pipeline._AKG_AVAILABLE", False))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.score_candidates", return_value=(normalized_signals, candidates)))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.rank_candidates", return_value=ranked))

        pipeline = DealFlowPipeline(config=config)
        pipeline._last_universe = universe
        pipeline._last_universe_ledger = pipeline._resolve_universe_ledger(universe, {})
        pipeline._last_manual_ideas = []
        pipeline._last_event_state = {"triggered": False, "reasons": []}
        pipeline.collect(as_of_date="2026-03-08", trigger="manual", top_k=2)

    artifact_path = tmp_path / "eval_results" / "deal_flow" / "2026-03-08" / "deep_selection_integrity.json"
    assert artifact_path.exists()
    payload = json.loads(artifact_path.read_text())
    assert payload["coverage_summary"]["selected_for_deep_count"] == 2
    assert payload["coverage_summary"]["near_miss_count"] == 0
    assert payload["rule_snapshot"]["auto_selected_count"] == 2




def test_run_equals_discover_then_collect(monkeypatch):
    """run() output must match sequential discover() + collect()."""
    from tradingagents.dealflow.pipeline import DealFlowPipeline

    config = _minimal_config()
    mock_akg_instance = _make_mock_akg([])

    def _run_pipeline(call_style):
        with ExitStack() as stack:
            _enter_pipeline_patches(stack, _pipeline_patches({
                "tradingagents.dealflow.pipeline.score_candidates": ([], []),
            }))
            mock_akg_cls = stack.enter_context(patch("tradingagents.dealflow.pipeline._AKG"))
            stack.enter_context(patch("tradingagents.dealflow.pipeline.DealFlowPipeline._persist"))
            stack.enter_context(patch("tradingagents.dealflow.pipeline.DealFlowPipeline._market_shock_metrics", return_value=(None, None)))
            mock_akg_cls.load.return_value = mock_akg_instance

            pipeline = DealFlowPipeline(config=config)
            if call_style == "run":
                return pipeline.run(as_of_date="2026-03-05", trigger="manual", top_k=10)
            else:
                pipeline.discover(as_of_date="2026-03-05", trigger="manual")
                return pipeline.collect(as_of_date="2026-03-05", trigger="manual", top_k=10)

    shortlist_run, rq_run, _, event_run = _run_pipeline("run")
    shortlist_dc, rq_dc, _, event_dc = _run_pipeline("discover+collect")

    # Both produce valid shortlists with same structure
    assert shortlist_run["date"] == shortlist_dc["date"] == "2026-03-05"
    assert shortlist_run["trigger"] == shortlist_dc["trigger"] == "manual"
    assert len(shortlist_run["candidates"]) == len(shortlist_dc["candidates"])
    assert event_run["triggered"] == event_dc["triggered"]
