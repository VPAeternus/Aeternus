# Multi-Lane Probability Funnel Design

**Date:** 2026-03-06

**Goal**

Turn the existing deal-flow pipeline into a measured, self-correcting probability system that can:

- preserve future winners at the top of the funnel,
- split tactical and emergence opportunities before they crowd each other out,
- and score every filter cut as a kept-vs-dropped bet.

## Problem Statement

The current pipeline already has the right major pieces:

- AKG-backed universe and scout enrichment
- deterministic scoring and ranking
- fundamental review list and deep analysis
- hindsight, attribution, and post-trade review

What it does not yet have is a formal probability ledger around every major funnel cut.

Today, some learning exists, but it is uneven:

- some filters are measured only indirectly through artifacts,
- some thresholds are static config or operator-driven,
- and the current funnel optimizes mostly for one blended objective.

That is dangerous for needle-finding. A future 3-month winner and a future 100x-1000x emergence name should not have to survive the same early ranking logic.

## Design Principles

1. **Recall at the top, precision at the bottom**
   The top of the funnel should avoid killing future winners too early. The bottom of the funnel should spend research and capital only where expected value is strongest.

2. **Shared compute, split decisions**
   The full universe should share one cheap, deterministic feature update pass. Lane-specific logic should begin only after the shared recall scan.

3. **Every cut is a hypothesis**
   Every filter boundary should record who was kept, who was dropped, what rule caused it, and what happened later.

4. **Proxy-fast, truth-anchored**
   The emergence lane must learn on practical timescales using early proxies, but those proxies must remain anchored to realized forward returns.

5. **No rewrite first**
   The initial rollout should instrument the current funnel before it changes routing behavior.

## Approved Architecture

### L0: Shared Feature Store

One persistent per-symbol feature store for the full AKG-backed universe.

Minimum contents:

- liquidity and tradability
- AKG centrality and emergence tier
- scout hits and recent event flags
- price and relative-strength snapshots
- volatility and freshness features
- sector and asset-class metadata
- fundamentals acceleration proxy fields
- narrative ignition proxy fields
- portfolio/manual override flags

This layer should be cheap enough to update daily across 5,000+ names.

### L1: Shared Recall Scan

Every symbol receives multiple lane-oriented scores, not one master rank.

Minimum score vector:

- `upside_3m_score`
- `emergence_proxy_score`
- `anomaly_score`
- `narrative_ignition_score`
- `fundamentals_acceleration_score`
- `relative_strength_score`

This stage is for broad recall, not final ranking.

### L2: Lane Split

After the shared recall scan, the funnel splits into two explicit lanes.

#### 3-Month Upside Lane

Objective:

- find names likely to outperform materially over the next 1-3 months

Primary truth metrics:

- 5d edge
- 20d edge
- 1m / 3m forward return vs benchmark and peers

#### Emergence Lane

Objective:

- identify stocks progressing along the path of future large winners before broad market recognition

Fast proxy metrics:

- narrative ignition
- fundamentals acceleration
- relative strength leadership

Truth anchors:

- 1m / 3m / 6m forward outperformance
- future winner recall by stage
- false-negative cost by stage

### L3: Lane-Specific Triage

The `300 -> 30` reduction should be lane-specific.

Each lane gets:

- its own triage score
- its own quotas
- its own reserve logic
- its own scorecard

### L4: Research Escalation

Only here should the system spend expensive research budget.

The `30 -> 8` survivors get:

- compiled research packets
- analyst synthesis
- debate / trader / risk continuation

The analyst layer should synthesize from compiled evidence, not research from scratch.

### L5: Capital Allocation

Portfolio and execution decisions must keep lane identity attached to the position.

That enables later hindsight to answer:

- which lane is producing alpha,
- which filters inside that lane are working,
- and which lane-specific failure modes are leaking optionality.

## Hypothesis Ledger

Every major funnel stage should emit a ledger row per cycle, per lane.

### Stages to Track

- universe gate
- evidence gate
- candidate_list cut
- fundamental-intake cut
- portfolio inclusion cut

### Minimum Ledger Fields

- `run_id`
- `source_date`
- `lane`
- `stage_id`
- `rule_snapshot`
- `input_count`
- `kept_count`
- `dropped_count`
- `kept_symbols_path`
- `dropped_symbols_path`
- `kept_mean_return_5d`
- `dropped_mean_return_5d`
- `edge_5d`
- `edge_20d`
- `edge_3m`
- `future_winner_recall`
- `false_negative_cost`
- `sample_size`
- `recommended_adjustment`
- `applied_adjustment`
- `applied_by`

### Core Questions the Ledger Must Answer

- Did the kept names outperform the dropped names?
- Which filter produced the most false negatives?
- Which filter preserved the most future winners?
- Which thresholds are costing us the most optionality?
- Which lane is surfacing real value versus narrative noise?

## Manual vs Closed-Loop Controls

### Already Partially Closed-Loop

- X budget tuning from attribution
- IC-driven signal-weight deltas
- IC-driven sector overrides
- confidence calibration adjustments

### Still Primarily Manual or Operator-Driven

- manual watchlist insertion and reinforcement
- negative constraints
- run-profile selection
- evidence thresholds
- lane quotas
- deep-research quotas
- portfolio inclusion thresholds
- several timeout and fallback policies

The ledger exists to move more of these from intuition into measured adjustments.

## Rollout Plan

### Phase 1: Instrument Existing Funnel

Add the hypothesis ledger to the current funnel without changing route selection behavior.

Deliverables:

- ledger module and artifact contract
- logging for universe, evidence, candidate_list, fundamental-intake, and portfolio stages
- kept/dropped symbol snapshots

### Phase 2: Add Lane Metadata

Extend candidates and queue objects with lane feature fields and lane scores.

No routing split yet.

### Phase 3: Split at L2

Keep `L0` and `L1` shared, then branch into:

- `3-Month Upside Lane`
- `Emergence Lane`

### Phase 4: Analyst Packet Compiler

Build structured evidence packets for lane survivors before deep research.

### Phase 5: Controlled Auto-Correction

Auto-adjust only low-risk knobs first:

- evidence thresholds
- lane quotas
- candidate_list quotas
- fundamental-intake quotas
- score weights

Keep portfolio and exit rules manual until sample sizes are much stronger.

## Testing Strategy

- stage-level ledger write tests
- counterfactual metric tests for kept-vs-dropped edge
- future winner recall and false-negative cost tests
- lane metadata regression tests
- no-regression tests for current deal-flow and analysis commands

## Success Criteria

Phase 1 is successful when:

1. every major filter stage emits a ledger row,
2. every row can identify kept vs dropped symbols,
3. hindsight can answer which filter killed future winners,
4. the current funnel still runs without behavior drift.

The broader initiative is successful when:

1. the system can optimize separately for 3-month upside and emergence,
2. idea-to-product time drops because new filter ideas can be measured quickly,
3. future winner recall becomes a first-class optimization target,
4. the funnel learns faster than operator intuition alone.
