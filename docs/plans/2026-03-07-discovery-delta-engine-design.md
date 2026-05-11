# Discovery Delta Engine Design

## Goal

Add a read-only `Discovery Delta Engine` to the discovery layer so scouts, `FVG_RECALL`, and `FMA_RECALL` can be normalized into a single state-change surface without changing Step 1 membership yet.

## Why

The current discovery layer has strong parts, but they still act like separate emitters:

- scout outputs are persisted in `scout_audit.json`
- `FVG_RECALL` and `FMA_RECALL` are now live additive Step 1 channels
- the universe builder can attribute which tier admitted a symbol

What is still missing is a common language for why a name is changing now. The next useful product step is not another filter. It is a read-only layer that can answer:

- which names are firing across independent channels
- which names are purely technical vs purely scout-driven
- which names look non-consensus because multiple independent signals agree

This has to be read-only first. If the Delta Engine is allowed to add names immediately, attribution gets muddied and the discovery spine becomes harder to reason about.

## Recommendation

Build `Discovery Delta` as a read-only integrated layer inside `discover()`:

- consume existing scout outputs
- consume `fvg_recall`
- consume `fma_recall`
- compute normalized symbol-level delta records
- persist a daily artifact
- expose a compact ranked summary

It should not alter:

- Step 1 quotas
- tier assignment
- downstream scoring
- candidate_list ranking

## Architecture

### New Module

Add a new module:

- `tradingagents/dealflow/discovery_delta.py`

This module should expose two pure primitives:

- `normalize_discovery_signals(...)`
- `build_discovery_delta(...)`

### Integration Point

In `DealFlowPipeline.discover()`:

1. build manual overlays
2. build `fvg_recall`
3. build `fma_recall`
4. run the existing scouts
5. build `scout_audit`
6. run `build_discovery_delta(...)`
7. build the filtered universe as usual

This keeps the Delta Engine close to the real discovery flow while staying read-only.

## Signal Contract

The first version should stay symbol-level.

### `DiscoveryDeltaSignal`

One record per `{date, symbol, source}`:

- `symbol`
- `source`
- `channel_type`
  - `scout`
  - `technical_recall`
- `delta_kind`
  - `breakout`
  - `iv_spike`
  - `insider_cluster`
  - `x_feed`
  - `fvg_recall`
  - `fma_recall`
- `direction`
- `raw_strength`
- `novelty_score`
- `persistence_score`
- `confidence_score`
- `tags`

### `DiscoveryDeltaRecord`

One aggregated record per symbol per run:

- `symbol`
- `sources_fired`
- `independent_channel_count`
- `novelty_score`
- `persistence_score`
- `orthogonality_score`
- `confidence_score`
- `delta_score`
- `technical_only`
- `scout_only`
- `multi_channel`
- `theme_tags`

## Scoring

Recommended first scoring formula:

- `35% novelty`
- `25% orthogonality`
- `20% persistence`
- `20% confidence`

Why this weighting:

- novelty answers whether something changed
- orthogonality answers whether independent sources agree
- persistence separates churn from follow-through
- confidence stops weak inputs from dominating

`theme_tags` may be attached as cheap AKG metadata, but there should be no theme-level scoring in v1.

## Artifacts

Persist:

- `eval_results/deal_flow/<date>/discovery_delta.json`

Contents:

- `as_of_date`
- `rule_snapshot`
- `signals`
- `symbol_records`
- `top_delta_symbols`
- `coverage_summary`
- `cohorts`
  - `scout_only`
  - `technical_only`
  - `multi_channel`

This artifact should be operator-readable and backtest-friendly.

## Guardrails

- no Step 1 promotion power in v1
- no hidden impact on tiering or ranking
- degrade gracefully on partial inputs
- preserve source attribution; do not collapse `FVG` and `FMA`

## Success Criteria

The first version is successful if:

- it runs on every discovery cycle without breaking universe build
- it produces a stable `discovery_delta.json`
- it explains which names are scout-driven, technical-driven, or multi-channel
- it gives us a ranked `top_delta_symbols` list worth reviewing
- after live cycles accrue, we can measure whether `multi_channel` names behave better than `technical_only` or `scout_only`

## Next After v1

Only after real cycles and scorecards:

1. add cohort-level hindsight / attribution
2. decide whether `Discovery Delta` deserves its own Step 1 quota
3. then consider theme / cluster-level scoring in a later version
