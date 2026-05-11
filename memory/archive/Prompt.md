# Aeternus Prompt (Durable Project Brief)

## Mission

Build the Aeternus Investment Intelligence Platform: institutional-quality, transparent investment intelligence accessible to non-institutional users.

## Product Objective

Deliver a full investment operating stack where:
1. Deal Flow sources high-quality investable ideas.
2. Research converts ideas into auditable recommendations.
3. Portfolio Construction allocates by conviction and risk.
4. Execution places paper/live orders via API.
5. Hedging continuously controls portfolio beta/VaR/drawdown risk.

## Current Scope (Execution Priority)

1. **Deal Flow Team (Priority 1 upstream bottleneck)**
2. **Research + Recommendation Team**
3. **Portfolio Construction Team**
4. **Execution Team**
5. **Independent Hedging Team**

## Canonical Scoring Spec

`AETERNUS_SCORE` is a weighted combination:
- fundamental: 30%
- technical: 25%
- macro: 20%
- sentiment: 15%
- momentum: 10%

Rating bands:
- 80-100: Strong Buy
- 60-79: Buy
- 40-59: Hold
- 20-39: Sell
- 0-19: Strong Sell

## Deliverables (Program-Level)

1. Deterministic daily deal-flow candidate_list (Top-20) with auditable evidence.
2. Two-pass research pipeline (triage then deep-research 6-8 names).
3. Traceable recommendation -> portfolio decision -> execution event chain.
4. Risk overlay with adaptive hedging and explicit rebalance controls.
5. Publicly inspectable track record and audit history.

## Non-Negotiables

1. Determinism where possible (thresholds, formulas, gates).
2. No silent failures in critical paths.
3. Auditability for every recommendation and lifecycle event.
4. Backward compatibility for existing CLI flows unless explicitly deprecated.
5. Tests required for every new module and integration path.

## Source Of Truth Links

1. Tactical state: `memory/WORKING.md`
2. Long-term architecture context: `memory/MEMORY.md`
3. Canonical architecture DeepWiki: `memory/DeepWiki_System_Architecture.md`
4. Active roadmap: `memory/Plans.md`
5. Decision ledger and progress status: `memory/Documentation.md`
