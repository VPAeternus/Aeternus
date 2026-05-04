# Step 1 FMA Recall Channel Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add `FMA_RECALL` as a separate capped Step 1 recall channel beside `FVG_RECALL`, preserving independent attribution and overlap tracking.

**Architecture:** Mirror the existing `FVG_RECALL` insertion path. Compute an `FMA_RECALL` set during discovery, persist an `fma_recall.json` artifact, thread the selected symbols into the filtered universe as `T3C_FMA_RECALL`, and extend the universe ledger snapshot with FMA counts and overlap counts.

**Tech Stack:** Python 3, pandas, pytest

---

### Task 1: Add failing Step 1 tests for `FMA_RECALL`

**Files:**
- Modify: `/Users/aeternusholdings/Documents/AeternusAgents-opus46/tests/test_dealflow_pipeline.py`
- Modify: `/Users/aeternusholdings/Documents/AeternusAgents-opus46/tests/test_dealflow_hypothesis_ledger.py`

**Step 1: Write the failing tests**

- Add a discover-path test mirroring the current FVG test:
  - `discover()` persists `fma_recall.json`
  - `build_universe_from_akg(...)` receives `fma_recall_symbols`
- Add a ledger snapshot test:
  - `build_filtered_universe(...)` records `T3C_FMA_RECALL`
  - `rule_snapshot` records `fma_recall_selected_count`
  - `rule_snapshot` records `fma_recall_overlap_with_fvg_count`

**Step 2: Run tests to verify they fail**

Run:

```bash
python3 -m pytest tests/test_dealflow_pipeline.py tests/test_dealflow_hypothesis_ledger.py -k 'fma_recall' -v
```

Expected:
- failures because `fma_recall.json`, `fma_recall_symbols`, and new ledger counts do not exist yet

### Task 2: Add config and universe-tier plumbing

**Files:**
- Modify: `/Users/aeternusholdings/Documents/AeternusAgents-opus46/tradingagents/default_config.py`
- Modify: `/Users/aeternusholdings/Documents/AeternusAgents-opus46/tradingagents/dealflow/akg_universe.py`

**Step 1: Write the minimal implementation**

- Add config keys:
  - `dealflow_fma_recall_enabled`
  - `dealflow_fma_recall_quota`
  - `dealflow_fma_recall_min_score`
- Extend `build_filtered_universe(...)` and `build_universe_from_akg(...)` to accept `fma_recall_symbols`
- Assign the new tier label:
  - `T3C_FMA_RECALL`
- Extend the last-universe ledger snapshot with:
  - `fma_recall_selected_count`
  - `fma_recall_overlap_with_fvg_count`

**Step 2: Run targeted tests**

Run:

```bash
python3 -m pytest tests/test_dealflow_hypothesis_ledger.py -k 'fma_recall' -v
```

Expected:
- universe-tier / ledger tests pass

### Task 3: Compute and persist the `FMA_RECALL` channel during discovery

**Files:**
- Modify: `/Users/aeternusholdings/Documents/AeternusAgents-opus46/tradingagents/dealflow/pipeline.py`
- Modify: `/Users/aeternusholdings/Documents/AeternusAgents-opus46/tradingagents/dealflow/fma_recall.py` only if a small helper extraction is needed

**Step 1: Write the minimal implementation**

- Add `_build_fma_recall_channel(...)` in `DealFlowPipeline`
- Reuse the production `F=MA` feature logic already implemented in `fma_recall.py`
- Build the investable Step 1 candidate set from AKG company nodes
- Score candidates with the live formula
- keep the top `dealflow_fma_recall_quota` names above `dealflow_fma_recall_min_score`
- persist:
  - `eval_results/deal_flow/<date>/fma_recall.json`
- pass `fma_recall_symbols` into `build_universe_from_akg(...)`

**Step 2: Run targeted tests**

Run:

```bash
python3 -m pytest tests/test_dealflow_pipeline.py -k 'fma_recall' -v
```

Expected:
- discover-path tests pass

### Task 4: Run focused regression on the Step 1 surface

**Files:**
- No new files unless regressions fail

Run:

```bash
python3 -m pytest tests/test_dealflow_pipeline.py tests/test_dealflow_hypothesis_ledger.py tests/test_dealflow_lane_metadata.py tests/test_hypothesis_ledger.py tests/test_hypothesis_ledger_metrics.py -v
```

Expected:
- existing FVG Step 1 behavior still passes
- new FMA recall plumbing is covered

### Task 5: Update session memory

**Files:**
- Modify: `/Users/aeternusholdings/Documents/AeternusAgents-opus46/memory/WORKING.md`
- Modify: `/Users/aeternusholdings/Documents/AeternusAgents-opus46/memory/2026-03-07.md` if created, otherwise current daily log file
- Modify: `/Users/aeternusholdings/Documents/AeternusAgents-opus46/memory/MEMORY.md` only if the architecture decision is durable enough for long-term memory

**Step 1: Capture what shipped**

- note the new tier name
- note the default quota
- note that `FMA_RECALL` is additive and separate from `FVG_RECALL`
- note that overlap tracking is now a first-class Step 1 measurement path
