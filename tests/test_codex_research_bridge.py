from pathlib import Path
import json
from types import SimpleNamespace
from concurrent.futures import Future
import subprocess

from tradingagents.graph.codex_research_bridge import (
    ANALYST_NAMES,
    analyst_artifact_path,
    build_analyst_prompt,
    build_codex_exec_command,
    run_ticker_bundle,
    run_single_analyst_claude,
    run_single_analyst,
)


def test_build_codex_exec_command_uses_gpt54_and_xhigh(tmp_path: Path):
    out = tmp_path / "market.json"
    schema = tmp_path / "schema.json"
    work_root = tmp_path / "isolated"

    cmd = build_codex_exec_command(
        work_root=work_root,
        model="gpt-5.4",
        reasoning_effort="xhigh",
        schema_path=schema,
        output_path=out,
    )

    assert cmd[:2] == ["codex", "exec"]
    assert str(work_root) in cmd
    assert "--skip-git-repo-check" in cmd
    assert "--ephemeral" in cmd
    assert "-m" in cmd
    assert "gpt-5.4" in cmd
    assert 'model_reasoning_effort="xhigh"' in cmd
    assert "--output-schema" in cmd
    assert "-o" in cmd


def test_analyst_artifact_path_uses_codex_research_dir(tmp_path: Path):
    path = analyst_artifact_path(
        results_root=tmp_path,
        ticker="AAPL",
        analysis_date="2026-03-05",
        analyst="market",
    )

    assert path == tmp_path / "AAPL" / "2026-03-05" / "codex_research" / "market.json"


def test_run_single_analyst_writes_structured_artifact(tmp_path: Path, monkeypatch):
    def _fake_run(cmd, input=None, capture_output=None, text=None, timeout=None):
        out_path = Path(cmd[cmd.index("-o") + 1])
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text('{"report_markdown":"Market view"}')

        class _Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return _Result()

    monkeypatch.setattr(
        "tradingagents.graph.codex_research_bridge.subprocess.run",
        _fake_run,
    )

    path = run_single_analyst(
        repo_root=tmp_path,
        results_root=tmp_path / "results",
        ticker="AAPL",
        analysis_date="2026-03-05",
        analyst="market",
        prompt_text="Analyze AAPL market structure",
    )

    payload = json.loads(path.read_text())
    assert payload["ticker"] == "AAPL"
    assert payload["analyst"] == "market"
    assert payload["model"] == "gpt-5.4"
    assert payload["reasoning_effort"] == "xhigh"
    assert payload["status"] == "SUCCESS"
    assert payload["report_markdown"] == "Market view"


def test_run_ticker_bundle_executes_all_four_analysts(tmp_path: Path, monkeypatch):
    calls = []

    def _fake_run_single_analyst(**kwargs):
        calls.append(kwargs["analyst"])
        out = (
            kwargs["results_root"]
            / kwargs["ticker"]
            / kwargs["analysis_date"]
            / "codex_research"
            / f"{kwargs['analyst']}.json"
        )
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(
                {
                    "ticker": "AAPL",
                    "as_of_date": "2026-03-05",
                    "analyst": kwargs["analyst"],
                    "status": "SUCCESS",
                    "model": "gpt-5.4",
                    "reasoning_effort": "xhigh",
                    "report_markdown": f"{kwargs['analyst']} report",
                    "sources": [],
                    "metadata": {},
                }
            )
        )
        return out

    monkeypatch.setattr(
        "tradingagents.graph.codex_research_bridge.run_single_analyst",
        _fake_run_single_analyst,
    )

    bundle = run_ticker_bundle(
        repo_root=tmp_path,
        results_root=tmp_path / "results",
        ticker="AAPL",
        analysis_date="2026-03-05",
    )

    assert sorted(calls) == ["fundamentals", "market", "news", "social"]
    assert bundle["ticker"] == "AAPL"
    assert bundle["complete"] is True
    assert sorted(bundle["artifacts"]) == ["fundamentals", "market", "news", "social"]


