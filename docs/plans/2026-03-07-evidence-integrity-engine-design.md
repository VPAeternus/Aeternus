# Evidence Integrity Engine Design

**Date:** 2026-03-07

## Goal

Add a read-only Step 2 classification layer that evaluates all scored candidates as `CONFIRMED`, `SPARSE_BUT_INTERESTING`, `DATA_DEGRADED`, or `LOW_SIGNAL` without changing current `ACTIVE` / `LOW_DATA` behavior.

## Architecture

The engine sits after `score_candidates()` in `DealFlowPipeline` and consumes candidate rows, raw signal rows, and connector-health context from the current run. It produces a deterministic artifact `evidence_integrity.json` and an in-memory summary returned by `discover()` / `collect()` paths. It does not change shortlist membership, ranking, or queue logic in v1.

Core principle: classify evidence quality and missingness separately from opportunity quality.

## Inputs

- Step 2 candidates from `score_candidates()`
- Raw signals for the run
- Connector health summary / rows for the run
- Current rule snapshot (`min_signal_families`, `min_evidence_count`)

## Candidate Classes

- `CONFIRMED`
  - sufficient breadth and evidence count
  - low degradation signal
- `SPARSE_BUT_INTERESTING`
  - weak breadth but at least one strong/asymmetric family
  - should be preserved for review, not assumed weak
- `DATA_DEGRADED`
  - low/weak evidence state plausibly explained by connector or source degradation
- `LOW_SIGNAL`
  - weak breadth and weak asymmetry, with no convincing degradation explanation

## First-Pass Scores

Per candidate:
- `evidence_breadth_score`
- `evidence_quality_score`
- `degradation_score`
- `asymmetry_score`

Supporting fields:
- `missing_families`
- `degraded_families`
- `strong_families`
- `source_status_map`

## Artifact

Write `eval_results/deal_flow/<date>/evidence_integrity.json` with:
- `as_of_date`
- `rule_snapshot`
- `class_counts`
- `candidate_records`
- `top_sparse_but_interesting`
- `top_data_degraded`
- `connector_context`

## Non-Goals

- No Step 2 gate changes in v1
- No shortlist/ranking impact
- No new connectors
- No quota changes

## Success Criteria

- Every Step 2 candidate is classified
- The engine survives partial connector-health data
- Operators can inspect which `LOW_DATA` names are actually sparse vs degraded
- Review artifacts later can compare class outcomes without having changed current behavior
