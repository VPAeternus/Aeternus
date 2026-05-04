# FMA Step 1 Recall Replay Design

## Goal

Test whether the existing `F=MA` momentum logic should be promoted into Step 1 as an additive recall channel, the same way confirmed FVG was promoted.

## Why

The `F=MA` system is already live downstream as the `price_momentum` family, but that does not prove it belongs in Step 1. Step 1 needs recall features that preserve future winners early; this replay must answer whether `F=MA` adds unique recall beyond FVG or mostly duplicates it.

## Design

Reuse the existing replay surface instead of creating a separate analytics subsystem.

Run two `FMA` variants:

- `fma_live`
  - the current production formula in `price_momentum.py`
- `fma_best_shadow`
  - the strongest historical IC variant from `backtest_price_momentum_ic.json`
  - `sma20_20d|W1_orig`

Run them in two universes:

- `semis_ai_narrow` vs `SMH`
- `qqq_top20_proxy` vs `QQQ`

## Outputs

For each universe / benchmark pair, produce:

- event-level forward-return summary at `20d / 60d / 90d`
- top-`N` daily basket summary
- basket edge vs benchmark
- overlap diagnostics versus the existing FVG replay:
  - `fvg_only`
  - `fma_only`
  - `fvg_and_fma`
  - `fvg_or_fma`

## Integration Shape

- Add a small `fma_recall.py` replay module under `tradingagents/dealflow/`
- Reuse the universe-resolution and artifact-location helpers from the FVG replay where practical
- Add a dedicated CLI command so the replay can be run without scripting
- Keep this isolated from live Step 1 behavior for now; this is evidence gathering, not production promotion

## Guardrails

- Do not assume downstream `price_momentum` success implies Step 1 suitability
- Do not rewrite the existing FVG replay
- Do not promote `accel_screener` as a Step 1 channel in this pass; it stays a downstream modifier unless replay evidence says otherwise

## Success Criteria

- `fma_live` and `fma_best_shadow` can be replayed apples-to-apples against the same universes used for FVG
- We can compare `FMA`, `FVG`, and their union on the same horizons and benchmarks
- The result is strong enough to decide whether `FMA_RECALL` deserves a capped Step 1 promotion trial
