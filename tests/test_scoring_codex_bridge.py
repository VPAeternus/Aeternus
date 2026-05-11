import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock


class _StubMessageBuffer:
    def __init__(self):
        self.messages = []
        self.tool_calls = []
        self.report_sections = {
            "market_report": None,
            "sentiment_report": None,
            "news_report": None,
            "fundamentals_report": None,
            "investment_plan": None,
            "final_trade_decision": None,
            "trader_investment_plan": None,
            "aeternus_score": None,
            "portfolio_risk_hedge": None,
        }
        self.agent_status = {
            "Market Analyst": "pending",
            "Social Analyst": "pending",
            "News Analyst": "pending",
            "Fundamentals Analyst": "pending",
            "Trader": "pending",
            "Trader": "pending",
            "Research Manager": "pending",
            "Risky Analyst": "pending",
            "Safe Analyst": "pending",
            "Neutral Analyst": "pending",
            "Portfolio Manager": "pending",
        }
        self.current_report = None
        self.final_report = None

    def add_message(self, message_type, content):
        self.messages.append(("ts", message_type, content))

    def add_tool_call(self, tool_name, args):
        self.tool_calls.append(("ts", tool_name, args))

    def update_report_section(self, section_name, content):
        self.report_sections[section_name] = content

    def update_agent_status(self, agent, status):
        self.agent_status[agent] = status

    def get_equity_research_report(self, ticker, analysis_date):
        return f"{ticker} {analysis_date}"


class _NullLive:
    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_run_analysis_uses_codex_bridge_path(tmp_path, monkeypatch):
    import cli.commands.scoring as scoring

    results_root = tmp_path / "results"
    artifact_dir = results_root / "AAPL" / "2026-03-05" / "codex_research"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    for name, report in (
        ("market", "market report"),
        ("news", "news report"),
        ("fundamentals", "fundamentals report"),
    ):
        (artifact_dir / f"{name}.json").write_text(
            json.dumps(
                {
                    "ticker": "AAPL",
                    "as_of_date": "2026-03-05",
                    "analyst": name,
                    "status": "SUCCESS",
                    "model": "gpt-5.4",
                    "reasoning_effort": "xhigh",
                    "report_markdown": report,
                    "sources": [],
                    "metadata": {},
                }
            )
        )

    class _PostAnalystRunner:
        def __init__(self):
            self.called = False

        def stream(self, init_state, **kwargs):
            self.called = True
            yield {
                "messages": [],
                "market_report": init_state["market_report"],
                "news_report": init_state["news_report"],
                "fundamentals_report": init_state["fundamentals_report"],
                "final_trade_decision": "BUY AAPL",
                "trader_investment_plan": "",
                "legacy_removed_state": {},
                "legacy_removed_state": {},
            }

    class _FullGraphRunner:
        def stream(self, init_state, **kwargs):
            raise AssertionError("full graph should not be used in codex bridge mode")

    post_runner = _PostAnalystRunner()

    class _FakeGraph:
        def __init__(self):
            self.graph = _FullGraphRunner()
            self.post_analyst_graph = post_runner
            self.propagator = SimpleNamespace(
                create_initial_state=lambda ticker, analysis_date: {},
                get_graph_args=lambda: {},
            )
            self.aeternus_scorer = SimpleNamespace(
                score=lambda *args, **kwargs: {"rating_id": "r1", "aeternus_score": 80}
            )
            self.thesis_checker = SimpleNamespace(check=lambda *args, **kwargs: {})

        def process_signal(self, signal):
            return signal

    stub_message_buffer = _StubMessageBuffer()
    monkeypatch.setattr(
        scoring,
        "DEFAULT_CONFIG",
        {
            "results_dir": str(results_root),
            "research_execution_mode": "codex_bridge",
            "llm_provider": "claude_cli",
            "quick_think_provider": "claude_cli",
            "quick_think_llm": "claude-sonnet-4-6",
            "deep_think_llm": "claude-sonnet-4-6",
            "backend_url": "claude_cli",
        },
    )
    monkeypatch.setattr(scoring, "TradingAgentsGraph", lambda *args, **kwargs: _FakeGraph())
    monkeypatch.setattr(scoring, "message_buffer", stub_message_buffer)
    monkeypatch.setattr(scoring, "Live", _NullLive)
    monkeypatch.setattr(scoring, "create_layout", lambda: object())
    monkeypatch.setattr(scoring, "update_display", lambda *args, **kwargs: None)
    monkeypatch.setattr(scoring, "update_research_team_status", lambda *args, **kwargs: None)
    monkeypatch.setattr(scoring, "display_complete_report", lambda *args, **kwargs: None)
    monkeypatch.setattr(scoring, "extract_content_string", lambda value: str(value))
    monkeypatch.setattr(scoring, "format_aeternus_score_markdown", lambda *args, **kwargs: "score")
    monkeypatch.setattr(scoring, "format_portfolio_risk_hedge_markdown", lambda *args, **kwargs: "hedge")
    monkeypatch.setattr(scoring, "build_pretrade_risk_context", lambda: ({}, {}, {}, {}, ""))
    monkeypatch.setattr(scoring, "run_hedging_cycle", lambda *args, **kwargs: ({}, {}, {}, {}))
    monkeypatch.setattr(scoring, "RatingAuditLog", lambda: SimpleNamespace(log_event=lambda *args, **kwargs: None))
    monkeypatch.setattr(
        scoring,
        "run_ticker_bundle",
        lambda **kwargs: {
            "ticker": "AAPL",
            "analysis_date": "2026-03-05",
            "complete": True,
            "artifacts": {
                "market": str(artifact_dir / "market.json"),
                "news": str(artifact_dir / "news.json"),
                "fundamentals": str(artifact_dir / "fundamentals.json"),
            },
            "failures": [],
        },
        raising=False,
    )

    analysts = [
        SimpleNamespace(value="market"),
        SimpleNamespace(value="news"),
        SimpleNamespace(value="fundamentals"),
    ]
    scoring.run_analysis(
        selections={
            "ticker": "AAPL",
            "analysis_date": "2026-03-05",
            "research_depth": 1,
            "shallow_thinker": "claude-sonnet-4-6",
            "deep_thinker": "claude-sonnet-4-6",
            "backend_url": "claude_cli",
            "llm_provider": "claude_cli",
            "analysts": analysts,
        }
    )

    assert post_runner.called is True
    assert (results_root / "AAPL" / "2026-03-05" / "analysis_report.json").is_file()


