# Research Conversion Integrity Design

## Goal

Add a read-only Step 5 artifact that measures whether deep-research budget actually turns into usable analysis, portfolio inclusion, and later forward returns.

## Why

Step 4 now measures who received deep-research budget.

The next question is whether those selected names actually convert into:

- usable `analysis_report.json`
- trustworthy `aeternus_score` output
- portfolio inclusion
- better later returns than quick-path or cached-path names

This is the first downstream layer where deep-selection can silently fail due to:

- timeouts
- quick-path substitution
- cached-report fallback
- failed analysis runs

## Scope

v1 is read-only and artifact-only.

It will:

- build `research_conversion_integrity.json`
- classify every `analyze-batch` row into execution/conversion cohorts
- optionally enrich with portfolio inclusion if a same-date portfolio plan exists
- reuse existing realized horizons from `analyze-batch` when present

It will not:

- change `analyze-batch`
- change `portfolio-plan`
- change graph execution
- add CLI review surfaces yet

## Insertion Point

The report is built after `analyze-batch` assembles and persists its batch summary in `cli/commands/scoring.py`.

Source artifacts:

- `batch_analyze_latest.json`
- optional `eval_results/paper_execution/plans/<date>/portfolio_plan_*.json`

Output artifact:

- `eval_results/deal_flow/<date>/research_conversion_integrity.json`

## Report Shape

Top-level fields:

- `as_of_date`
- `rule_snapshot`
- `group_counts`
- `candidate_records`
- `groups`
- `comparisons`
- `coverage_summary`

### rule_snapshot

- `requested`
- `processed`
- `include_unselected`
- `quick_unselected`
- `per_item_timeout_seconds`
- `portfolio_plan_found`

### candidate_records

Per symbol:

- `symbol`
- `selected_for_deep`
- `analysis_mode`
- `status`
- `analysis_report_found`
- `aeternus_score`
- `recommendation`
- `portfolio_included`
- `realized_horizons`
- `integrity_group`

### groups

- `deep_success`
- `deep_cached`
- `deep_failed`
- `quick_success`
- `quick_cached`
- `quick_failed`

Definitions:

- `deep_success`
  - `selected_for_deep = true`
  - `analysis_mode = DEEP`
  - status in fresh success states
- `deep_cached`
  - selected deep item succeeded only via cached fallback
- `deep_failed`
  - selected deep item ended failed / skipped without usable report
- `quick_success`
  - non-deep or quick path fresh success
- `quick_cached`
  - quick path reused cached report
- `quick_failed`
  - quick path failed / skipped without usable report

### comparisons

v1 comparisons stay simple:

- `deep_vs_quick`
  - count
  - usable-report rate
  - portfolio-conversion rate
- `fresh_vs_cached`
  - count
  - portfolio-conversion rate

### coverage_summary

- `candidate_count`
- `portfolio_included_count`
- `analysis_report_found_count`
- `realized_horizon_count`

## Testing

Add:

- pure helper test in `tests/test_research_conversion_integrity.py`
- focused command/helper persistence test in `tests/test_cli_dealflow.py`

The tests should prove:

- items are classified into the correct cohorts
- portfolio inclusion is detected from a same-date plan when present
- artifact persists into the dated deal-flow folder
- missing portfolio plan degrades cleanly

## Follow-On

After enough real cycles:

- add review scorecards to hindsight/performance review
- compare deep vs quick returns and portfolio conversion
- decide whether deep research is earning its budget
