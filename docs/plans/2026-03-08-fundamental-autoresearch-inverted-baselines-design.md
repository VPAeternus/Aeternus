# Fundamental Autoresearch Inverted Baselines Design

Date: 2026-03-08

## Purpose

Test the hypothesis that negative `60d` rank IC for `growth_only` and `quality_only` should be interpreted as anti-signals, not as evidence that those factor families are useless.

## Design

- Keep the existing deterministic scorer path.
- Add inverted variants by complementing factor sub-scores (`100 - subscore`) rather than using raw negative totals.
- Preserve the current baseline suite and add a constrained inverted suite:
  - `growth_only_inverted`
  - `quality_only_inverted`
  - `growth_quality_inverted`
  - `health_minus_growth`
  - `health_minus_quality`

## Why Complement Instead Of Negative Weights

The scorer clamps the final score into a bounded range. Pure negative totals would collapse many rows toward zero and destroy relative ranking. Complementing each component preserves boundedness and keeps the comparison interpretable.

## Evaluation Contract

- Same historical dataset
- Same sector-neutral `60d` rank IC primary metric
- Same coverage / observation accounting
- No live pillar changes

## Success Criteria

- Confirm whether inverted growth/quality variants beat their positive counterparts
- Identify whether the best constrained blend is:
  - pure anti-growth/anti-quality
  - or health plus an inverted crowding component

## Expected Decision

If inverted variants dominate, the next search space should treat growth/quality as overexpectation/crowding variables rather than direct long signals.