def test_default_config_has_codex_bridge_keys():
    from tradingagents.default_config import DEFAULT_CONFIG

    assert DEFAULT_CONFIG["research_execution_mode"] == "session_engine"
    assert DEFAULT_CONFIG["research_analyst_provider"] == "claude"
    assert DEFAULT_CONFIG["research_post_analyst_provider"] == "claude"
    assert DEFAULT_CONFIG["codex_cli_binary"] == "codex"
    assert DEFAULT_CONFIG["codex_cli_model"] == "gpt-5.4"
    assert DEFAULT_CONFIG["codex_cli_reasoning_effort"] == "xhigh"


def test_build_noninteractive_selections_respects_provider_overrides():
    from cli.common import _build_noninteractive_selections

    selections = _build_noninteractive_selections(
        "AAPL",
        "2026-03-09",
        analyst_provider="grok_manual",
        post_analyst_provider="gpt",
    )

    assert selections["analyst_provider"] == "grok_manual"
    assert selections["post_analyst_provider"] == "gpt"
    assert selections["llm_provider"] == "codex_cli"


def test_run_analysis_forces_codex_cli_for_gpt_post_analyst_provider(monkeypatch):
    import cli.commands.scoring as scoring

    captured = {}

    class _FakeGraph:
        def __init__(self, selected_analysts=None, config=None, **kwargs):
            captured["config"] = dict(config or {})
            self.graph = Mock()
            self.post_analyst_graph = Mock()
            self.propagator = SimpleNamespace(
                create_initial_state=lambda ticker, analysis_date: {},
                get_graph_args=lambda: {},
            )
            self.aeternus_scorer = SimpleNamespace(
                score=lambda *args, **kwargs: {"rating_id": "r1", "aeternus_score": 80}
            )
            self.thesis_checker = SimpleNamespace(check=lambda *args, **kwargs: {})

    monkeypatch.setattr(
        scoring,
        "DEFAULT_CONFIG",
        {
            "results_dir": "/tmp/results",
            "research_execution_mode": "codex_bridge",
            "llm_provider": "claude_cli",
            "quick_think_provider": "claude_cli",
            "backend_url": "claude_cli",
            "codex_cli_quick_model": "gpt-5.4",
            "codex_cli_deep_model": "gpt-5.4",
            "research_analyst_provider": "gpt",
            "research_post_analyst_provider": "claude",
        },
    )
    monkeypatch.setattr(scoring, "TradingAgentsGraph", _FakeGraph)
    monkeypatch.setattr(scoring, "message_buffer", _StubMessageBuffer())
    monkeypatch.setattr(scoring, "Live", _NullLive)
    monkeypatch.setattr(scoring, "create_layout", lambda: object())
    monkeypatch.setattr(scoring, "update_display", lambda *args, **kwargs: None)
    monkeypatch.setattr(scoring, "update_research_team_status", lambda *args, **kwargs: None)
    monkeypatch.setattr(scoring, "display_complete_report", lambda *args, **kwargs: None)
    monkeypatch.setattr(scoring, "extract_content_string", lambda value: str(value))
    monkeypatch.setattr(scoring, "format_aeternus_score_markdown", lambda *args, **kwargs: "score")
    monkeypatch.setattr(scoring, "format_portfolio_risk_hedge_markdown", lambda *args, **kwargs: "hedge")
    monkeypatch.setattr(scoring, "build_pretrade_risk_context", lambda: ({}, {}, {}, {}, ""))
    monkeypatch.setattr(scoring, "run_hedging_cycle", lambda *args, **kwargs: ({}, {}, {}, {}))
    monkeypatch.setattr(scoring, "RatingAuditLog", lambda: SimpleNamespace(log_event=lambda *args, **kwargs: None))
    monkeypatch.setattr(
        scoring,
        "run_ticker_bundle",
        lambda **kwargs: {"complete": False, "failures": [{"analyst": "market", "error": "missing manual artifact"}]},
        raising=False,
    )

    analysts = [
        SimpleNamespace(value="market"),
        SimpleNamespace(value="social"),
        SimpleNamespace(value="news"),
        SimpleNamespace(value="fundamentals"),
    ]
    try:
        scoring.run_analysis(
            selections={
                "ticker": "AAPL",
                "analysis_date": "2026-03-05",
                "research_depth": 1,
                "shallow_thinker": "claude-sonnet-4-6",
                "deep_thinker": "claude-sonnet-4-6",
                "backend_url": "claude_cli",
                "llm_provider": "claude_cli",
                "analysts": analysts,
                "analyst_provider": "grok_manual",
                "post_analyst_provider": "gpt",
            }
        )
    except RuntimeError:
        pass

    assert captured["config"]["llm_provider"] == "codex_cli"
    assert captured["config"]["quick_think_provider"] == "codex_cli"
    assert captured["config"]["backend_url"] == "codex_cli"


