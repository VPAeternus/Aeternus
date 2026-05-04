# Task: S-083 — Wire IV Scanner Force Queue Into Pipeline Signals

## Tier
sonnet

## Summary
Feed IV scanner force_queue output into the pipeline signal list so IV divergence candidates reach scoring.

## Context

The IV scanner (`sources/iv_scanner.py`) already runs in the pipeline (`pipeline.py:179-191`). It:
1. Scans S&P 500 + Dow 30 from AKG for earnings in 7-14 days
2. Computes IV divergence (ATM straddle vs historical earnings surprise)
3. Classifies: UNDERPRICED / OVERPRICED / NEUTRAL
4. Writes enrichment to AKG via `enrich_node_iv()`
5. Persists `iv_force_queue.json` artifact
6. Returns results dict with `force_queue` list

**The bug:** `pipeline.py:185` prints the force_queue count and throws away the data:
```python
_fq = _iv_results.get("force_queue", [])
if _fq:
    print(f"[pipeline] IV scanner: {len(_fq)} force-queue candidates")
# ← _fq never used again
```

Force_queue items are dicts with keys: `ticker`, `implied_move_pct`, `historical_move_pct`, `divergence`, `signal`, `earnings_date`, `action`. These are NOT in DealFlowSignal format. They need transformation before entering the signals list.

### Design Decision: Signal Family

IV divergence is a distinct signal type — not covered by any existing family. Options:

**Option A (recommended): New family `iv_divergence`**
- Add to `CORE_SIGNAL_FAMILIES` so it counts toward evidence gate
- Add to `CORE_SCORE_WEIGHTS` with weight **0.0** initially (observability only)
- Do NOT add to `GATING_FAMILIES` (it covers <50 tickers, shouldn't gate 5K universe)
- Weight stays 0 until a hindsight cycle validates its forward IC
- This lets IV signals appear in candidate subscores for manual review without affecting automated ranking

**Option B: Piggyback on `emergence`**
- Rejected. IV divergence is not emergence — it's a specific event catalyst. Mixing them muddies the emergence signal.

**Why weight=0 initially:** We have no hindsight data on IV divergence's predictive value. The correct sequence is: emit signals → observe in subscores → run hindsight → assign weight based on measured IC. Same approach we used with value_overlay (weight=0 until validated).

### What Already Exists
- `iv_scanner.py` — complete, writes to AKG, returns force_queue list
- `scoring.py` — `CORE_SCORE_WEIGHTS`, `CORE_SIGNAL_FAMILIES`, `GATING_FAMILIES`
- `contracts.py` — `DealFlowSignal` TypedDict (already has `iv_divergence` would be a new family... wait, no — we just added `earnings_catalyst` and `forward_earnings_anticipation` in R-C. We'd need to add `iv_divergence` too)
- `pipeline.py:179-191` — IV scanner call site

### NOT in Scope
- Assigning a non-zero weight (needs hindsight cycle first)
- Covered call signal handling (separate overlay, not deal flow)
- Changing IV scanner internals

## Requirements

1. **Transform force_queue items to DealFlowSignal format** in `pipeline.py` after line 185:
   - `symbol` = item `ticker`
   - `signal_family` = `"iv_divergence"`
   - `raw_score` = map divergence to 0-100 scale. Suggested: `min(100, max(30, divergence * 140 + 50))` — UNDERPRICED (divergence > 0.3) maps to ~92, NEUTRAL maps to ~50
   - `z_score` = 0.0 (single-source, no z-scoring needed)
   - `direction` = `"BULLISH"` if signal == `"UNDERPRICED"` else `"BEARISH"` if signal == `"OVERPRICED"` else `"NEUTRAL"`
   - `evidence_count` = 3 (straddle price + historical surprise + earnings date — three distinct data points)
   - `freshness_hours` = 0.0 (computed live)
   - `source_status` = `"OK"`
   - `source_name` = `"iv_scanner"`

2. **Append transformed signals to `signals` list** before the `score_candidates()` call.

3. **Add `"iv_divergence"` to `CORE_SIGNAL_FAMILIES`** in `scoring.py` so it appears in subscores.

4. **Add `"iv_divergence": 0.0` to `CORE_SCORE_WEIGHTS`** in `scoring.py` — weight zero, observability only.

5. **Do NOT add to `GATING_FAMILIES`** — IV covers <50 tickers per run, shouldn't count toward the ≥3 family gate for the other 5,000.

6. **Add `"iv_divergence"` to `DealFlowSignal.signal_family` Literal** in `contracts.py`.

## Files to Touch
- `tradingagents/dealflow/pipeline.py` (~10 lines added after line 185)
- `tradingagents/dealflow/scoring.py` (2 lines: weight dict + families tuple)
- `tradingagents/dealflow/contracts.py` (1 line: add to Literal)

## Acceptance Criteria
- [ ] IV scanner force_queue items appear in `signals_raw.json` with `signal_family: "iv_divergence"`
- [ ] Candidates with IV divergence show `iv_divergence` in their subscores dict
- [ ] `CORE_SCORE_WEIGHTS["iv_divergence"]` == 0.0 (no scoring impact yet)
- [ ] `"iv_divergence"` NOT in GATING_FAMILIES
- [ ] All existing tests pass: `python -m pytest tests/test_dealflow_momentum.py tests/test_emergence_loop.py tests/test_iv_scanner.py -v`
- [ ] New test: construct a mock force_queue item → transform → verify DealFlowSignal shape

## Status
done

---

## Handoff
*Fill in when marking done. Opus reads this to parse completion without reading the implementation.*

**Work Done:** `pipeline.py` (transform force_queue → iv_divergence signals, append to signals list), `scoring.py` (added iv_divergence to CORE_SCORE_WEIGHTS at 0.0 + CORE_SIGNAL_FAMILIES), `contracts.py` (added iv_divergence to signal_family Literal). IV scanner output now flows through scoring as observability-only signals.

**Learnings:** none

**Follow-ups:** After hindsight cycle, compute iv_divergence IC and assign weight if > +0.20.
