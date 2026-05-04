# Task: S-084 — Earnings Families Weight Model (earnings_catalyst + forward_earnings_anticipation)

## Tier
opus (design decision — requires hindsight validation before implementation)

## Summary
Design and validate scoring weights for `earnings_catalyst` and `forward_earnings_anticipation` signal families, which currently emit signals that are silently discarded by the scorer.

## Context

Two connectors run in the pipeline and produce signals, but those signals have zero impact:

| Connector | Family | What it does | Status |
|---|---|---|---|
| `earnings_catalyst.py` | `earnings_catalyst` | Supply chain pre-positioning before customer earnings (FOXCONN before AAPL reports) | Signals emitted, silently dropped |
| `forward_earnings.py` | `forward_earnings_anticipation` | Forward anticipation from causal engine — predicted magnitude/direction for upcoming reporters | Signals emitted, silently dropped |

**Why they're dropped:** Neither family appears in `CORE_SCORE_WEIGHTS`, `CORE_SIGNAL_FAMILIES`, or `GATING_FAMILIES` in `scoring.py`. The scorer iterates `CORE_SIGNAL_FAMILIES` (line 76) and ignores everything else. These connectors burn CPU cycles and produce dead output.

### Why this is NOT a simple fix

Adding families to `CORE_SCORE_WEIGHTS` with non-zero weights **rebalances every existing ticker's score**. Current weights sum to 105.0 (including emergence at 7.0, value_overlay at 0.0). Adding two more families at any weight changes the denominator, shifting all existing scores.

Example: if both get weight 5.0, total goes from 105 → 115. Every existing family's effective contribution drops by ~8.7%. This could degrade ranking IC — the very metric we just fixed in the ranking audit.

### The correct sequence

1. **Add both families to `CORE_SIGNAL_FAMILIES` and `CORE_SCORE_WEIGHTS` with weight 0.0** — same pattern as value_overlay and the new iv_divergence. This makes signals visible in subscores without affecting ranking.

2. **Run ≥1 hindsight cycle with both families visible** — `aeternus hindsight <date>` computes 5-day forward returns for all shortlisted tickers. With the families in subscores, we can compute their individual ICs.

3. **Decide weights based on measured IC:**
   - IC > +0.20 → assign weight proportional to IC (suggested: IC × 25, capped at 10.0)
   - IC between -0.10 and +0.20 → keep weight 0.0 (not predictive enough)
   - IC < -0.10 → keep weight 0.0 and investigate (inverted signal, like core_score was)

4. **If weights assigned, rebalance total** — all weights should still sum to ~105 (the current effective total). Steal weight from the weakest existing family (likely `value_overlay` at 0.0, or `liquidity_tradability` at 5.0 if it has weak IC).

### What Already Exists
- Both connectors implemented and wired into pipeline parallel executor
- `contracts.py` already has both families in the `DealFlowSignal.signal_family` Literal (added in ranking audit R-C)
- Both have config gates: `dealflow_earnings_catalyst_enabled`, `dealflow_forward_earnings_enabled`
- `earnings_catalyst.py` uses AKG supply chain edges to find pre-positioning candidates
- `forward_earnings.py` reads from causal engine's forward anticipation scanner
- **Both have the `.load()` bug** (C-4 siblings) — fix that first (S-082 follow-up)

### NOT in Scope
- Fixing the `.load()` bug (mechanical fix, separate task)
- Changing connector internals
- Running the hindsight cycle (operator action, not code change)

## Requirements

### Phase 1: Observability (implement now)

1. Add `"earnings_catalyst"` and `"forward_earnings_anticipation"` to `CORE_SIGNAL_FAMILIES` tuple in `scoring.py`
2. Add both to `CORE_SCORE_WEIGHTS` with weight `0.0`
3. Do NOT add to `GATING_FAMILIES` — both cover a small subset of tickers (only those with approaching earnings + supply chain edges). Adding them to the gate would count as a family for evidence purposes, inflating evidence coverage for a narrow set.

### Phase 2: Weight assignment (after hindsight)

4. After ≥1 hindsight cycle with both families visible in subscores:
   - Compute per-family IC: `corr(subscore, 5d_return)` across all evaluated tickers
   - If IC > +0.20 for either family, assign weight = `round(IC * 25, 1)` capped at 10.0
   - Rebalance: reduce weakest existing family by the same amount added
   - Update `CORE_SCORE_WEIGHTS` with validated weights

### GATING_FAMILIES consideration

Both families should stay OUT of `GATING_FAMILIES` permanently. Rationale:
- `earnings_catalyst` only fires for tickers with AKG supply chain edges AND upcoming earnings — maybe 5-20 tickers per run
- `forward_earnings_anticipation` only fires for tickers in the causal engine's forward window — similar count
- Adding either to gating would give those 5-20 tickers a free pass toward the ≥3 family gate while the other 5,000 tickers don't benefit. This creates systematic selection bias toward earnings-adjacent names.

## Files to Touch (Phase 1 only)
- `tradingagents/dealflow/scoring.py` (4 lines: 2 in weight dict, 2 in families tuple)

## Acceptance Criteria

### Phase 1
- [ ] Both families appear in `CORE_SIGNAL_FAMILIES`
- [ ] Both appear in `CORE_SCORE_WEIGHTS` with weight 0.0
- [ ] Neither appears in `GATING_FAMILIES`
- [ ] Candidates with earnings catalyst signals show `earnings_catalyst` in subscores
- [ ] Candidates with forward anticipation signals show `forward_earnings_anticipation` in subscores
- [ ] All existing tests pass: `python -m pytest tests/test_dealflow_momentum.py tests/test_emergence_loop.py -v`
- [ ] No existing ticker scores change (weight 0.0 means zero impact)

### Phase 2 (after hindsight)
- [ ] IC computed for both families across ≥1 hindsight cycle
- [ ] Weight assigned only if IC > +0.20
- [ ] Total CORE_SCORE_WEIGHTS sum preserved at ~105.0 after rebalancing
- [ ] Ranking IC (momentum_score) does not degrade vs pre-change baseline

## Status
done (Phase 1 — observability. Phase 2 blocked on hindsight cycle.)

---

## Handoff
*Fill in when marking done. Opus reads this to parse completion without reading the implementation.*

**Work Done:** `scoring.py` — added earnings_catalyst (0.0) and forward_earnings_anticipation (0.0) to CORE_SCORE_WEIGHTS + CORE_SIGNAL_FAMILIES. Both families now appear in candidate subscores for hindsight validation without affecting ranking.

**Learnings:** none

**Follow-ups:** Run hindsight cycle → compute per-family IC → assign non-zero weights only if IC > +0.20. Both connectors also need the `.load()` fix (C-4 siblings) before they produce meaningful signals.