def test_run_ticker_bundle_supports_claude_provider(tmp_path, monkeypatch):
    from tradingagents.graph.codex_research_bridge import run_ticker_bundle

    results_root = tmp_path / "results"

    def fake_run_single_analyst_claude(**kwargs):
        artifact = results_root / "AAPL" / "2026-03-09" / "claude_research" / f"{kwargs['analyst']}.json"
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text(
            json.dumps(
                {
                    "ticker": "AAPL",
                    "as_of_date": "2026-03-09",
                    "analyst": kwargs["analyst"],
                    "status": "SUCCESS",
                    "report_markdown": f"{kwargs['analyst']} report",
                    "metadata": {},
                }
            )
        )
        return artifact

    monkeypatch.setattr(
        "tradingagents.graph.codex_research_bridge.run_single_analyst_claude",
        fake_run_single_analyst_claude,
    )

    bundle = run_ticker_bundle(
        repo_root=tmp_path,
        results_root=results_root,
        ticker="AAPL",
        analysis_date="2026-03-09",
        provider="claude",
        model="claude-sonnet-4-6",
        timeout_seconds=30,
    )

    assert bundle["provider"] == "claude"
    assert bundle["complete"] is True
    assert sorted(bundle["artifacts"].keys()) == ["fundamentals", "market", "news"]


