import json
from pathlib import Path


def test_event_card_contract_requires_expected_fields():
    from tradingagents.dealflow.scenario_contracts import REQUIRED_EVENT_CARD_FIELDS, validate_event_card

    card = {
        "event_card_id": "evt_1",
        "date": "2026-03-15",
        "title": "Iran escalation drives oil cluster",
        "event_type": "geopolitical_supply_shock",
        "summary": "Cross-scout event.",
        "source_bundle": ["x_feed", "macro"],
        "source_records": [],
        "direct_entities": [{"entity_type": "ticker", "entity_id": "XLE", "label": "XLE"}],
        "second_order_entities": [],
        "channels": ["oil", "risk_off"],
        "expected_direction": {"XLE": "up"},
        "confidence": 0.8,
        "urgency": "immediate",
        "time_horizon": "1d_to_5d",
        "portfolio_relevance": "medium",
        "matched_holdings": [],
        "matched_universe_symbols": ["XLE"],
        "coverage_dimensions": ["social", "macro"],
        "missing_dimensions": ["portfolio"],
        "followup_questions": ["Do we need a hedge?"],
    }

    assert set(REQUIRED_EVENT_CARD_FIELDS).issubset(card.keys())
    assert validate_event_card(card) == []


def test_event_card_contract_reports_missing_required_fields():
    from tradingagents.dealflow.scenario_contracts import validate_event_card

    missing = validate_event_card({"event_card_id": "evt_1", "date": "2026-03-15"})

    assert "title" in missing
    assert "event_type" in missing


def test_compile_scout_events_merges_multi_source_oil_narrative():
    from tradingagents.dealflow.scout_compiler import compile_scout_events

    scout_audit = {
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
        "insider": {"buy_clusters": [], "sell_clusters": []},
        "breakout": {"alerts": []},
    }
    discovery_delta = {
        "signals": [
            {
                "symbol": "UAL",
                "source": "fvg_recall",
                "channel_type": "technical_recall",
                "delta_kind": "fvg_recall",
                "direction": "BEARISH",
                "raw_strength": 0.5,
                "confidence_score": 0.6,
                "tags": ["oil"],
            }
        ]
    }
    x_feed_merged = {
        "XLE": {
            "ticker": "XLE",
            "catalyst": "Trump announced war on Iran; oil higher and airlines like $UAL under pressure.",
            "sentiment": "BULLISH",
            "velocity": "ACCELERATING",
            "sector": "Energy",
        }
    }

    result = compile_scout_events(
        as_of_date="2026-03-15",
        scout_audit=scout_audit,
        discovery_delta=discovery_delta,
        universe_filter={"universe_symbols": ["XLE", "UAL", "SPY"]},
        x_feed_merged=x_feed_merged,
        macro_cache={"regime": "late_cycle"},
        holdings=["XLE"],
    )

    cards = result["event_cards"]
    assert len(cards) == 1
    card = cards[0]
    assert card["event_type"] == "geopolitical_supply_shock"
    assert sorted(card["source_bundle"]) == ["fvg_recall", "technical_ignition", "x_feed"]
    assert "oil" in card["channels"]
    assert any(entity["entity_id"] == "XLE" for entity in card["direct_entities"])
    assert any(entity["entity_id"] == "UAL" for entity in card["second_order_entities"])
    assert card["expected_direction"]["XLE"] == "up"
    assert card["portfolio_relevance"] == "high"


def test_compile_scout_events_groups_themed_x_feed_records_into_single_event_card():
    from tradingagents.dealflow.scout_compiler import compile_scout_events

    x_feed_merged = {
        "NVDA": {
            "ticker": "NVDA",
            "catalyst": "NVDA and AMAT highlighted for AI memory demand and next-gen chip factory deployment",
            "sentiment": "BULLISH",
            "source_pass_type": "sector",
        },
        "AMAT": {
            "ticker": "AMAT",
            "catalyst": "Applied Materials partnership with MU for AI memory chip capacity expansion",
            "sentiment": "BULLISH",
            "source_pass_type": "sector",
        },
        "MU": {
            "ticker": "MU",
            "catalyst": "Micron earnings focus on AI memory demand after big tech AI beats",
            "sentiment": "BULLISH",
            "source_pass_type": "sector",
        },
    }

    result = compile_scout_events(
        as_of_date="2026-03-15",
        scout_audit={"signals": [], "insider": {"buy_clusters": [], "sell_clusters": []}, "breakout": {"alerts": []}},
        discovery_delta={},
        universe_filter={"symbols": ["NVDA", "AMAT", "MU"]},
        x_feed_merged=x_feed_merged,
        macro_cache={"regime": "late_cycle"},
        holdings=[],
    )

    cards = result["event_cards"]
    assert len(cards) == 1
    card = cards[0]
    assert card["event_type"] == "leading_indicator_signal"
    assert card["title"] == "AI infrastructure buildout cluster"
    assert sorted(entity["entity_id"] for entity in card["direct_entities"]) == ["AMAT", "MU", "NVDA"]
    assert "ai_capex" in card["channels"]