def test_run_ticker_bundle_limits_claude_parallelism(tmp_path: Path, monkeypatch):
    captured = {}

    class _FakeExecutor:
        def __init__(self, max_workers):
            captured["max_workers"] = max_workers

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def submit(self, fn, **kwargs):
            future = Future()
            artifact = (
                kwargs["results_root"]
                / kwargs["ticker"]
                / kwargs["analysis_date"]
                / "claude_research"
                / f"{kwargs['analyst']}.json"
            )
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text(
                json.dumps(
                    {
                        "ticker": kwargs["ticker"],
                        "as_of_date": kwargs["analysis_date"],
                        "analyst": kwargs["analyst"],
                        "status": "SUCCESS",
                        "report_markdown": f"{kwargs['analyst']} report",
                        "metadata": {},
                    }
                )
            )
            future.set_result(artifact)
            return future

    monkeypatch.setattr(
        "tradingagents.graph.codex_research_bridge.ThreadPoolExecutor",
        _FakeExecutor,
    )

    bundle = run_ticker_bundle(
        repo_root=tmp_path,
        results_root=tmp_path / "results",
        ticker="AAPL",
        analysis_date="2026-03-09",
        provider="claude",
        model="claude-sonnet-4-6",
        timeout_seconds=30,
    )

    assert captured["max_workers"] == 1
    assert bundle["complete"] is True
    assert sorted(bundle["artifacts"].keys()) == sorted(ANALYST_NAMES)


def test_run_single_analyst_claude_parses_fenced_json(tmp_path: Path, monkeypatch):
    stdout = json.dumps(
        {
            "is_error": False,
            "result": '```json\n{"report_markdown":"Claude market report"}\n```',
        }
    )

    class _FakeProc:
        pid = 12345
        returncode = 0

        def communicate(self, input=None, timeout=None):
            return stdout, ""

    monkeypatch.setattr(
        "tradingagents.graph.codex_research_bridge.subprocess.Popen",
        lambda *args, **kwargs: _FakeProc(),
    )

    path = run_single_analyst_claude(
        repo_root=tmp_path,
        results_root=tmp_path / "results",
        ticker="AAPL",
        analysis_date="2026-03-09",
        analyst="market",
        prompt_text="Analyze AAPL",
    )

    payload = json.loads(path.read_text())
    assert payload["status"] == "SUCCESS"
    assert payload["report_markdown"] == "Claude market report"


def test_run_single_analyst_claude_kills_process_group_on_timeout(tmp_path: Path, monkeypatch):
    kill_calls = []

    class _FakeProc:
        pid = 24680
        returncode = 0

        def __init__(self):
            self._timed_out = False

        def communicate(self, input=None, timeout=None):
            if not self._timed_out:
                self._timed_out = True
                raise subprocess.TimeoutExpired(cmd="claude", timeout=timeout)
            return "", ""

    monkeypatch.setattr(
        "tradingagents.graph.codex_research_bridge.subprocess.Popen",
        lambda *args, **kwargs: _FakeProc(),
    )
    monkeypatch.setattr(
        "tradingagents.graph.codex_research_bridge.os.killpg",
        lambda pid, sig: kill_calls.append((pid, sig)),
    )

    path = run_single_analyst_claude(
        repo_root=tmp_path,
        results_root=tmp_path / "results",
        ticker="AAPL",
        analysis_date="2026-03-09",
        analyst="fundamentals",
        prompt_text="Analyze AAPL",
        timeout_seconds=7,
    )

    payload = json.loads(path.read_text())
    assert payload["status"] == "FAILED"
    assert payload["metadata"]["error"] == "claude -p timed out after 7s"
    assert kill_calls
    assert kill_calls[0][0] == 24680


