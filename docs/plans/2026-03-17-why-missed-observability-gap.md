# Why-Missed Observability Gap (Savepoint)

**Date:** 2026-03-17  
**Purpose:** Preserve current state before pivoting work.

## Context

We validated whether the new question investigation flow can answer:

- `Where did we miss?`
- `Why did we miss?`

## Current Truth

### What the system can answer reliably now

The system can usually identify **where** a symbol dropped out across stages:

- `scouts`
- `event_cards`
- `universe_filter`
- `collect`
- `shortlist`
- `deep_selection`

This is based on existing artifacts and stage presence checks.

### What is still not robust

The system cannot yet reliably answer **why** with stage-native precision.

In many cases we can say:
- symbol was absent at stage X

But we cannot yet always say:
- exact reject reason code
- threshold used
- observed value
- pass/fail delta

## Why This Matters

Without stage-native reject reasons, `question-investigate` can provide strong triage but only partial root-cause confidence for discovery-lane optimization.

## Data/Artifacts Already Available

Useful today:

- `scout_audit.json`
- `event_cards.json`
- `coverage_precheck.json`
- `universe_filter.json`
- `all_scored_candidates.json`
- `shortlist_top20.json`
- `research_queue.json`
- `hypothesis_ledger/*/rows.json`
- `why_missed` helper path

## Missing Instrumentation (Next Upgrade)

Add deterministic per-symbol stage rejection metadata:

1. `reason_code`
2. `reason_text`
3. `threshold`
4. `observed_value`
5. `delta_to_pass`

Suggested stage coverage:

- scouts
- event_cards
- universe_filter
- collect
- shortlist
- deep_selection

## Interim Position

- `question-investigate` is production-useful for **where** diagnostics.
- It is not yet fully authoritative for **why** diagnostics.
- Next high-leverage work is stage-level reject-reason instrumentation.

## Pivot Note

This file is the savepoint before switching to a different priority.
