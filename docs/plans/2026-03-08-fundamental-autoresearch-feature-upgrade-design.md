# Fundamental Autoresearch Feature Upgrade Design

## Goal

Improve the deterministic feature definitions inside the fundamental autoresearch harness so the next gains come from better signal truthfulness rather than a wider search loop.

The immediate target is to strengthen the current health-led model and make the growth/quality anti-signal interpretation more economically meaningful.

## Why This Slice

The current state is:

- the SEC + market-data harness is real
- baseline comparisons are real
- inverted baselines are real
- constrained search is real
- robustness is real
- constrained autoresearch is real

The current winner remains:

- `health_0p5__inv_growth_0p1__inv_quality_0p4`

Since the loop is already working and the winner did not change when formalized into autoresearch, the bottleneck is now feature quality rather than search machinery.

## Scope

### In Scope

- additive deterministic feature refinements in the prepared feature row builder
- updates to score usage where needed
- fixture-driven tests
- re-evaluation of baseline, inverted, constrained, and robustness outputs

### Out of Scope

- no new factor families beyond refined growth/quality/health
- no SEC fetch/schema changes
- no universe expansion
- no live fundamental pillar integration

## Feature Additions

### Growth

Replace naive “high growth is good” assumptions with more expectation-aware definitions:

- `revenue_growth_acceleration_pct`
- `fcf_growth_acceleration_pct`

These should reward improving growth rather than visible headline growth alone.

### Quality

Add a cleaner expectation-risk interaction:

- `margin_change_pct`
- `quality_valuation_tension`

This should help separate durable quality from expensive, already-loved quality.

### Health

Strengthen the currently winning health family:

- `liquidity_stress_score`
- `leverage_stress_score`

These should make the health family more explicitly about resilience and stress, not just generic “balance-sheet okay” signals.

## Architecture

Modify:

- `tradingagents/research/fundamental_autoresearch/features.py`

Keep:

- scoring API stable
- evaluation API stable
- search/autoresearch orchestration stable

If a feature cannot be derived cleanly from the current prepared row inputs, it should not be forced into this slice.

## Success Criteria

- feature builder remains deterministic and backward-compatible
- tests cover the new derived fields
- reruns show whether the upgraded features materially improve the best strategies
- if the upgrades do not improve signal quality, they should be easy to revert

## Validation Path

After implementation:

1. rerun baseline comparison
2. rerun inverted baseline comparison
3. rerun constrained search
4. rerun robustness on the new winner

The goal is not to prove the new features are clever.
The goal is to prove they improve the truth engine.
