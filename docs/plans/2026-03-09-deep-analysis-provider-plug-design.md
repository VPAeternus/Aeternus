# Deep Analysis Provider Plug Design

Date: 2026-03-09

## Goal

Make deep research explicitly choose its LLM stack at run time.

The system should stop hiding provider choice behind config fallbacks and instead expose:

- analyst provider
- post-analyst graph provider

The desired operating model is:

- LLMs are the plug
- prompts are the play

## Current Problem

Today's deep path is hybrid but implicit:

- 4 analyst reports use Codex CLI (`gpt-5.4`)
- the downstream post-analyst graph uses `claude_cli`

This is hard to audit because the operator does not choose the stack directly per run.

## Design

### Provider contract

Add two explicit run-time selections:

- `analyst_provider`
  - `gpt`
  - `claude`
  - `grok_manual`
  - `gemini` (placeholder, blocked in v1)
- `post_analyst_provider`
  - `gpt`
  - `claude`
  - `gemini` (placeholder, blocked in v1)

### GPT support

Add a `ChatCodexCLI` LangChain-compatible wrapper so the downstream LangGraph phase can use local Codex CLI the same way it already uses `ChatClaudeCLI`.

This makes GPT a true post-analyst plug rather than an analyst-only bridge.

### Analyst bundle support

Keep the existing analyst-bundle architecture, but make it provider-aware:

- `gpt` -> existing Codex bundle path
- `claude` -> new Claude CLI bundle path
- `grok_manual` -> manual prompt generation + ingest + readiness gate

### Manual Grok flow

Add a first-class CLI for manual analyst bundles:

- generate prompts
- ingest JSON per analyst
- check readiness

This should mirror the manual X-feed pattern.

### Defaults

Preserve current behavior by default:

- `research_analyst_provider = gpt`
- `research_post_analyst_provider = claude`

### Auditability

Every analyze/analyze-batch run should persist:

- analyst provider
- post-analyst provider
- actual models used
- whether manual artifacts were used

## Non-goals

- No Gemini execution in v1
- No live score-weight changes
- No change to research queue selection logic

## Success Criteria

- Provider choice is explicit per deep run
- GPT can power both analyst and post-analyst phases
- Claude can power both analyst and post-analyst phases
- Grok manual can power the analyst phase with a hard readiness gate
- Batch artifacts record the chosen stack clearly
