# Deep Analysis Provider Plug Implementation Plan

Date: 2026-03-09

## Task 1: Config and contract

- add default config keys for:
  - `research_analyst_provider`
  - `research_post_analyst_provider`
  - Codex CLI deep/quick graph models and reasoning
- extend noninteractive selections to carry both provider choices

## Task 2: GPT post-analyst provider

- add `ChatCodexCLI`
- add `codex_cli` provider support to `TradingAgentsGraph`
- add focused unit tests

## Task 3: Analyst bundle provider switching

- make analyst bundle provider-aware
- add Claude CLI analyst execution
- add manual Grok generate/ingest/status flow
- add readiness handling for missing manual analyst artifacts

## Task 4: CLI wiring

- add `--analyst-provider`
- add `--post-analyst-provider`
- wire through `analyze` and `analyze-batch`
- persist stack metadata into batch summaries

## Task 5: Verification

- provider selection tests
- Codex CLI wrapper tests
- manual Grok ingest/readiness tests
- scoring bridge tests