def test_build_coverage_precheck_assigns_complete_partial_and_missing():
    from tradingagents.dealflow.scout_compiler import build_coverage_precheck

    cards = [
        {
            "event_card_id": "evt_complete",
            "date": "2026-03-15",
            "title": "Complete",
            "event_type": "technical_ignition",
            "summary": "Complete card",
            "source_bundle": ["technical_ignition", "x_feed"],
            "source_records": [{"source_family": "technical_ignition"}],
            "direct_entities": [{"entity_type": "ticker", "entity_id": "BE", "label": "BE"}],
            "second_order_entities": [],
            "channels": ["technical_momentum"],
            "expected_direction": {"BE": "up"},
            "confidence": 0.8,
            "urgency": "immediate",
            "time_horizon": "1d_to_5d",
            "portfolio_relevance": "medium",
            "matched_holdings": [],
            "matched_universe_symbols": ["BE"],
            "coverage_dimensions": ["social", "technical"],
            "missing_dimensions": [],
            "followup_questions": [],
        },
        {
            "event_card_id": "evt_partial",
            "date": "2026-03-15",
            "title": "Partial",
            "event_type": "geopolitical_supply_shock",
            "summary": "Partial card",
            "source_bundle": ["x_feed"],
            "source_records": [{"source_family": "x_feed"}],
            "direct_entities": [{"entity_type": "ticker", "entity_id": "XLE", "label": "XLE"}],
            "second_order_entities": [],
            "channels": ["oil"],
            "expected_direction": {"XLE": "up"},
            "confidence": 0.5,
            "urgency": "immediate",
            "time_horizon": "1d_to_5d",
            "portfolio_relevance": "low",
            "matched_holdings": [],
            "matched_universe_symbols": ["XLE"],
            "coverage_dimensions": ["social"],
            "missing_dimensions": ["macro", "portfolio"],
            "followup_questions": [],
        },
        {
            "event_card_id": "evt_missing",
            "date": "2026-03-15",
            "title": "Missing",
            "event_type": "cross_scout_narrative",
            "summary": "Missing card",
            "source_bundle": [],
            "source_records": [],
            "direct_entities": [],
            "second_order_entities": [],
            "channels": [],
            "expected_direction": {},
            "confidence": 0.0,
            "urgency": "developing",
            "time_horizon": "20d_plus",
            "portfolio_relevance": "none",
            "matched_holdings": [],
            "matched_universe_symbols": [],
            "coverage_dimensions": [],
            "missing_dimensions": ["social"],
            "followup_questions": [],
        },
    ]

    payload = build_coverage_precheck(as_of_date="2026-03-15", event_cards=cards)

    rows = {row["event_card_id"]: row for row in payload["rows"]}
    assert rows["evt_complete"]["coverage_status"] == "COMPLETE"
    assert rows["evt_complete"]["ready_for_retrieval"] is True
    assert rows["evt_partial"]["coverage_status"] == "PARTIAL"
    assert rows["evt_missing"]["coverage_status"] == "MISSING"


def test_build_writeback_candidates_preview_only():
    from tradingagents.dealflow.scout_compiler import build_akg_writeback_candidates

    cards = [
        {
            "event_card_id": "evt_1",
            "event_type": "geopolitical_supply_shock",
            "summary": "Oil event",
            "confidence": 0.8,
            "direct_entities": [{"entity_type": "ticker", "entity_id": "XLE", "label": "XLE"}],
            "second_order_entities": [{"entity_type": "ticker", "entity_id": "UAL", "label": "UAL"}],
            "channels": ["oil"],
        }
    ]

    candidates = build_akg_writeback_candidates(cards)

    assert len(candidates) >= 1
    assert {candidate["candidate_type"] for candidate in candidates}.issubset(
        {"edge", "event_summary", "entity_alias", "relationship_claim"}
    )
    assert all("writeback_recommendation" in candidate for candidate in candidates)


def test_persist_scout_compiler_artifacts_writes_expected_files(tmp_path):
    from tradingagents.dealflow.scout_compiler import persist_scout_compiler_artifacts

    payload = {
        "event_cards": [{"event_card_id": "evt_1"}],
        "coverage_precheck": {"rows": []},
        "debug": {"warnings": []},
        "akg_writeback_candidates": [{"candidate_id": "cand_1"}],
    }

    result = persist_scout_compiler_artifacts(
        as_of_date="2026-03-15",
        payload=payload,
        base_dir=tmp_path / "eval_results" / "deal_flow",
    )

    base = tmp_path / "eval_results" / "deal_flow" / "2026-03-15"
    assert (base / "event_cards.json").exists()
    assert (base / "coverage_precheck.json").exists()
    assert (base / "scout_compiler_debug.json").exists()
    assert (base / "akg_writeback_candidates.json").exists()
    assert result["event_card_count"] == 1
    assert json.loads((base / "event_cards.json").read_text())[0]["event_card_id"] == "evt_1"
