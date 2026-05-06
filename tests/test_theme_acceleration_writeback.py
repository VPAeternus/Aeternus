from unittest.mock import patch

from tradingagents.dealflow.akg_universe import build_filtered_universe
from tradingagents.dealflow.theme_acceleration_writeback import write_theme_acceleration_to_akg
from tradingagents.dealflow.theme_heatmap import build_theme_heatmap
from tradingagents.graph.knowledge_graph import AeternusKnowledgeGraph


def test_llm_result_writeback_to_akg_promotes_glw_to_rescan():
    akg = AeternusKnowledgeGraph()
    count = write_theme_acceleration_to_akg(akg, [
        {
            "ticker": "GLW",
            "primary_theme": "AI Data Center Infrastructure",
            "secondary_themes": '["800G"]',
            "theme_role": "infrastructure_provider",
            "theme_confidence": "high",
            "theme_driver_type": "revenue",
            "theme_momentum": "accelerating",
            "theme_evidence": '["Optical communications demand drove segment growth."]',
            "theme_acceleration_score": "10",
        }
    ], "2026-05-05")

    assert count == 1
    node = akg._nodes["GLW"]
    assert node["primary_theme"] == "ai_data_center"
    assert node["secondary_themes"] == ["optical_networking"]
    assert node["signal_theme_acceleration_score"] == 10
    assert node["theme_acceleration_rescan_flag"] is True
    assert node["theme_acceleration_research_visibility"] is True
    edges = {
        (edge["source"], edge["target"], edge["relationship"], edge["evidence_sources"][0])
        for edge in akg._edges
    }
    assert ("GLW", "ai_data_center", "catalyst_beneficiary", "filing_theme_acceleration") in edges
    assert ("GLW", "optical_networking", "theme_exposure", "filing_theme_acceleration") in edges

    with patch("tradingagents.dealflow.akg_universe._build_anchor_set", return_value=[]):
        rows, tier_map = build_filtered_universe(akg, config={})

    assert tier_map["GLW"] == "T5_RESCAN"
    assert "GLW" in {row["symbol"] for row in rows}

    heatmap = build_theme_heatmap(akg, as_of_date="2026-05-05")
    ai_theme = next(row for row in heatmap["themes"] if row["theme_id"] == "ai_data_center")
    assert "GLW" in ai_theme["top_tickers"]
    assert ai_theme["number_with_filing_acceleration"] == 1
    assert ai_theme["linked_edge_count"] == 1


def test_write_theme_acceleration_to_akg_requires_evidence():
    akg = AeternusKnowledgeGraph()
    write_theme_acceleration_to_akg(akg, [{"ticker": "GLW", "theme_acceleration_score": 15, "theme_evidence": ""}], "2026-05-05")
    node = akg._nodes["GLW"]
    assert node["signal_theme_acceleration_score"] == 0
    assert node["theme_acceleration_rescan_flag"] is False
