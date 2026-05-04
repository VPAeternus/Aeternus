# Fundamental Autoresearch Constrained Autoresearch Design

## Goal

Add a deterministic, reproducible autoresearch-style search loop to the fundamental autoresearch harness that explores only the currently validated search space:

- positive `health`
- inverted `quality`
- inverted `growth`

The loop should improve the fundamental pillar truth engine without widening the factor space, introducing LLM calls, or affecting the live pillar.

## Why This Slice

The historical `2009+` `large_cap_v1` run already established:

- the naive composite is weak
- `health_only` is positive
- `growth` and `quality` behave better as anti-signals
- the best constrained blend so far is `health_0p5__inv_growth_0p1__inv_quality_0p4`
- that winner remains positive across horizons, eras, and sectors

So the highest-probability next move is no longer ingestion or unconstrained search. It is a controlled autoresearch loop inside the proven space.

## Scope

### In Scope

- deterministic search loop over bounded weight configurations
- artifacted leaderboard and best-strategy outputs
- optional robustness summaries for top candidates
- CLI command to run the loop on a prepared dataset

### Out of Scope

- no new factor families
- no full Karpathy-style open-ended mutation over arbitrary formulas
- no LLM calls
- no live pillar promotion
- no universe expansion beyond the current prepared dataset

## Search Space

The loop will only generate candidate strategies satisfying:

- `health > 0`
- `growth <= 0`
- `quality <= 0`
- `capital_discipline = 0`
- `valuation = 0`
- absolute weights sum to `1.0`
- `health` remains dominant via a lower bound

The first version should keep the same family as the current constrained search rather than invent a new formula DSL.

## Architecture

### New Module

Add:

- `tradingagents/research/fundamental_autoresearch/autoresearch.py`

Responsibilities:

- generate candidate strategies inside the constrained rules
- evaluate each candidate with the existing scorer/evaluator
- rank candidates by the existing primary metric
- optionally compute robustness for the top `N`
- return a deterministic experiment object

### Existing Modules Reused

- `score.py`
- `evaluate.py`
- `search.py`
- `robustness.py`
- `artifacts.py`

The new loop should orchestrate these, not replace them.

## Output Artifacts

Under:

- `eval_results/fundamental_autoresearch/<date>/<experiment>/`

Write:

- `leaderboard.json`
- `best_strategy.json`
- `autoresearch_summary.json`

If enabled for top candidates:

- `top_robustness.json`

## Evaluation Contract

Primary metric:

- `60d` sector-neutral rank IC

Required secondary fields:

- coverage ratio
- observation count
- winning weights
- top-`N` ranking

Optional robustness on the top set should include:

- `20d`
- `60d`
- `120d`
- `252d`
- era slices
- sector slices

## Guardrails

- deterministic only
- same dataset for all candidates
- no mutation outside the constrained factor family
- no dynamic benchmark changes
- no data prep changes inside the loop

## Success Criteria

- one command can run the constrained autoresearch loop on a prepared dataset
- outputs are reproducible and inspectable
- the best result is clearly ranked against the rest of the search space
- the implementation reuses existing harness primitives instead of forking logic

## Promotion Rule

This loop is still sidecar research infrastructure.

It should only justify the next step if:

- winners remain robust across horizons/eras/sectors
- results materially improve on the current constrained-search winner
- behavior is stable enough to justify a later, still-constrained promotion step
