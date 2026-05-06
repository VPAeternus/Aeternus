from tradingagents.dealflow.akg_writeback import writeback_scores_to_akg, writeback_signals_to_akg
from tradingagents.graph.knowledge_graph import AeternusKnowledgeGraph


def test_writeback_scores_to_akg_uses_public_node_api_and_source_tags():
    akg = AeternusKnowledgeGraph()
    akg.add_node("GLW", node_type="company")

    count = writeback_scores_to_akg(
        akg,
        [{"symbol": "GLW", "core_score": 80, "momentum_score": 10, "asymmetry_score": 5, "lane": "CORE"}],
        [{"symbol": "GLW", "source_status": "OK", "source_name": "theme_acceleration"}],
        "2026-05-05",
    )

    node = akg.get_node("GLW")
    assert count == 1
    assert node["pipeline_core_score"] == 80
    assert node["pipeline_source_tags"] == ["theme_acceleration"]


def test_writeback_signals_to_akg_skips_non_ok_signals():
    akg = AeternusKnowledgeGraph()
    count = writeback_signals_to_akg(
        akg,
        [{"symbol": "GLW", "source_status": "ERROR", "signal_family": "price_momentum", "raw_score": 77}],
        "2026-05-05",
    )

    assert count == 0
    assert akg.get_node("GLW") is None


def test_writeback_signals_to_akg_combines_social_and_news_once():
    akg = AeternusKnowledgeGraph()
    count = writeback_signals_to_akg(
        akg,
        [
            {"symbol": "GLW", "source_status": "OK", "signal_family": "social_momentum", "raw_score": 40},
            {"symbol": "GLW", "source_status": "OK", "signal_family": "news_catalyst", "raw_score": 55},
        ],
        "2026-05-05",
    )

    node = akg.get_node("GLW")
    assert count == 1
    assert node["signal_social_score"] == 40
    assert node["signal_news_catalyst_score"] == 55


def test_writeback_signals_to_akg_enriches_price_momentum():
    akg = AeternusKnowledgeGraph()
    count = writeback_signals_to_akg(
        akg,
        [{"symbol": "GLW", "source_status": "OK", "signal_family": "price_momentum", "raw_score": 77, "direction": "BULLISH"}],
        "2026-05-05",
    )

    assert count == 1
    assert akg.get_node("GLW")["signal_momentum_score"] == 77
