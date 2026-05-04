# Step 1 FVG Recall Channel Design

## Goal

Promote confirmed bullish FVG into Step 1 as a first-class recall channel so the funnel can preserve early trend names without making FVG a hard gate.

## Why

The replay evidence says confirmed FVG is promising as a discovery / escalation feature, but not as a standalone lifecycle trading system. The top-of-funnel problem is recall: Step 1 needs a cheap additional path that can surface future winners earlier without rewriting the whole universe build.

## Design

Add a dedicated FVG recall tier to the Step 1 universe build:

- keep the current universe tiers intact
- compute an FVG recall candidate set during `discover()`
- pass those symbols into the universe builder as a dedicated channel
- assign them a distinct tier label
- cap the channel with a fixed quota, default `30`

Initial confirmed rule:

- bullish FVG present
- `relative_strength_20d >= 0.03`
- `SMA50 > SMA200`

## Integration Shape

- `pipeline.py`
  - compute the FVG recall set before universe construction
  - persist a daily `fvg_recall.json` artifact
- `akg_universe.py`
  - accept FVG-selected symbols as a dedicated inclusion tier
  - include the tier in `tier_map`
  - record channel counts in the universe ledger snapshot
- `default_config.py`
  - add FVG recall feature flags and quota config

## Guardrails

- FVG is additive, not mandatory.
- Manual and portfolio guarantees remain stronger than FVG insertion.
- FVG channel should be fully measurable in the hypothesis ledger; no hiding it inside generic extras.

## Success Criteria

- FVG-only additions are visible and countable.
- The Step 1 universe remains deterministic.
- We can measure whether FVG additions improve future winner recall and reduce false-negative cost.
