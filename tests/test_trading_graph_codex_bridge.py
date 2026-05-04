from unittest import mock


def test_trading_graph_exposes_post_analyst_graph(monkeypatch):
    import os
    import tradingagents.graph.trading_graph as tg_module
    from tradingagents.default_config import DEFAULT_CONFIG

    class _FakeGraphSetup:
        def __init__(self, *args, **kwargs):
            pass

        def setup_graph(self, selected_analysts):
            return "full-graph"

        def setup_post_analyst_graph(self):
            return "post-graph"

    for key in (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GOOGLE_API_KEY",
        "OPENAI_AUTH_TOKEN",
        "ANTHROPIC_AUTH_TOKEN",
        "MINIMAX_OAUTH_TOKEN",
        "MINIMAX_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)

    monkeypatch.setattr(tg_module, "GraphSetup", _FakeGraphSetup)
    monkeypatch.setattr(tg_module, "Propagator", mock.MagicMock())
    monkeypatch.setattr(tg_module, "Reflector", mock.MagicMock())
    monkeypatch.setattr(tg_module, "SignalProcessor", mock.MagicMock())
    monkeypatch.setattr(tg_module, "SectorContext", mock.MagicMock())
    monkeypatch.setattr(tg_module, "TrackRecord", mock.MagicMock())
    monkeypatch.setattr(tg_module, "AeternusScorer", mock.MagicMock())
    monkeypatch.setattr(tg_module, "ThesisChecker", mock.MagicMock())
    monkeypatch.setattr(tg_module, "ConditionalLogic", mock.MagicMock())
    monkeypatch.setattr(tg_module, "FinancialSituationMemory", mock.MagicMock())
    monkeypatch.setattr(tg_module, "TradeMemory", mock.MagicMock())
    monkeypatch.setattr(tg_module, "set_config", mock.MagicMock())
    monkeypatch.setattr(tg_module, "ToolNode", mock.MagicMock())
    monkeypatch.setattr(os, "makedirs", mock.MagicMock())

    config = dict(DEFAULT_CONFIG)
    config["llm_provider"] = "claude_cli"
    config["quick_think_provider"] = "claude_cli"

    graph = tg_module.TradingAgentsGraph(config=config)

    assert graph.graph == "full-graph"
    assert graph.post_analyst_graph == "post-graph"
