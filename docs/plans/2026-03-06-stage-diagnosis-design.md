# Stage Diagnosis Design

**Date:** 2026-03-06

## Goal

Add a dedicated operator-facing CLI surface that answers one question quickly:

> Which funnel stages are currently destroying the most optionality and deserve attention first?

The design must optimize for faster learning loops and faster idea-to-product iteration, not for reporting completeness.

## Why This Matters

The hypothesis ledger now captures kept-vs-dropped behavior at each major funnel cut. That is useful, but still too raw for fast operator diagnosis. If an operator has to open individual `rows.json` files or inspect each cycle manually, the learning loop remains too slow.

The next step should therefore be a rolling diagnosis layer that:

- stays read-only
- uses the current review artifacts as the source of truth
- highlights which filters are costing the most future optionality
- recommends where to focus the next experiment

## Design Principles

- **Elon step order**
  - Do not add a new persisted data plane.
  - Reuse existing `hindsight.json` and `performance_review.json`.
  - Optimize for the shortest path from signal to operator action.
- **Karpathy constraints**
  - Add one thin module and one thin CLI command.
  - Keep the behavior deterministic and easy to test.
  - Avoid clever ranking logic that cannot be explained.

## Recommended Shape

### 1. Dedicated CLI Command

Add:

- `aeternus stage-diagnosis`

Why a dedicated command:

- cycle-specific commands remain cycle-specific
- rolling diagnosis becomes explicit and discoverable
- operator intent is clearer than overloading `hindsight-summary`

### 2. Artifact-Driven Aggregation

Create a pure aggregation module:

- `tradingagents/dealflow/stage_diagnosis.py`

It will:

- scan recent dated folders under `eval_results/deal_flow/`
- prefer `performance_review.json` when present because it has richer horizon coverage
- fall back to `hindsight.json` when only the 5d summary exists
- read `hypothesis_stage_summary`
- aggregate by `stage_id`

### 3. Metrics To Surface

For each stage:

- `cycles_seen`
- `sample_cycles`
- `avg_edge_5d`
- `avg_edge_20d`
- `avg_edge_3m`
- `avg_recall`
- `total_false_negative_cost`
- `avg_false_negative_cost`
- `worst_cycle_date`
- `worst_cycle_false_negative_cost`
- `priority_score`

### 4. Priority Heuristic

The ranking is intentionally practical rather than academic.

Highest weight:

- cumulative false-negative cost

Next:

- low future-winner recall

Then:

- negative medium-horizon edge (`20d`, then `3m`, then `5d` fallback)

This keeps the command focused on the real business question:

- which filter is likely suppressing the next winner earliest and most often?

### 5. CLI Output

Default table output:

- `Priority Ranking`
  - stage
  - cycles
  - recall
  - 5d edge
  - 20d edge
  - 3m edge
  - total FN cost
  - priority

- `Worst Recent Misses`
  - source date
  - stage
  - recall
  - 5d/20d/3m edge
  - false-negative cost

- `Current Diagnosis`
  - one short line naming the first stage to inspect next and why

JSON output should expose the same computed structure directly.

## Why This Is The Right Next Move

This does not change routing, scoring, or portfolio behavior.
It increases the speed of learning by making the operator-visible diagnosis immediate.

That is the right next step because:

- the ledger already exists
- the summaries already exist
- the next bottleneck is interpretation, not collection

## Out Of Scope

- no new DB tables
- no new persisted rollup artifact
- no auto-correction logic
- no lane-routing changes
- no dashboard work yet

## Success Criteria

- one command shows which stages are hurting recall most over recent cycles
- result comes entirely from existing review artifacts
- output is deterministic and tested
- no changes to current deal-flow execution behavior
