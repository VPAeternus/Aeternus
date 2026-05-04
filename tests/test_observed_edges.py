import json

from tradingagents.dealflow.observed_edges import update_observed_edges_for_cycle
from tradingagents.graph.knowledge_graph import AeternusKnowledgeGraph


def test_update_observed_edges_from_x_feed_catalyst_mentions(tmp_path):
    x_feed_dir = tmp_path / "eval_results" / "x_feed" / "2026-02-07"
    x_feed_dir.mkdir(parents=True, exist_ok=True)
    (x_feed_dir / "merged.json").write_text(
        json.dumps(
            {
                "NVDA": {
                    "ticker": "NVDA",
                    "catalyst": "$NVDA partners with $TSM and $AMAT on packaging capacity",
                }
            }
        )
    )
    kg_path = tmp_path / "kg.json"
    g = AeternusKnowledgeGraph()
    g.add_node("NVDA")
    g.save(kg_path)

    result = update_observed_edges_for_cycle(
        "2026-02-07",
        knowledge_graph_path=kg_path,
        x_feed_root=tmp_path / "eval_results" / "x_feed",
    )

    g2 = AeternusKnowledgeGraph.load(kg_path)
    rels = {(e["source"], e["target"], e["relationship"]) for e in g2._edges}
    assert ("NVDA", "TSM", "co_mentioned") in rels
    assert ("NVDA", "AMAT", "co_mentioned") in rels
    assert result["edges_added"] >= 2
