# Learning Loop and Observed Edges Design

**Date:** 2026-03-12

## Goal

Make the daily workflow produce hindsight and signal-family IC rows on every eligible cycle, safely write measured source quality back into live scoring weights, add a small high-precision observed-edge pass to the AKG, and persist scout/source attribution so each discovery family can be judged by realized edge.

## Decision

The workflow will be **fail-open for learning** and **fail-closed for corrupted weight outputs**.

- If hindsight, IC computation, or weight writeback cannot complete, the daily workflow still finishes and records `learning_status=DEGRADED`.
- Live scoring continues to use the last known good weight file.
- New weights are only written when the full hindsight -> IC -> validation -> save chain succeeds.
- If the last known good weight file is missing or a newly computed weight file is malformed, the learning phase is marked `BLOCKED` and the weight file is not updated.

## Why

- Daily run volume is a prerequisite for compound learning.
- Hindsight is a back-half feedback function, not a same-day market-readiness gate.
- Failing the entire workflow on a hindsight miss would reduce the exact sample volume needed to improve the system.
- Weight corruption is different: that can poison live scoring and must be blocked.

## Scope

This design covers four changes:

1. Automatic learning phase in `workflow-run`
2. Adaptive signal/ensemble weight writeback
3. High-precision observed edge builders
4. Scout/source attribution persistence and review

It does not redesign the core deal-flow funnel, research engine, or execution layer.

## 1. Workflow Learning Phase

### Current state

- `compute_hindsight(...)` and `compute_performance_review(...)` exist as standalone utilities.
- `workflow-run` does not invoke them as part of the daily cycle.
- Operators can manually inspect performance, but the learning path is not guaranteed to run.

### New behavior

At the end of `workflow-run`, after planning/execution/sync, add a `learning` step:

1. Run hindsight for the workflow date
2. Run performance review for the workflow date
3. Attempt weight writeback from the new IC rows
4. Optionally add observed edges from the day’s artifacts
5. Persist a learning summary artifact and embed it into the workflow artifact

### Status model

- `OK`
  - hindsight and performance review succeeded
  - IC rows persisted
  - weight writeback succeeded or was intentionally skipped because data was insufficient
- `DEGRADED`
  - workflow finished, but hindsight/performance/writeback did not fully complete
  - prior weights remain active
- `BLOCKED`
  - learning output was malformed or unsafe to activate
  - prior weights remain active

### Artifact

Create a small per-date artifact, for example:

- `eval_results/deal_flow/<date>/learning_status.json`

Fields:

- `source_date`
- `learning_status`
- `hindsight_status`
- `performance_status`
- `weight_update_status`
- `last_good_weight_update_date`
- `observed_edges_added`
- `warnings`

## 2. Adaptive Weight Writeback

### Current state

- `compute_performance_review(...)` already writes `signal_family_ic` rows into the hindsight DB.
- `EnsembleWeightStore.update_weights(...)` is still a stub.
- Deal-flow scoring already supports dynamic score weights from config-style overrides, but nothing writes them automatically.

### Design choice

Separate two kinds of adaptation:

1. **Deal-flow signal-family weights**
   - Source of truth: `signal_family_ic`
   - Target: a new control artifact consumed by deal-flow scoring, for example:
     - `eval_results/control/ic_signal_weights.json`
2. **Top-level ensemble weights**
   - Source of truth: mapped pillar ICs or later richer attribution
   - Target:
     - `eval_results/control/ensemble_weights.json`

The first slice should be conservative:

- Fully automate **deal-flow signal-family weight writeback**
- Make **ensemble weight writeback** safe and incremental rather than aggressive

### Writeback policy

- Use rolling recent cycles, not a single day
- Require a minimum sample count before applying changes
- Clamp all deltas to small increments
- Never flip signs aggressively from one noisy cycle
- Persist metadata:
  - lookback window
  - sample counts
  - per-family IC
  - update reason

### Activation rules

- If there is insufficient data, keep previous weights and log `SKIPPED_INSUFFICIENT_DATA`
- If a candidate weight file fails validation, reject it and log `BLOCKED_INVALID_OUTPUT`
- Only activate a new file after validation succeeds

## 3. High-Precision Observed Edge Builders

### Current state

- The AKG supports rich edge types and propagation.
- The graph is still dominated by seed relationships.
- Edge count alone is not the target; decision-useful observed edges are.

### First slice

Add one small daily observed-edge pass with high precision and cheap inputs:

1. **Manual X-feed repeated co-mention edges**
   - If two tickers appear together across multiple merged X-feed entries/themes on the same day, add or reinforce a weak observed edge
   - Relationship:
     - `co_mentioned`
2. **News/article repeated co-mention edges**
   - Reuse existing social/news artifacts when two names recur together in the same article-level evidence
   - Relationship:
     - `co_mentioned`
3. **Catalyst beneficiary edges from explicit manual evidence**
   - When manual X-feed or earnings/options scout explicitly ties a ticker to a theme or beneficiary relationship, reinforce:
     - `catalyst_beneficiary`

### Exclusions

- No raw correlation edge builder in this slice
- No transcript parser in this slice
- No broad LLM-inferred edge synthesis in this slice

This keeps the first observed-edge pass high precision and operationally cheap.

## 4. Scout/Source Attribution

### Current state

- The system now has partial missed-opportunity and cohort tools.
- Attribution is still fragmented across discovery artifacts and hindsight utilities.

### New behavior

Persist one normalized per-ticker source/scout attribution artifact for each cycle:

- `eval_results/deal_flow/<date>/source_attribution.json`

Per ticker, persist:

- `symbol`
- `discovery_sources`
- `discovery_stage_hits`
- `collector_families_present`
- `entered_shortlist`
- `selected_for_deep`
- `entered_plan`

This becomes the join surface for hindsight and source-level review.

### Review outputs

Use hindsight/performance rows to produce:

- source hit-rate summaries
- source average edge summaries
- source false-negative summaries

The key idea is: each scout family is judged by realized edge, not by operator intuition.

## Error Handling

- Missing hindsight window:
  - mark `DEGRADED`
  - skip writeback
- Missing or malformed artifacts:
  - mark `DEGRADED`
  - preserve prior weights
- Malformed weight candidate:
  - mark `BLOCKED`
  - preserve prior weights
- Observed-edge builder failure:
  - mark warning only
  - do not fail workflow

## Testing Strategy

1. Workflow tests
   - verify `workflow-run` records `learning` status
   - verify degraded learning does not fail the whole workflow
   - verify malformed weight output blocks activation
2. Weight tests
   - verify IC rows produce bounded weight deltas
   - verify insufficient data skips updates
   - verify saved weights are valid and reloadable
3. Edge tests
   - verify repeated same-day co-mentions create/reinforce edges
   - verify edge builder is idempotent
4. Attribution tests
   - verify source attribution artifact contains expected per-ticker sources/stages
   - verify hindsight can summarize source-level edge

## Success Criteria

- Every completed workflow cycle attempts hindsight/performance review automatically
- Eligible cycles persist `signal_family_ic` rows without manual intervention
- Weight files update safely from measured IC or explicitly record why they did not
- The workflow artifact clearly exposes `learning_status`
- The AKG gains daily observed edges from real evidence, not only seeds
- Each scout/source family can be evaluated by realized edge over time
