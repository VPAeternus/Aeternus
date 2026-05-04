# Deep Selection Integrity Design

## Goal

Add a read-only Step 4 integrity artifact that measures the deep-research selection boundary without changing current `deep_k`, quota, or injection behavior.

## Why

Step 4 is where scarce deep-research budget is allocated. We already instrument:

- Step 1: discovery / universe recall
- Step 2: evidence integrity
- Step 3: shortlist integrity

The next question is whether `selected_for_deep` is actually better than the strongest eligible names that were left out, and whether manual / IV / held-position injections are improving or distorting that boundary.

## Scope

v1 is read-only and artifact-only.

It will:

- persist `deep_selection_integrity.json`
- classify selected names into:
  - `auto_selected`
  - `manual_selected`
  - `iv_force_selected`
  - `portfolio_selected`
- expose:
  - `selected_for_deep`
  - `near_miss_eligible`
  - `injected_selected`
  - `top_false_negatives`

It will not:

- change `deep_k`
- change quotas
- change `_select_for_deep`
- change manual / IV / held-position guarantees
- add CLI surfaces or review scorecards in v1

## Insertion Point

The artifact is built after `_build_research_queue(...)` in `tradingagents/dealflow/pipeline.py`, using:

- Step 3 shortlist output
- Step 4 research queue output

and written beside:

- `shortlist_integrity.json`
- `evidence_integrity.json`

under:

- `eval_results/deal_flow/<date>/deep_selection_integrity.json`

## Report Shape

Top-level fields:

- `as_of_date`
- `rule_snapshot`
- `groups`
- `comparisons`
- `top_false_negatives`
- `coverage_summary`

### rule_snapshot

- `deep_k`
- `selected_count`
- `near_miss_limit`
- `auto_selected_count`
- `manual_selected_count`
- `iv_force_selected_count`
- `portfolio_selected_count`

### groups

- `selected_for_deep`
- `near_miss_eligible`
- `injected_selected`

### selected_for_deep rows

Per selected symbol include:

- `symbol`
- `lane`
- `triage_score`
- `deal_flow_score`
- `source`
- `source_detail`
- `selection_kind`

### near_miss_eligible rows

Names in the research queue that were not selected, sorted by strongest miss:

- descending `triage_score`
- then fresher evidence

These should include:

- `symbol`
- `lane`
- `triage_score`
- `deal_flow_score`
- `source`
- `source_detail`

### injected_selected rows

Selected names whose Step 4 inclusion came from a non-auto path:

- `MANUAL`
- `IV_FORCE_QUEUE`
- `PORTFOLIO`

### comparisons

v1 stays simple:

- selected count vs near-miss count
- injected-selected count vs selected count

### top_false_negatives

Top 5 names from `near_miss_eligible` with strongest triage scores.

## Testing

Add:

- pure report test in `tests/test_deep_selection_integrity.py`
- pipeline persistence test in `tests/test_dealflow_pipeline.py`

The tests should prove:

- selected names are classified correctly
- near misses are limited and ordered correctly
- injected selections are separated correctly
- artifact persists in the standard dated deal-flow folder

## Follow-On

After enough real cycles:

- promote to review scorecards
- compare selected vs near-miss on returns and downstream conversion
- decide whether Step 4 behavior should change
