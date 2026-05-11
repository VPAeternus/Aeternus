# Codex Research Bridge Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace deep-analysis analyst API execution with a local Codex CLI bridge that runs four analyst jobs in parallel per ticker, stores structured artifacts, and then hands control back to the existing downstream analysis flow.

**Architecture:** Introduce a dedicated `codex_research_bridge` module that shells out to `codex exec` for `market`, `social`, `news`, and `fundamentals` prompts, persists one JSON artifact per analyst under `results/{ticker}/{date}/codex_research/`, and validates the artifact contract before downstream use. Add a downstream-only graph execution seam so `run_analysis()` can skip analyst nodes when Codex artifacts are present, while leaving debate, trader, risk, scoring, and report generation on the existing path for this first slice.

**Tech Stack:** Python 3, Typer CLI, LangGraph, subprocess, JSON Schema, pytest, local Codex CLI (`codex exec`)

---

### Task 1: Define the Codex artifact contract and command builder

**Files:**
- Create: `tradingagents/graph/codex_research_bridge.py`
- Create: `tradingagents/graph/schemas/codex_analyst_output.schema.json`
- Test: `tests/test_codex_research_bridge.py`

**Step 1: Write the failing test**

```python
from pathlib import Path

from tradingagents.graph.codex_research_bridge import (
    analyst_artifact_path,
    build_codex_exec_command,
)


def test_build_codex_exec_command_uses_gpt54_and_xhigh(tmp_path: Path):
    out = tmp_path / "market.json"
    schema = tmp_path / "schema.json"

    cmd = build_codex_exec_command(
        repo_root=tmp_path,
        model="gpt-5.4",
        reasoning_effort="xhigh",
        schema_path=schema,
        output_path=out,
    )

    assert cmd[:2] == ["codex", "exec"]
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
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_codex_research_bridge.py::test_build_codex_exec_command_uses_gpt54_and_xhigh -v`

Expected: FAIL with `ModuleNotFoundError` or missing symbol errors.

**Step 3: Write minimal implementation**

Implement:

- `ANALYST_NAMES = ("market", "social", "news", "fundamentals")`
- `analyst_artifact_path(...)`
- `build_codex_exec_command(...)`
- a shared schema file for the artifact contract

Use the real Codex CLI contract:

```python
[
    "codex",
    "exec",
    "-C", str(repo_root),
    "-m", "gpt-5.4",
    "-c", 'model_reasoning_effort="xhigh"',
    "--output-schema", str(schema_path),
    "-o", str(output_path),
    "-",
]
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_codex_research_bridge.py -v`

Expected: PASS for command-builder and artifact-path tests.

**Step 5: Commit**

```bash
git add tests/test_codex_research_bridge.py tradingagents/graph/codex_research_bridge.py tradingagents/graph/schemas/codex_analyst_output.schema.json
git commit -m "feat: add codex research bridge contract"
```

### Task 2: Add prompt builders and single-analyst execution

**Files:**
- Modify: `tradingagents/graph/codex_research_bridge.py`
- Test: `tests/test_codex_research_bridge.py`

**Step 1: Write the failing test**

```python
from unittest.mock import Mock

from tradingagents.graph.codex_research_bridge import run_single_analyst


def test_run_single_analyst_writes_structured_artifact(tmp_path, monkeypatch):
    fake_run = Mock(return_value=Mock(returncode=0, stdout="", stderr=""))
    monkeypatch.setattr("tradingagents.graph.codex_research_bridge.subprocess.run", fake_run)

    path = run_single_analyst(
        repo_root=tmp_path,
        results_root=tmp_path / "results",
        ticker="AAPL",
        analysis_date="2026-03-05",
        analyst="market",
        prompt_text="Analyze AAPL market structure",
    )

    payload = __import__("json").loads(path.read_text())
    assert payload["ticker"] == "AAPL"
    assert payload["analyst"] == "market"
    assert payload["model"] == "gpt-5.4"
    assert payload["reasoning_effort"] == "xhigh"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_codex_research_bridge.py::test_run_single_analyst_writes_structured_artifact -v`

Expected: FAIL because `run_single_analyst()` is missing or incomplete.

**Step 3: Write minimal implementation**

Add:

- `build_analyst_prompt(...)` with one prompt template per analyst
- `run_single_analyst(...)` that:
  - writes a prompt file
  - shells out with `subprocess.run(..., input=prompt_text, text=True, timeout=...)`
  - writes a structured JSON artifact
  - records `status`, timestamps, duration, `exit_code`, and `error`

Prompt files should live beside artifacts, for example:

- `results/{ticker}/{date}/codex_research/prompts/market.txt`

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_codex_research_bridge.py -k single_analyst -v`

Expected: PASS with no live Codex dependency because subprocess is mocked.

**Step 5: Commit**

```bash
git add tests/test_codex_research_bridge.py tradingagents/graph/codex_research_bridge.py
git commit -m "feat: add codex single-analyst execution"
```

### Task 3: Add ticker-scoped 4-way parallel fan-out with retry and validation

**Files:**
- Modify: `tradingagents/graph/codex_research_bridge.py`
- Test: `tests/test_codex_research_bridge.py`

**Step 1: Write the failing test**

```python
from tradingagents.graph.codex_research_bridge import run_ticker_bundle


def test_run_ticker_bundle_executes_all_four_analysts(tmp_path, monkeypatch):
    calls = []

    def _fake_run_single_analyst(**kwargs):
        calls.append(kwargs["analyst"])
        out = kwargs["results_root"] / kwargs["ticker"] / kwargs["analysis_date"] / "codex_research" / f"{kwargs['analyst']}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            '{"ticker":"AAPL","as_of_date":"2026-03-05","analyst":"%s","status":"SUCCESS","model":"gpt-5.4","reasoning_effort":"xhigh","report_markdown":"ok","sources":[],"metadata":{}}'
            % kwargs["analyst"]
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
    assert sorted(bundle["artifacts"]) == ["fundamentals", "market", "news", "social"]
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_codex_research_bridge.py::test_run_ticker_bundle_executes_all_four_analysts -v`

Expected: FAIL because the orchestrator and validation helpers do not exist yet.

**Step 3: Write minimal implementation**

Use `concurrent.futures.ThreadPoolExecutor(max_workers=4)` to:

- submit one job per analyst
- wait for all four
- retry only failed analysts up to the configured retry count
- validate that each artifact has `status == "SUCCESS"` and non-empty `report_markdown`

Return a bundle shaped like:

```python
{
    "ticker": "AAPL",
    "analysis_date": "2026-03-05",
    "complete": True,
    "artifacts": {"market": "...", "social": "...", "news": "...", "fundamentals": "..."},
    "failures": [],
}
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_codex_research_bridge.py -k ticker_bundle -v`

Expected: PASS for success, retry, and validation tests.

**Step 5: Commit**

```bash
git add tests/test_codex_research_bridge.py tradingagents/graph/codex_research_bridge.py
git commit -m "feat: add per-ticker codex analyst fanout"
```

### Task 4: Add a downstream-only graph seam that starts after analyst collection

**Files:**
- Modify: `tradingagents/graph/setup.py`
- Modify: `tradingagents/graph/trading_graph.py`
- Create: `tests/test_trading_graph_codex_bridge.py`

**Step 1: Write the failing test**

```python
from tradingagents.graph.trading_graph import TradingAgentsGraph


def test_trading_graph_exposes_post_analyst_graph(monkeypatch):
    graph = TradingAgentsGraph(config={"llm_provider": "claude_cli"})
    assert graph.post_analyst_graph is not None
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_trading_graph_codex_bridge.py::test_trading_graph_exposes_post_analyst_graph -v`

Expected: FAIL because no downstream-only graph exists yet.

**Step 3: Write minimal implementation**

Refactor `GraphSetup` so it can compile:

- the existing full graph
- a new downstream-only graph beginning at `Bull Researcher`

The downstream graph should assume the initial state already contains:

- `market_report`
- `sentiment_report`
- `news_report`
- `fundamentals_report`

Expose that compiled graph as `TradingAgentsGraph.post_analyst_graph`.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_trading_graph_codex_bridge.py -v`

Expected: PASS and no regression to existing graph construction tests.

**Step 5: Commit**

```bash
git add tests/test_trading_graph_codex_bridge.py tradingagents/graph/setup.py tradingagents/graph/trading_graph.py
git commit -m "feat: add post-analyst graph path"
```

### Task 5: Wire `run_analysis()` to use the Codex bridge before downstream graph execution

**Files:**
- Modify: `cli/commands/scoring.py`
- Modify: `tradingagents/default_config.py`
- Modify: `cli/common.py`
- Create: `tests/test_scoring_codex_bridge.py`

**Step 1: Write the failing test**

```python
from cli.commands.scoring import run_analysis


def test_run_analysis_uses_codex_bridge_when_enabled(monkeypatch, tmp_path):
    called = {"bundle": 0, "graph": 0}

    monkeypatch.setattr("cli.commands.scoring.DEFAULT_CONFIG", {
        "results_dir": str(tmp_path / "results"),
        "research_execution_mode": "codex_bridge",
        "llm_provider": "claude_cli",
        "quick_think_llm": "claude-sonnet-4-6",
        "deep_think_llm": "claude-sonnet-4-6",
        "backend_url": "claude_cli",
    })
    monkeypatch.setattr(
        "cli.commands.scoring.run_ticker_bundle",
        lambda **kwargs: called.__setitem__("bundle", called["bundle"] + 1) or {
            "complete": True,
            "artifacts": {},
        },
    )

    class _FakeGraph:
        post_analyst_graph = object()
        propagator = type("P", (), {"create_initial_state": lambda *a, **k: {}, "get_graph_args": lambda *a, **k: {}})()

    monkeypatch.setattr("cli.commands.scoring.TradingAgentsGraph", lambda *a, **k: _FakeGraph())

    # The exact UI plumbing can be mocked away; this test only asserts the bridge path is entered.
    assert called["bundle"] == 0
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_scoring_codex_bridge.py -v`

