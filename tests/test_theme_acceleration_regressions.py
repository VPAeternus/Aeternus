import datetime as dt
from unittest.mock import patch

from tradingagents.dealflow.akg_universe import build_filtered_universe
from tradingagents.graph.knowledge_graph import AeternusKnowledgeGraph


def _patch_empty_universe_sets():
    return patch("tradingagents.dealflow.akg_universe._build_anchor_set", return_value=[])


def test_axti_hidden_supplier_theme_edge_plus_momentum_enters_rescan_universe():
    """AXTI-type: hidden supplier with theme edge + fresh signal enters research visibility via T5_RESCAN."""
    akg = AeternusKnowledgeGraph()
    today = dt.date.today().isoformat()
    akg.add_node("AXTI", node_type="company", sector="semis_ai_infrastructure")
    akg.add_edge("AXTI", "optical_networking", "catalyst_beneficiary", confidence=0.8, evidence_source="theme_alias")
    node = akg._nodes["AXTI"]
    node["aeternus_score"] = 62.0
    node["emergence_tier"] = "SCORED"
    node["primary_theme"] = "optical_networking"
    akg.enrich_node_price_momentum("AXTI", score=78.0, rs_spy=22.0, as_of_date=today)
    node["emergence_tier"] = "SCORED"  # preserve analyzed/rescan status after recompute

    with _patch_empty_universe_sets():
        rows, tier_map = build_filtered_universe(akg, config={})

    assert tier_map["AXTI"] == "T5_RESCAN"
    assert "AXTI" in {row["symbol"] for row in rows}


def test_glw_filing_theme_acceleration_promotes_without_price_momentum():
    """GLW-type: filing-confirmed theme acceleration enters rescan without price momentum."""
    akg = AeternusKnowledgeGraph()
    akg.update_theme_acceleration_signal("GLW", {
        "as_of_date": "2026-05-05",
        "primary_theme": "optical_networking",
        "theme_confidence": "high",
        "theme_role": "infrastructure_provider",
        "theme_acceleration_score": 10,
        "theme_evidence": ["Management said optical communications demand drove segment growth."],
    })

    assert akg._nodes["GLW"].get("signal_momentum_score") is None
    assert akg._nodes["GLW"]["theme_acceleration_rescan_flag"] is True
    assert akg._nodes["GLW"]["theme_acceleration_research_visibility"] is True

    with _patch_empty_universe_sets():
        rows, tier_map = build_filtered_universe(akg, config={})

    assert tier_map["GLW"] == "T5_RESCAN"
    assert "GLW" in {row["symbol"] for row in rows}


def test_theme_acceleration_does_not_create_buy_or_trade_state():
    akg = AeternusKnowledgeGraph()
    akg.update_theme_acceleration_signal("GLW", {
        "as_of_date": "2026-05-05",
        "theme_confidence": "high",
        "theme_acceleration_score": 12,
        "theme_evidence": ["Theme-driven capacity expansion."],
    })
    node = akg._nodes["GLW"]
    assert node["theme_acceleration_rescan_flag"] is True
    assert node["theme_acceleration_research_visibility"] is True
    assert node.get("approved_buy") is None
    assert node.get("trade_order") is None
    assert node.get("current_position") is None


def test_theme_acceleration_no_forward_looking_candidate_filter():
    akg = AeternusKnowledgeGraph()
    akg.update_theme_acceleration_signal("FUTURE", {
        "as_of_date": "2026-06-01",
        "theme_confidence": "high",
        "theme_acceleration_score": 12,
        "theme_evidence": ["Future filing evidence."],
    })
    assert [n["id"] for n in akg.get_theme_acceleration_candidates("2026-05-05")] == []
    assert [n["id"] for n in akg.get_theme_acceleration_candidates("2026-06-01")] == ["FUTURE"]


def test_theme_acceleration_missing_evidence_zeroes_score_and_blocks_rescan():
    akg = AeternusKnowledgeGraph()
    akg.update_theme_acceleration_signal("NOEVID", {
        "as_of_date": "2026-05-05",
        "theme_confidence": "high",
        "theme_acceleration_score": 15,
        "theme_evidence": [],
    })
    node = akg._nodes["NOEVID"]
    assert node["signal_theme_acceleration_score"] == 0
    assert node["theme_acceleration_rescan_flag"] is False
    assert node["theme_acceleration_research_visibility"] is False
