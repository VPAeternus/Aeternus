# Codex Research Bridge Design

**Date:** 2026-03-05

**Goal**

Replace research-phase LLM API usage with a local Codex CLI bridge while keeping dealflow/social ingestion on the existing manual Grok path.

## Scope

- Keep manual Grok copy/paste workflows for X feed and social ingestion only.
- Replace research-phase analyst execution with local Codex CLI execution.
- Run four analyst jobs per ticker in parallel: `market`, `social`, `news`, `fundamentals`.
- Process tickers sequentially: finish all four analysts for one ticker before moving to the next ticker.
- Preserve downstream graph state and report contracts wherever possible.

## Non-Goals

- No OpenAI API integration.
- No xAI API integration.
- No rewrite of the downstream debate, trader, risk, or paper-execution stages in this phase.
- No global unlimited fan-out across all tickers.

## Approved Architecture

### 1. Split Responsibilities

There are two distinct execution lanes:

- **Dealflow/social lane:** manual Grok prompt generation and ingest remain the source of truth for X/social data.
- **Research lane:** the four research analysts run through a local Codex bridge authenticated with the operator's ChatGPT/Codex login.

This yields the operating model:

`Python app -> local codex tool -> result file -> Python app`

### 2. Ticker-Scoped Orchestration

The orchestrator loops through deep-analysis tickers sequentially. For each ticker:

1. Build one prompt per analyst.
2. Launch the four analyst Codex jobs in parallel.
3. Wait for all four result artifacts.
4. Validate and store the artifacts.
5. Continue to the next ticker.

This keeps concurrency bounded, supports simple per-ticker retries, and produces a complete research bundle before downstream processing.

### 3. Existing State Compatibility

The bridge writes analyst outputs into artifacts that map directly onto the graph's current state contract:

- `market_report`
- `sentiment_report`
- `news_report`
- `fundamentals_report`

Downstream debate, trader, scoring, and report generation should continue to consume these same state fields.

## Artifact Contract

Artifacts should live under:

- `results/{ticker}/{date}/codex_research/market.json`
- `results/{ticker}/{date}/codex_research/social.json`
- `results/{ticker}/{date}/codex_research/news.json`
- `results/{ticker}/{date}/codex_research/fundamentals.json`

Each artifact should contain:

- `ticker`
- `as_of_date`
- `analyst`
- `status`
- `model` (`gpt-5.4`)
- `reasoning_effort`
- `report_markdown`
- `sources`
- `metadata`

`metadata` should capture at minimum:

- `prompt_path`
- `started_at`
- `completed_at`
- `duration_seconds`
- `exit_code`
- `error`

## Prompt and Execution Model

Each analyst job should be isolated. The system should generate one prompt file and one output file per `{ticker, analyst}` pair. The Codex bridge should run the analyst using the local Codex CLI, then persist a structured JSON result for the pipeline to read.

The research lane should not silently fall back to Claude, xAI API, OpenAI API, or other vendor paths.

## Failure Handling

- If one analyst fails, retry only that analyst for the current ticker.
- If retries are exhausted, write a failed artifact with error metadata.
- A ticker should not be marked complete until all four analyst artifacts are present and valid.
- The bridge should hard-fail early if `codex` is not installed or not authenticated.

## Testing Strategy

Testing should focus on the new seam instead of broad graph rewrites:

- prompt generation tests
- Codex bridge command construction tests
- per-ticker parallel fan-out orchestration tests
- artifact validation and state-loading tests
- failure/retry tests
- end-to-end ticker bundle assembly tests

The manual Grok ingestion tests should remain intact and continue to anchor the dealflow/social lane.

## Deletion and Simplification Targets

This design makes the following cleanup directionally correct for later implementation phases:

- remove research dependence on `claude_cli`
- delete or replace `llm_quick` where it still hardcodes Claude
- remove dead routing scaffolding such as `model_router.py` if it remains unwired after the bridge is integrated

These deletions should happen only after the Codex bridge path is verified.

## Operational Policy

- Design and architecture decisions run under `GPT54-Strategist` / `extra-high`.
- Implementation can move to a lower reasoning setting after the plan is approved.
- Manual Grok remains the only approved social/dealflow X ingestion path.

## Success Criteria

The phase is successful when:

1. A deep-analysis ticker can produce all four analyst artifacts through local Codex CLI.
2. The pipeline can load those artifacts into the existing state contract.
3. The downstream analysis report continues to build without Claude/xAI/OpenAI API research calls.
4. Failures are explicit, auditable, and retryable per analyst.