def test_run_single_analyst_claude_retries_once_and_succeeds(tmp_path: Path, monkeypatch):
    calls = {"count": 0}
    success_stdout = json.dumps(
        {
            "is_error": False,
            "result": '{"report_markdown":"Recovered report"}',
        }
    )

    class _FakeProc:
        pid = 13579

        def __init__(self, returncode, stdout, stderr):
            self.returncode = returncode
            self._stdout = stdout
            self._stderr = stderr

        def communicate(self, input=None, timeout=None):
            return self._stdout, self._stderr

    def _fake_popen(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return _FakeProc(-15, "", "")
        return _FakeProc(0, success_stdout, "")

    monkeypatch.setattr(
        "tradingagents.graph.codex_research_bridge.subprocess.Popen",
        _fake_popen,
    )

    path = run_single_analyst_claude(
        repo_root=tmp_path,
        results_root=tmp_path / "results",
        ticker="AAPL",
        analysis_date="2026-03-09",
        analyst="news",
        prompt_text="Analyze AAPL",
        retry_count=1,
    )

    payload = json.loads(path.read_text())
    assert calls["count"] == 2
    assert payload["status"] == "SUCCESS"
    assert payload["report_markdown"] == "Recovered report"


def test_run_single_analyst_claude_uses_fallback_model_on_retry(tmp_path: Path, monkeypatch):
    called_models = []
    success_stdout = json.dumps(
        {
            "is_error": False,
            "result": '{"report_markdown":"Recovered report"}',
        }
    )

    class _FakeProc:
        def __init__(self, returncode, stdout):
            self.pid = 111
            self.returncode = returncode
            self._stdout = stdout

        def communicate(self, input=None, timeout=None):
            return self._stdout, ""

    def _fake_popen(cmd, *args, **kwargs):
        called_models.append(cmd[cmd.index("--model") + 1])
        if len(called_models) == 1:
            return _FakeProc(-15, "")
        return _FakeProc(0, success_stdout)

    monkeypatch.setattr(
        "tradingagents.graph.codex_research_bridge.subprocess.Popen",
        _fake_popen,
    )

    path = run_single_analyst_claude(
        repo_root=tmp_path,
        results_root=tmp_path / "results",
        ticker="AAPL",
        analysis_date="2026-03-09",
        analyst="fundamentals",
        prompt_text="Analyze AAPL",
        model="claude-sonnet-4-6",
        fallback_model="claude-haiku-4-5-20251001",
        retry_count=1,
    )

    payload = json.loads(path.read_text())
    assert called_models == ["claude-sonnet-4-6", "claude-haiku-4-5-20251001"]
    assert payload["status"] == "SUCCESS"
    assert payload["model"] == "claude-haiku-4-5-20251001"


def test_codex_output_schema_is_strict_and_minimal():
    schema_path = Path(
        "tradingagents/graph/schemas/codex_analyst_output.schema.json"
    )
    schema = json.loads(schema_path.read_text())

    assert schema["type"] == "object"
    assert schema["required"] == ["report_markdown"]
    assert schema["additionalProperties"] is False
    assert list(schema["properties"]) == ["report_markdown"]


def test_build_analyst_prompt_forbids_repo_exploration():
    prompt = build_analyst_prompt("AAPL", "2026-03-05", "market")

    assert "Do not inspect local repository files" in prompt
    assert "Return exactly one JSON object matching the provided schema" in prompt
    assert "## Thesis" in prompt
    assert "## What Matters Most" in prompt
    assert "## Bottom Line" in prompt


def test_build_analyst_prompt_uses_institutional_common_shell():
    prompt = build_analyst_prompt("AAPL", "2026-03-05", "market")

    assert "top-tier institutional equity research analyst" in prompt
    assert "internal investment committee" in prompt
    assert "facts from inference" in prompt
    assert "priced in versus not priced in" in prompt
    assert '{"report_markdown":"..."}' in prompt


def test_build_analyst_prompt_includes_market_specific_mandate():
    prompt = build_analyst_prompt("AAPL", "2026-03-05", "market")

    assert "strictly through market structure, price action, positioning, volatility, liquidity, and technical/regime context" in prompt
    assert "support, resistance, breakout/breakdown zones" in prompt
    assert "constructive, neutral, or deteriorating" in prompt


def test_build_analyst_prompt_includes_social_specific_mandate():
    prompt = build_analyst_prompt("AAPL", "2026-03-05", "social")

    assert "X/social discussion" in prompt
    assert "signal from engagement bait" in prompt
    assert "investable, tradable, or ignorable" in prompt


def test_build_analyst_prompt_includes_news_specific_mandate():
    prompt = build_analyst_prompt("AAPL", "2026-03-05", "news")

    assert "recent news flow and catalysts only" in prompt
    assert "7-30 days" in prompt
    assert "catalyst map" in prompt


def test_build_analyst_prompt_includes_fundamentals_specific_mandate():
    prompt = build_analyst_prompt("AAPL", "2026-03-05", "fundamentals")

    assert "business quality and valuation using a professional equity-research standard" in prompt
    assert "intrinsic value over the next 1-3 years" in prompt
    assert "what bulls believe, what bears believe" in prompt
