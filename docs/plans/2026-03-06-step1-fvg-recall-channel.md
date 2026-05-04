# Step 1 FVG Recall Channel Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add confirmed bullish FVG as a first-class capped recall channel in Step 1 without rewriting the rest of the universe builder.

**Architecture:** Compute an FVG recall set during discovery, thread it into the filtered universe as its own tier, and persist a dedicated artifact plus universe-ledger counts so the new channel can be scored like any other funnel bet.

**Tech Stack:** Python 3, pandas, pytest, Typer-free pipeline path

---

### Task 1: Add failing universe-tier tests

**Files:**
- Modify: `/Users/aeternusholdings/Documents/AeternusAgents-opus46/tests/test_dealflow_hypothesis_ledger.py`
- Modify: `/Users/aeternusholdings/Documents/AeternusAgents-opus46/tests/test_dealflow_pipeline.py`

**Step 1: Write failing tests**

- Add a test that `build_filtered_universe(...)` can assign a distinct FVG recall tier when passed FVG symbols.
- Add a test that `discover()` persists an `fvg_recall.json` artifact and threads the selected symbols into the built universe.

**Step 2: Run tests to verify they fail**

Run:

```bash
python3 -m pytest tests/test_dealflow_hypothesis_ledger.py tests/test_dealflow_pipeline.py -k 'fvg_recall' -v
```

### Task 2: Add config and universe-tier support

**Files:**
- Modify: `/Users/aeternusholdings/Documents/AeternusAgents-opus46/tradingagents/default_config.py`
- Modify: `/Users/aeternusholdings/Documents/AeternusAgents-opus46/tradingagents/dealflow/akg_universe.py`

**Step 1: Minimal implementation**

- Add:
  - `dealflow_fvg_recall_enabled`
  - `dealflow_fvg_recall_quota`
  - `dealflow_fvg_recall_min_rs20`
  - `dealflow_fvg_recall_min_liquidity_score`
- Extend the universe builder to accept FVG-selected symbols as a dedicated tier and include counts in `_last_universe_ledger`.

**Step 2: Run targeted tests**

```bash
python3 -m pytest tests/test_dealflow_hypothesis_ledger.py -k 'fvg_recall' -v
```

### Task 3: Compute and persist the FVG recall set during discovery

**Files:**
- Modify: `/Users/aeternusholdings/Documents/AeternusAgents-opus46/tradingagents/dealflow/pipeline.py`
- Modify: `/Users/aeternusholdings/Documents/AeternusAgents-opus46/tradingagents/dealflow/fvg_recall.py` only if a small helper extraction is needed

**Step 1: Minimal implementation**

- Add a helper that:
  - builds an investable Step 1 candidate universe from AKG company nodes
  - computes confirmed FVG recall candidates with the existing feature logic
  - selects the top `quota` names
- Write `eval_results/deal_flow/<date>/fvg_recall.json`
- Thread those symbols into `build_universe_from_akg(...)` as a dedicated channel

**Step 2: Run pipeline tests**

```bash
python3 -m pytest tests/test_dealflow_pipeline.py -k 'fvg_recall' -v
```

### Task 4: Run focused regression

**Files:**
- No additional code changes unless regressions fail

Run:

```bash
python3 -m pytest tests/test_dealflow_hypothesis_ledger.py tests/test_dealflow_pipeline.py tests/test_dealflow_lane_metadata.py tests/test_hypothesis_ledger.py tests/test_hypothesis_ledger_metrics.py -v
```

### Task 5: Document the rollout

**Files:**
- Modify: `/Users/aeternusholdings/Documents/AeternusAgents-opus46/memory/WORKING.md`
- Modify: `/Users/aeternusholdings/Documents/AeternusAgents-opus46/memory/2026-03-06.md`
- Modify: `/Users/aeternusholdings/Documents/AeternusAgents-opus46/memory/MEMORY.md` only if the architecture decision is durable enough to merit long-term memory

**Step 1: Capture what shipped**

- Note the FVG recall tier name
- Note the quota
- Note that it is additive and capped
- Note any remaining measurement gap before promotion beyond shadow mode
