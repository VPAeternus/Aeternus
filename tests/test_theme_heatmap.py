from tradingagents.dealflow.theme_heatmap import build_theme_heatmap
from tradingagents.graph.knowledge_graph import AeternusKnowledgeGraph


def test_theme_heatmap_counts_theme_acceleration_and_momentum():
    g = AeternusKnowledgeGraph()
    g.update_theme_acceleration_signal("GLW", {
        "as_of_date": "2026-05-05",
        "primary_theme": "optical_networking",
        "theme_role": "infrastructure_provider",
        "theme_confidence": "high",
        "theme_evidence": ["Optical demand drove segment growth."],
        "theme_acceleration_score": 10,
    })
    g.enrich_node_price_momentum("LITE", score=75, rs_spy=12, as_of_date="2026-05-05")
    g._nodes["LITE"]["primary_theme"] = "optical_networking"
    g.add_node("optical_networking", node_type="theme")
    g.add_edge("GLW", "optical_networking", "catalyst_beneficiary", confidence=0.9, evidence_source="filing_theme_acceleration")
    g.add_edge("LITE", "optical_networking", "theme_exposure", confidence=0.7, evidence_source="filing_theme_acceleration")

    heatmap = build_theme_heatmap(g, as_of_date="2026-05-05")
    optical = next(row for row in heatmap["themes"] if row["theme_id"] == "optical_networking")
    assert optical["active_theme_node_count"] == 1
    assert optical["linked_edge_count"] == 2
    assert optical["linked_ticker_count"] == 2
    assert optical["number_with_price_momentum"] == 1
    assert optical["number_with_filing_acceleration"] == 1
    assert optical["average_theme_acceleration_score"] == 10
    assert "GLW" in optical["top_tickers"]
    assert optical["top_evidence_snippets"][0]["ticker"] == "GLW"
