# Shortlist Integrity Design

## Goal

Measure whether Step 3 shortlist selection is preserving the right names and feeding the right downstream candidates without changing current ranking behavior.

## Recommendation

Build a read-only `Shortlist Integrity` layer that evaluates the shortlist boundary itself:

- compare `selected_shortlist` vs `near_miss_eligible`
- compare `selected_for_deep` vs `selected_shortlist`
- expose the strongest false negatives just below the cut

This should stay read-only in v1 and produce one artifact plus optional later review integration.

## Scope

### In Scope

- new read-only module:
  - `tradingagents/dealflow/shortlist_integrity.py`
- one new artifact:
  - `shortlist_integrity.json`
- comparisons between:
  - `selected_shortlist`
  - `near_miss_eligible`
  - `selected_for_deep`
- forward-return and downstream-conversion metrics
- `top_false_negatives`

### Out Of Scope

- ranking formula changes
- quota changes
- lane split changes
- deep-selection behavior changes

## Data Model

Artifact path:

- `eval_results/deal_flow/<date>/shortlist_integrity.json`

Contents:

- `as_of_date`
- `rule_snapshot`
- `groups`
  - `selected_shortlist`
  - `near_miss_eligible`
  - `selected_for_deep`
- `comparisons`
- `top_false_negatives`
- `coverage_summary`

Metrics per group:

- `count`
- `mean_return_5d`
- `mean_return_20d`
- `mean_return_3m`
- `edge_vs_benchmark_5d`
- `edge_vs_benchmark_20d`
- `edge_vs_benchmark_3m`
- `deep_selection_conversion`
- `portfolio_inclusion_conversion`

## Group Definitions

### selected_shortlist

Names that made the current top-`k` shortlist output.

### near_miss_eligible

Names immediately below the shortlist cut that still passed the basic candidate eligibility rules and therefore represent the best direct counterfactual set for the shortlist boundary.

### selected_for_deep

Subset of the shortlist that consumed the deeper research budget.

## Key Comparisons

- `selected_shortlist` vs `near_miss_eligible`
  - measures shortlist cut quality
- `selected_for_deep` vs `selected_shortlist`
  - measures whether the deep-selection layer adds value on top of the shortlist

## Operator Value

The most useful v1 operator output is `top_false_negatives`:

- names that missed the shortlist by a narrow margin
- later outperformed strongly
- should have received more attention

This is the cleanest way to learn faster from ranking mistakes without rewriting ranking immediately.

## Integration

Initial rollout should be artifact-only:

- build the artifact after shortlist and queue construction
- do not wire it into ranking behavior
- do not add a new CLI command until the artifact proves useful

## Success Criteria

- shortlist boundary quality becomes measurable
- deep-selection lift becomes measurable
- strongest near-miss false negatives are explicit
- no Step 3 behavior change in v1
