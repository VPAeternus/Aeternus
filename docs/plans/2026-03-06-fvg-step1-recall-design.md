# FVG Step 1 Recall Design

**Date:** 2026-03-06

## Goal

Test whether bullish Fair Value Gap behavior can improve Step 1 recall for semis / AI leaders and near-leaders without turning Step 1 into indicator soup or a slow research system.

The immediate objective is not to rewrite live Step 1. The objective is to prove or reject a concrete hypothesis with point-in-time replay:

> Bullish FVG behavior, when combined with cheap confirmation features, can surface higher-upside names earlier than the current anchor-first Step 1 gate.

## Why This Matters

The current Step 1 and Step 2 stack is strongest at keeping liquid, already-visible names alive. It is weaker at catching early needles with sparse but powerful evidence. That is exactly the wrong failure mode for the stated mission:

- catch the next `+20% in 3 months`
- preserve the next `100x / 1000x` optionality
- reduce time from idea to validated product

The user's observation is that major trends tend to begin with a directional imbalance pattern, and that bullish FVGs often appear before sustained bullish trends. That is a good hypothesis, but not yet a rule. The system should prove it on its own data rather than encode it from conviction alone.

## Design Principles

- **Elon step order**
  - Do not rewrite Step 1 first.
  - Build the thinnest replay harness that can reject or validate the idea quickly.
  - Reuse existing technical/backtest surfaces where practical.
- **Karpathy constraints**
  - One small feature engine.
  - Point-in-time only; no lookahead.
  - Clear artifact outputs and tests.
  - Avoid overfitting through too many handcrafted rules.

## Recommended Shape

### 1. Narrow Replay First

Start with a narrow universe:

- semis leaders
- semis near-leaders
- AI infrastructure leaders
- adjacent AI-enabler names

This is the right first slice because:

- it matches the user's stated intuition
- it is where names like `NVDA`, `MU`, and `SNDK` matter most
- it minimizes implementation surface while still testing a real edge

This first version should be bullish-only.

### 2. Two Evaluation Modes From One Feature Engine

Use one shared point-in-time feature engine and evaluate it in two ways:

- **Event study**
  - each bullish FVG event becomes an observation
  - measure `5d / 20d / 60d / 90d` forward returns

- **Daily basket backtest**
  - each symbol/day gets an FVG recall score
  - rank the universe daily
  - evaluate the forward returns of the top `N`

Why both are needed:

- event study answers whether the pattern has predictive content at all
- basket backtest answers whether the pattern is useful for Step 1 selection

### 3. Mechanical FVG Definition

Use a strict, testable bullish FVG rule:

- bullish FVG on day `t` if `low[t] > high[t-2]`
- raw gap size = `low[t] - high[t-2]`
- normalize by ATR to avoid treating tiny gaps as meaningful
- apply a minimum normalized size floor

This keeps the rule deterministic and aligned with the existing phase-engine vocabulary already present in the repo.

### 4. Feature Set

Do not test "FVG present" alone as the Step 1 feature. Use a compact feature stack around it:

- `bullish_fvg_present`
- `fvg_size_atr`
- `same_direction_fvg_count_10d`
- `alternating_gap_count_10d`
- `gap_persistence_days`
- `price_above_gap_midpoint`
- `relative_strength_20d`
- `relative_strength_60d`
- `volume_zscore_20d`
- `distance_to_52w_high`
- `trend_alignment_20_50_200`

This maps directly to the hypothesis:

- trend ignition should show repeated same-direction imbalance plus follow-through
- chop should show alternating gaps and weak progress

### 5. Initial Score Model

Use an intentionally simple first-pass score:

- `35%` FVG quality
- `30%` relative strength
- `20%` trend structure
- `15%` volume confirmation

Where:

- FVG quality is built from presence, normalized size, persistence, and same-direction count

This is not meant to be the final production formula. It is the minimum score that can answer whether the observation has Step 1 value.

## Implementation Shape

### New Pure Module

Create:

- `tradingagents/dealflow/fvg_recall.py`

Responsibilities:

- load daily OHLCV for the target universe
- compute point-in-time bullish FVG features
- compute forward-return horizons
- build event rows
- build daily score rows
- summarize top-`N` basket results

### CLI Surface

Add:

- `aeternus fvg-backtest`

Recommended home:

- `cli/commands/technical.py`

Why:

- the repo already has technical/backtest commands there
- this keeps the new tool discoverable without creating another CLI silo

### Artifact Output

Persist results under:

- `eval_results/deal_flow/fvg_backtest/<run_date>/`

Files:

- `events.json`
- `daily_scores.json`
- `summary.json`

This keeps the first experiment inspectable and replay-friendly.

## What This Proves

If the experiment works, it proves:

- bullish FVG behavior has useful predictive content in the chosen narrow universe
- stacked with RS / trend / volume, it can rank likely winners better than chance
- it is worth promoting into the new Step 1 recall architecture as a feature family or channel

If it fails, that is still valuable:

- FVG is rejected or demoted before contaminating Step 1
- the system learns quickly instead of encoding trading lore by intuition

## What This Does Not Prove

- that FVG is a universal cross-sector law
- that FVG should be a hard gate
- that FVG-only should drive a live strategy
- that the chosen weights are production-ready

## Success Criteria

- deterministic bullish FVG detection with no lookahead
- event-level forward return stats for `5d / 20d / 60d / 90d`
- daily top-`N` basket results for the narrow universe
- one compact summary that shows whether FVG + confirmation is promising enough to graduate into Step 1 redesign work
