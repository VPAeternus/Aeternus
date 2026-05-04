# Codex Session Handoff

Date: 2026-03-09
Workspace: `/Users/aeternusholdings/Documents/AeternusAgents-codex`
Branch: `codex/review-main`
HEAD: `1cd50dbc` (`feat: checkpoint pipeline integrity and SEC shadow system`)

## Start Here

Open these first:
- [memory/WORKING.md](/Users/aeternusholdings/Documents/AeternusAgents-codex/memory/WORKING.md)
- [docs/research/aeternus-daily-pipeline-debug-runbook.md](/Users/aeternusholdings/Documents/AeternusAgents-codex/docs/research/aeternus-daily-pipeline-debug-runbook.md)
- [eval_results/deal_flow/2026-03-09/fundamental_factor_shadow.json](/Users/aeternusholdings/Documents/AeternusAgents-codex/eval_results/deal_flow/2026-03-09/fundamental_factor_shadow.json)
- [eval_results/deal_flow/2026-03-09/shadow_challenge_recommendation.md](/Users/aeternusholdings/Documents/AeternusAgents-codex/eval_results/deal_flow/2026-03-09/shadow_challenge_recommendation.md)

## What Is Already Implemented

- Step 1-5 read-only integrity layers:
  - Discovery Delta
  - Evidence Integrity
  - Shortlist Integrity
  - Deep Selection Integrity
  - Research Conversion Integrity
- Manual X-feed workflow gating:
  - `x-feed --status`
  - manual-mode workflow blocks until all 15 passes exist
- Deep-analysis provider plug model:
  - `analyst_provider = gpt | claude | grok_manual`
  - `post_analyst_provider = gpt | claude`
- Shared market cache for collector hot paths
- SEC fundamental autoresearch harness:
  - SEC cache/fetch
  - 2009+ historical filing backfill
  - return attachment
  - baseline comparisons
  - inverted baselines
  - constrained search / autoresearch
  - robustness
  - signal registry
- Live SEC connector is registry-driven and shadow-only:
  - `fundamental_factor_shadow`

## Current Fundamental Shadow Truth

Active broad-universe shadow strategy:
- `health_0p4__inv_quality_0p6`

Interpretation:
- prefer stronger financial health
- penalize obvious/crowded “quality”
- this is a shadow observation tool, not a promoted live scoring family yet

## Most Important Current Live Read

The shadow SEC signal is surfacing a different opportunity set from the live funnel.

Top shadow-only challenge names:
- `AAOI`
- `AMPX`
- `RKLB`

If forcing deep-research challenges today, these should displace maintenance/injected names first:
- `AXP`
- `BMY`
- `JNJ`

If only pressuring the shortlist boundary, weakest current shortlist names to challenge first:
- `HAL`
- `FCX`
- `XOM`
- `UPS`

## What Not To Waste Time On

Do not continue:
- tiny Qwen weight retuning loops
- tiny Qwen feature-overlay loops

Why:
- those search spaces saturated
- deterministic search already learned the useful answer there

## Recommended Next Step

Run a fresh `collect`, then inspect:
- shadow top names
- shortlist
- selected-for-deep

The immediate decision is whether to create a real shadow challenge sleeve for:
- `AAOI`
- `AMPX`
- `RKLB`

After that, the next engineering step should be moving Qwen to a higher-value search surface:
- sector-specific formulas
- horizon-specific formulas
- broader-universe bounded proposals
- residual filing-text features

## Daily Debug Order

Use this every run:
1. X-feed readiness
2. `discover`
3. first universe filter audit
4. `collect`
5. second filter / shortlist / research queue audit
6. deep analysis
7. hindsight / performance / stage diagnosis

## Operational Note

There is a safety stash in this clone from the prior local codex state:
- `stash@{0}: pre-sync-local-state`

Do not pop it unless you explicitly want to inspect that older local state.
