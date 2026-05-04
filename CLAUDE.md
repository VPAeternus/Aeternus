# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Critical Rules

- Do not fabricate prices, costs, or financial figures. If you don't have real data, say so. Verify numbers against actual sources before presenting them.

## Project Overview

Aeternus (AeternusAgents) is a multi-agent LLM-powered investment research and ratings platform built on the TradingAgents framework (arXiv:2412.20138). Specialized AI agents collaborate via structured debate to produce investment decisions, scores, and portfolio plans.

## Build & Run

```bash
pip install -r requirements.txt                     # install
python -m pytest tests/ -v                           # all tests
aeternus workflow-run --mode auto --profile daily     # full pipeline
python -m cli.main score AAPL --format json           # single ticker
```

## Required API Keys

Set via `.env`: `OPENAI_API_KEY` (required), `ALPHA_VANTAGE_API_KEY` (required). Optional: `XAI_API_KEY`, `GOOGLE_API_KEY`, `ANTHROPIC_API_KEY`, `APCA_API_KEY_ID` + `APCA_API_SECRET_KEY` (Alpaca).

## Architecture (routing — read `docs/ARCHITECTURE.md` for full reference)

**Agent pipeline:** Data → Analysts (4) → Reviewers (4) → Researchers (bull/bear debate) → Trader → Risk → PM
**Workflow:** Deal Flow → Research Queue → Batch Analysis → Portfolio Plan → Execution → Reconciliation
**Config:** All in `tradingagents/default_config.py` as `DEFAULT_CONFIG` dict, env-var overridable.
**Entry point:** `TradingAgentsGraph.propagate(ticker, date)` returns a decision.

## Architecture / Domain Concepts

- **AKG is the single source of truth** for the ticker universe. Scouts feed discovery data INTO AKG. Connectors score FROM AKG. Do not suggest alternative universe sources or top-k filtering unless asked.
- **Scout vs Analyst:** Scouts are lightweight discovery/screening (fast, broad, 200-300 tickers). Analysts are deep research (thorough, narrow, per-ticker). Never conflate these roles.

## Code Changes

- When I say "delete" or "remove" code, fully delete it. Do not keep fallback logic, stubs, or compatibility shims unless I explicitly ask for them.

## Communication Style

- When I ask for data or analysis results, give me the raw data first. No narrative explanations unless I ask for interpretation.

## Model Orchestration

| Tier | Model | Assignment |
|---|---|---|
| **Architect** | Opus | System design, complex refactors, cross-cutting changes |
| **Builder** | Sonnet | Features, pipelines, connectors, API integrations |
| **Worker** | Haiku | Tests, utilities, boilerplate, simple fixes |

- Opus owns the plan and delegates. Always set `model` explicitly when spawning subagents.
- Ask: "What's the minimum model tier that can do this well?" Use that tier.

## Cross-Worktree Coordination

```
main (production)
  └── feature/opus46 (architect)
        ├── feature/sonnet46 (builder)
        └── feature/haiku45 (worker)
```

Task dispatch via `tasks/queue/`: `S-NNN-*.md` (Sonnet), `H-NNN-*.md` (Haiku).
Only Opus merges to main.

## Context Routing

- **Before coding:** Read `.claude/rules/karpathy.md` (non-negotiable)
- **Before planning:** Read `.claude/rules/workflow.md`
- **Financial domain work:** Read `.claude/rules/financial.md`
- **Session start:** Read `memory/WORKING.md` for current state
- **After corrections:** Update `tasks/lessons.md`
- **Architecture questions:** Read `docs/ARCHITECTURE.md`
