import json


def _mock_score() -> dict:
    return {
        "rating_id": "r1",
        "ticker": "AAPL",
        "date": "2026-03-10",
        "aeternus_score": 74.2,
        "rating": "Buy",
        "confidence": 4,
        "breakdown": {
            "fundamental": 72,
            "coherence": 70,
            "macro": 68,
            "sentiment": 76,
            "momentum": 79,
        },
        "timestamp": "2026-03-10T09:00:00",
    }


def test_run_session_research_writes_downstream_report(tmp_path, monkeypatch):
    from tradingagents.graph.session_research_engine import run_session_research

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "tradingagents.graph.session_research_engine.gather_computation_data",
        lambda ticker, date, sector="", asset_class="Equity": {
            "ticker": ticker,
            "date": date,
            "fundamental_metrics": {"data_coverage": 0.8},
            "sentiment_metrics": {"data_coverage": 0.8},
            "macro_metrics": {"data_coverage": 0.8, "regime": "NEUTRAL"},
            "momentum_metrics": {"data_coverage": 0.8},
            "options_metrics": {},
            "flow_toxicity_metrics": {},
        },
    )
    monkeypatch.setattr(
        "tradingagents.graph.session_research_engine.build_session_score",
        lambda computation_data, sonnet_outputs: _mock_score(),
    )
    monkeypatch.setattr(
        "tradingagents.graph.session_research_engine._run_research_completion",
        lambda **kwargs: {
            "market_report": "market",
            "sentiment_report": "sentiment",
            "news_report": "news",
            "fundamentals_report": "fundamentals",
            "investment_plan": "plan",
            "final_trade_decision": "Recommendation: **BUY**",
            "trader_investment_decision": "BUY",
        },
    )

    report_path = run_session_research(
        ticker="AAPL",
        analysis_date="2026-03-10",
        provider="claude",
        queue_context={"sector": "Technology", "asset_class": "Equity", "lane": "CORE"},
    )

    payload = json.loads((tmp_path / report_path).read_text())
    assert payload["company_of_interest"] == "AAPL"
    assert payload["market_report"] == "market"
    assert payload["final_trade_decision"] == "Recommendation: **BUY**"
    assert payload["dealflow_context"]["lane"] == "CORE"
    assert payload["aeternus_score"]["aeternus_score"] == 74.2


def test_run_session_research_passes_provider_to_completion_layer(tmp_path, monkeypatch):
    from tradingagents.graph.session_research_engine import run_session_research

    captured = {}

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "tradingagents.graph.session_research_engine.gather_computation_data",
        lambda ticker, date, sector="", asset_class="Equity": {
            "ticker": ticker,
            "date": date,
            "fundamental_metrics": {},
            "sentiment_metrics": {},
            "macro_metrics": {},
            "momentum_metrics": {},
            "options_metrics": {},
            "flow_toxicity_metrics": {},
        },
    )
    monkeypatch.setattr(
        "tradingagents.graph.session_research_engine.build_session_score",
        lambda computation_data, sonnet_outputs: _mock_score(),
    )

    def _fake_run_completion(**kwargs):
        captured.update(kwargs)
        return {
            "market_report": "market",
            "sentiment_report": "sentiment",
            "news_report": "news",
            "fundamentals_report": "fundamentals",
            "investment_plan": "plan",
            "final_trade_decision": "Recommendation: **HOLD**",
        }

    monkeypatch.setattr(
        "tradingagents.graph.session_research_engine._run_research_completion",
        _fake_run_completion,
    )

    run_session_research(
        ticker="MSFT",
        analysis_date="2026-03-10",
        provider="gpt",
    )

    assert captured["provider"] == "gpt"


def test_run_session_research_persists_llm_influence_block(tmp_path, monkeypatch):
    from tradingagents.graph.session_research_engine import run_session_research

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "tradingagents.graph.session_research_engine.gather_computation_data",
        lambda ticker, date, sector="", asset_class="Equity": {
            "ticker": ticker,
            "date": date,
            "fundamental_metrics": {"data_coverage": 0.8},
            "sentiment_metrics": {"data_coverage": 0.8},
            "macro_metrics": {"data_coverage": 0.8, "regime": "NEUTRAL"},
            "momentum_metrics": {"data_coverage": 0.8},
            "options_metrics": {},
            "flow_toxicity_metrics": {},
        },
    )

    calls = {"count": 0}

    def _mock_build_score(computation_data, sonnet_outputs):
        calls["count"] += 1
        if calls["count"] == 1:
            return {
                "rating_id": "r-pre",
                "ticker": "AAPL",
                "date": "2026-03-10",
                "aeternus_score": 60.0,
                "rating": "Buy",
                "confidence": 1,
                "breakdown": {},
                "ensemble_model_scores": {
                    "fundamental": 62,
                    "coherence": 58,
                    "macro": 61,
                    "sentiment": 57,
                    "momentum": 59,
                    "research_debate": None,
                    "trader_verdict": None,
                    "risk_verdict": None,
                },
                "timestamp": "2026-03-10T09:00:00",
            }
        return {
            "rating_id": "r-post",
            "ticker": "AAPL",
            "date": "2026-03-10",
            "aeternus_score": 64.5,
            "rating": "Buy",
            "confidence": 4,
            "breakdown": {},
            "ensemble_model_scores": {
                "fundamental": 62,
                "coherence": 58,
                "macro": 61,
                "sentiment": 57,
                "momentum": 59,
                "research_debate": 66,
                "trader_verdict": 68,
                "risk_verdict": 55,
            },
            "timestamp": "2026-03-10T09:00:01",
        }

    monkeypatch.setattr(
        "tradingagents.graph.session_research_engine.build_session_score",
        _mock_build_score,
    )
    monkeypatch.setattr(
        "tradingagents.graph.session_research_engine._run_research_completion",
        lambda **kwargs: {
            "market_report": "market",
            "sentiment_report": "sentiment",
            "news_report": "news",
            "fundamentals_report": "fundamentals",
            "investment_plan": "plan",
            "final_trade_decision": "Recommendation: **BUY**",
            "trader_investment_decision": "BUY",
        },
    )

    report_path = run_session_research(
        ticker="AAPL",
        analysis_date="2026-03-10",
        provider="claude",
        queue_context={"sector": "Technology"},
    )

    payload = json.loads((tmp_path / report_path).read_text())
    score_block = payload["aeternus_score"]
    influence = score_block["llm_influence"]

    assert score_block["pre_llm_score"] == 60.0
    assert score_block["aeternus_score"] == 64.5
    assert influence["score_delta"] == 4.5
    assert influence["confidence_delta"] == 3.0
    assert influence["debate_components"]["research_debate"]["before"] is None
    assert influence["debate_components"]["research_debate"]["after"] == 66
    assert influence["debate_components"]["research_debate"]["delta"] is None
    assert influence["active_debate_components"] == [
        "research_debate",
        "risk_verdict",
        "trader_verdict",
    ]
