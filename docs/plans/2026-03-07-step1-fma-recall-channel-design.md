# Step 1 FMA Recall Channel Design

## Goal

Promote `F=MA` into Step 1 as a first-class additive recall channel so the funnel can preserve broad momentum / capital-flow winners without hiding them inside `FVG_RECALL`.

## Why

The replay evidence says `F=MA` is a real Step 1 candidate, but it behaves differently from `FVG`:

- `FVG` is the sharper ignition selector
- `F=MA` is broader and steadier
- the strict overlap is strong in narrow semis/AI, but too restrictive on larger-cap baskets

That means `F=MA` should be measurable on its own. Folding it into `FVG_RECALL` would destroy attribution and make future tuning harder.

## Design

Add a dedicated `FMA_RECALL` tier to the Step 1 universe build:

- keep the current universe tiers intact
- keep `T3B_FVG_RECALL` unchanged
- add `T3C_FMA_RECALL` as a separate additive inclusion tier
- compute an `FMA_RECALL` candidate set during `discover()`
- pass those symbols into the universe builder as their own channel
- cap the channel with its own fixed quota, default `20`

Initial live rule:

- `fma_score >= dealflow_fma_recall_min_score`
- asset class must be `Equity`
- liquidity score must satisfy the existing Step 1 investability floor

The first version should reuse the production `F=MA` formula already validated in replay. No variant grid, no extra confirmation gates, no rewrite of the broader Step 1 architecture yet.

## Integration Shape

- `pipeline.py`
  - compute the `FMA_RECALL` set during `discover()`
  - persist a daily `fma_recall.json` artifact
  - thread the selected symbols into the universe builder
- `akg_universe.py`
  - accept `fma_recall_symbols` as a dedicated inclusion tier
  - assign `T3C_FMA_RECALL`
  - record:
    - `fma_recall_selected_count`
    - `fma_recall_overlap_with_fvg_count`
    - updated `tier_counts`
- `default_config.py`
  - add:
    - `dealflow_fma_recall_enabled`
    - `dealflow_fma_recall_quota`
    - `dealflow_fma_recall_min_score`
- tests
  - extend existing Step 1 FVG tests to cover FMA artifact threading and ledger attribution

## Guardrails

- `FMA_RECALL` is additive, not mandatory.
- `FMA_RECALL` should not share quota or config with `FVG_RECALL`.
- overlap with `FVG_RECALL` is informative and should be counted, not collapsed.
- manual / portfolio guarantees remain stronger than both recall channels.

## Success Criteria

- `FMA`-added symbols are visible and countable in Step 1.
- overlap with `FVG_RECALL` is visible in the universe ledger snapshot.
- the Step 1 universe remains deterministic.
- after live cycles accrue, we can compare:
  - `FVG only`
  - `FMA only`
  - `FVG + FMA`
  - union-level recall and false-negative cost
