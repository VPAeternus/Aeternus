# FVG Regime And Confirmation Slice Design

**Date:** 2026-03-06

## Goal

Extend the bullish FVG replay harness so it answers two follow-up questions clearly:

1. In which simple market regimes does the bullish FVG signal hold up?
2. Which confirmation layers actually add value beyond raw FVG detection?

The objective is still evidence generation, not live Step 1 integration.

## Why This Matters

The first replay run over `1999-01-01 -> 2026-03-06` was promising on the narrow semis / AI universe, but the current summary is too aggregated. It does not yet tell us whether:

- the edge survives outside bullish tape
- relative strength, trend, and volume meaningfully improve raw FVG
- a live Step 1 promotion would be robust or just lucky in one dominant regime

This next slice should increase confidence without widening scope or inventing new infrastructure.

## Design Principles

- **Elon step order**
  - Do not promote FVG into live Step 1 yet.
  - Reuse the current replay harness and artifacts.
  - Add only enough slicing to answer the next decision.
- **Karpathy constraints**
  - Extend one module and one command.
  - Keep regime logic intentionally simple for this pass.
  - Keep the output compact and explainable.

## Recommended Shape

### 1. Simple Regime Split First

Use a deliberately lightweight market tag per date:

- `bull`
- `bear`
- `high_vol`

This is better than pulling in the repo’s full regime machinery immediately because:

- it gets a fast answer
- it reduces assumption load
- it makes the first interpretation easier

The richer regime system can be layered in later if the signal still looks strong.

### 2. Explicit Confirmation Slices

Do not rely on score buckets yet. Compare explicit cohorts:

- `raw_fvg`
- `fvg_plus_rs`
- `fvg_plus_rs_trend`
- `fvg_plus_rs_trend_volume`

This is the right next move because the business question is not only “does the final score work?” It is also:

- what ingredient is doing the work
- whether raw FVG is enough
- whether confirmation is required before any live funnel use

### 3. Output Shape

Extend `summary.json` with:

- `by_regime`
- `by_slice`

Optional deeper combinations like `by_regime_and_slice` should be deferred unless the simpler output leaves ambiguity. The first goal is readable diagnosis, not maximal granularity.

### 4. Decision Rule

After this pass:

- if `raw_fvg` is weak but `fvg_plus_rs_trend` is clearly stronger, FVG is a component rather than a standalone trigger
- if the edge collapses in `bear` or `high_vol`, the signal should be regime-aware, not universal
- if the top basket still holds up under stricter slices, the signal is a real candidate for future Step 1 recall channels
- if the edge disappears under slicing, FVG stays as research evidence, not a live gate

## Success Criteria

- one replay run produces understandable results for:
  - simple regime split
  - explicit confirmation slices
- output shows whether the first-run edge is robust or concentrated in one environment
- no changes to live Step 1 behavior
