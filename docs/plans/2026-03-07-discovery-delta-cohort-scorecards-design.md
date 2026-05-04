# Discovery Delta Cohort Scorecards Design

## Goal

Measure whether `scout_only`, `technical_only`, and `multi_channel` discovery cohorts are actually better than each other and better than the Step 1 universe baseline.

## Recommendation

Add Delta cohort scorecards to the existing review artifacts:

- `hindsight.json`
- `performance_review.json`

Do not create a new artifact family.

Why:

- the platform already treats `hindsight` and `performance_review` as the operator review surfaces
- they already hold forward-return and benchmark context
- keeping Delta cohorts there makes the new layer measurable without adding reporting sprawl

## Design

### Cohorts

Use the three v1 Discovery Delta cohorts:

- `scout_only`
- `technical_only`
- `multi_channel`

### Metrics Per Cohort

For each cohort:

- `count`
- `mean_return_5d`
- `mean_return_20d`
- `mean_return_3m`
- `edge_vs_benchmark_5d`
- `edge_vs_benchmark_20d`
- `edge_vs_benchmark_3m`
- `shortlist_conversion`
- `deep_selection_conversion`

### Comparisons

Persist both:

- `vs_other_cohorts`
- `vs_step1_baseline`

This is necessary because a cohort can outperform the other cohorts while still being no better than the full kept universe, or vice versa.

## Insertion Points

### `hindsight.py`

Fast feedback path:

- compute `5d` cohort return stats
- compute benchmark-relative edge
- compute shortlist and deep-selection conversion

### `performance_tracker.py`

Richer horizon path:

- compute `5d`, `20d`, `3m`
- use this as the more complete source of truth when enough forward-return data exists

## Shared Helper

Add a small shared helper for cohort rollups, either in:

- `tradingagents/dealflow/discovery_delta.py`

or a nearby dedicated helper if the file starts growing too much.

Inputs should be:

- `discovery_delta.json`
- Step 1 kept-universe symbols
- shortlist symbols
- deep-selected symbols
- forward return maps
- benchmark return maps

The helper should return a deterministic dictionary ready to embed in the review artifacts.

## Guardrails

- no change to Step 1 behavior
- no new CLI requirement in this phase
- no new standalone artifact family
- missing Delta artifacts should degrade gracefully to an empty scorecard

## Success Criteria

After enough cycles, the system should be able to answer:

- whether `multi_channel` is materially stronger than the other cohorts
- whether any cohort beats the full Step 1 baseline
- whether a strong discovery cohort is getting suppressed by later funnel stages