def test_run_ticker_bundle_manual_provider_uses_readiness(tmp_path, monkeypatch):
    from tradingagents.graph.codex_research_bridge import run_ticker_bundle

    monkeypatch.setattr(
        "tradingagents.graph.codex_research_bridge.get_manual_bundle_readiness",
        lambda *args, **kwargs: {
            "ready": False,
            "artifacts": {"market": "/tmp/market.json"},
            "missing_analysts": ["social", "news", "fundamentals"],
        },
    )

    bundle = run_ticker_bundle(
        repo_root=tmp_path,
        results_root=tmp_path / "results",
        ticker="AAPL",
        analysis_date="2026-03-09",
        provider="grok_manual",
    )

    assert bundle["provider"] == "grok_manual"
    assert bundle["complete"] is False
    assert len(bundle["failures"]) == 3


def test_run_analysis_uses_session_engine_by_default(monkeypatch):
    import cli.commands.scoring as scoring

    captured = {}

    monkeypatch.setattr(
        scoring,
        "DEFAULT_CONFIG",
        {
            "results_dir": "./results",
            "research_execution_mode": "session_engine",
            "research_analyst_provider": "claude",
            "research_post_analyst_provider": "claude",
        },
    )
    monkeypatch.setattr(
        scoring,
        "_run_session_engine_analysis",
        lambda selections, config=None: captured.setdefault("session", dict(selections)),
        raising=False,
    )
    monkeypatch.setattr(
        scoring,
        "_run_legacy_graph_analysis",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("legacy graph path should not run")
        ),
        raising=False,
    )

    scoring.run_analysis(
        selections={
            "ticker": "AAPL",
            "analysis_date": "2026-03-10",
            "research_depth": 1,
            "shallow_thinker": "claude-sonnet-4-6",
            "deep_thinker": "claude-sonnet-4-6",
            "backend_url": "claude_cli",
            "llm_provider": "claude_cli",
            "analysts": [SimpleNamespace(value="market")],
        }
    )

    assert captured["session"]["ticker"] == "AAPL"


def test_run_session_engine_analysis_appends_track_record_with_recommendation(
    tmp_path, monkeypatch
):
    import cli.commands.scoring as scoring

    report_dir = tmp_path / "results" / "AAPL" / "2026-03-10"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "analysis_report.json"
    report_path.write_text(
        json.dumps(
            {
                "company_of_interest": "AAPL",
                "trade_date": "2026-03-10",
                "final_trade_decision": "Recommendation: **BUY**\n\nRationale: Test.",
                "aeternus_score": {
                    "rating_id": "rid-123",
                    "ticker": "AAPL",
                    "date": "2026-03-10",
                    "aeternus_score": 74.2,
                    "rating": "Hold",
                    "confidence": 4,
                },
            }
        )
    )

    appended = {}
    audit_calls = []

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "tradingagents.graph.session_research_engine.run_session_research",
        lambda **kwargs: str(report_path.relative_to(tmp_path)),
    )
    monkeypatch.setattr(
        scoring,
        "TrackRecord",
        lambda: SimpleNamespace(append=lambda payload: appended.setdefault("payload", dict(payload))),
    )
    monkeypatch.setattr(
        scoring,
        "RatingAuditLog",
        lambda: SimpleNamespace(log_event=lambda *args: audit_calls.append(args)),
    )

    scoring._run_session_engine_analysis(
        {
            "ticker": "AAPL",
            "analysis_date": "2026-03-10",
            "source_context": {"lane": "CORE"},
        }
    )

    assert appended["payload"]["rating_id"] == "rid-123"
    assert appended["payload"]["recommendation"] == "BUY"
    assert audit_calls[0][0] == "RATING_CREATED"
