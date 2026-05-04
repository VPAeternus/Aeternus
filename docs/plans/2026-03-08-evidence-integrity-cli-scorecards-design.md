# Evidence Integrity CLI And Scorecards Design

## Goal

Make the read-only Step 2 Evidence Integrity layer operator-visible and review-measurable without changing current Step 2 admission behavior.

## Recommendation

Use the same rollout pattern as Discovery Delta:

- keep classification in `tradingagents/dealflow/evidence_integrity.py`
- add shared cohort scorecards there
- embed those scorecards into `hindsight.json` and `performance_review.json`
- render summaries in the existing CLI commands
- do not add a new artifact family
- do not change `ACTIVE` / `LOW_DATA`

## Scope

### In Scope

- Shared Evidence Integrity scorecards for:
  - `CONFIRMED`
  - `SPARSE_BUT_INTERESTING`
  - `DATA_DEGRADED`
  - `LOW_SIGNAL`
- Review artifact enrichment in:
  - `tradingagents/dealflow/hindsight.py`
  - `tradingagents/dealflow/performance_tracker.py`
- Operator CLI rendering in:
  - `cli/commands/dealflow.py`
  - `cli/commands/performance.py`
- Live operator summary rendering from `shortlist["evidence_integrity_summary"]`

### Out Of Scope

- Any Step 2 gate rewrite
- Any ranking or shortlist behavior change
- Any full per-candidate CLI dump by default
- Any new connector or new artifact family

## Data Model

The existing `evidence_integrity.json` remains the source artifact. The new review scorecard block will be:

- `evidence_integrity_cohorts`

Structure:

- `cohorts`
  - one row per integrity class
- `step2_baseline`
  - metrics across all Step 2 candidates
- `comparisons`
  - `vs_step2_baseline`
  - `vs_other_cohorts`

Metrics per cohort:

- `count`
- `mean_return_5d`
- `mean_return_20d`
- `mean_return_3m`
- `edge_vs_benchmark_5d`
- `edge_vs_benchmark_20d`
- `edge_vs_benchmark_3m`
- `shortlist_conversion`
- `deep_selection_conversion`

## CLI Surface

### Live Operator Flow

Render `Evidence Integrity` with:

- class counts
- top `SPARSE_BUT_INTERESTING`
- top `DATA_DEGRADED`

This should appear in the same general flow where live discovery/collect output is rendered.

### Review Flow

Render `Evidence Integrity Cohort Scorecards` in:

- `dealflow hindsight`
- `performance performance-review`

Show:

- cohort returns by horizon
- shortlist conversion
- deep-selection conversion
- deltas vs Step 2 baseline
- deltas vs peer cohorts

## Integration Points

### Shared Logic

Extend `tradingagents/dealflow/evidence_integrity.py` with:

- `build_evidence_integrity_scorecards(...)`

### Review Artifacts

Add scorecard embedding to:

- `tradingagents/dealflow/hindsight.py`
- `tradingagents/dealflow/performance_tracker.py`

### CLI Renderers

Add shared renderers in:

- `cli/common.py`

Wire them into:

- `cli/commands/dealflow.py`
- `cli/commands/performance.py`

## Testing Strategy

### Unit

- `tests/test_evidence_integrity.py`
  - scorecard rollups
  - baseline comparisons
  - peer comparisons

### Review Artifacts

- `tests/test_hindsight.py`
- `tests/test_performance_tracker.py`

### CLI

- `tests/test_cli_dealflow.py`

## Success Criteria

- Evidence Integrity stays read-only
- Existing Step 2 behavior remains unchanged
- CLI shows summary-level operator visibility
- Review artifacts include cohort scorecards
- Focused tests pass