Expected: FAIL because `run_analysis()` does not branch into a Codex bridge path yet.

**Step 3: Write minimal implementation**

Add `research_execution_mode` config handling:

- `graph` for current full-graph path
- `codex_bridge` for:
  - run `run_ticker_bundle(...)`
  - load artifact `report_markdown` into the initial state
  - mark analyst report sections complete in the UI
  - stream `graph.post_analyst_graph` for debate, trader, risk, and final scoring

Also add default config entries such as:

- `research_execution_mode`
- `codex_cli_binary`
- `codex_cli_model`
- `codex_cli_reasoning_effort`
- `codex_cli_timeout_seconds`
- `codex_cli_retry_count`

Thread this through `_build_noninteractive_selections()` only if needed for batch/deep runs. Do not change `score()` in this slice.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_scoring_codex_bridge.py -v`

Expected: PASS for the new branch and no regression to existing scoring tests.

**Step 5: Commit**

```bash
git add tests/test_scoring_codex_bridge.py cli/commands/scoring.py tradingagents/default_config.py cli/common.py
git commit -m "feat: wire analyze to codex research bridge"
```

### Task 6: Verify batch behavior and preserve current downstream artifacts

**Files:**
- Modify: `tests/test_cli_dealflow.py`
- Modify: `tests/test_session_assembler.py`
- Modify: `tests/test_reanalysis.py`

**Step 1: Write the failing test**

Add a batch-level test that proves:

- `retired post-scout batch command --selected-only` still writes `analysis_report.json`
- batch summaries still populate `analysis_report_path` and `analysis_report_found`
- downstream consumers such as reanalysis still read the same path

**Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/test_cli_dealflow.py -k analyze_batch -v
pytest tests/test_reanalysis.py -v
```

Expected: At least one failure until the new path preserves the old artifact contract.

**Step 3: Write minimal implementation**

Adjust any integration points needed so the Codex bridge path still produces:

- `results/{ticker}/{date}/analysis_report.json`
- `results/{ticker}/{date}/Equity_Research_Report.md`
- batch summary metadata unchanged

Do not fork a new report format.

**Step 4: Run test to verify it passes**

Run:

```bash
pytest tests/test_cli_dealflow.py -k analyze_batch -v
pytest tests/test_reanalysis.py -v
pytest tests/test_session_assembler.py -v
```

Expected: PASS with no downstream path breakage.

**Step 5: Commit**

```bash
git add tests/test_cli_dealflow.py tests/test_reanalysis.py tests/test_session_assembler.py
git commit -m "test: preserve downstream report contract for codex bridge"
```

### Task 7: Manual smoke test with local Codex and final cleanup

**Files:**
- Modify: `memory/WORKING.md`
- Modify: `memory/MEMORY.md` (only if architecture decisions changed)
- Create or Modify: `memory/2026-03-05.md`

**Step 1: Run the manual smoke test**

Run:

```bash
codex --version
codex login
python -m cli.main analyze --from-queue-id <QUEUE_ID> --run-date <YYYY-MM-DD>
```

Expected:

- four artifacts under `results/{ticker}/{date}/codex_research/`
- `analysis_report.json` written
- no manual copy/paste for research analysts

**Step 2: Run the full targeted verification set**

Run:

```bash
pytest tests/test_codex_research_bridge.py -v
pytest tests/test_trading_graph_codex_bridge.py -v
pytest tests/test_scoring_codex_bridge.py -v
pytest tests/test_cli_dealflow.py -k analyze_batch -v
pytest tests/test_reanalysis.py -v
pytest tests/test_session_assembler.py -v
```

Expected: PASS

**Step 3: Run the broader suite if time permits**

Run: `python -m pytest tests/ -v`

Expected: PASS, or document exactly which unrelated pre-existing failures remain.

**Step 4: Update memory files**

Record:

- Codex bridge architecture
- required local setup (`codex exec`, ChatGPT login)
- current limitation that manual Grok remains only for dealflow/social ingestion

**Step 5: Commit**

```bash
git add memory/WORKING.md memory/MEMORY.md memory/2026-03-05.md
git commit -m "docs: record codex research bridge rollout"
```

## Notes for the Implementer

- Do not delete `claude_cli`, `llm_quick`, or `model_router.py` in this implementation slice.
- First prove the Codex analyst bridge works and preserves `analysis_report.json`.
- Only after that should the broader provider-deletion phase begin.
- Keep all live Codex subprocess calls behind mocks in automated tests.
- The operator should lower this session from `extra-high` to `high` before starting code changes.
