# Discovery Delta Engine Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a read-only Discovery Delta Engine that normalizes scout and technical recall state-change signals into a daily artifact without changing live Step 1 selection behavior.

**Architecture:** Add a pure normalization/aggregation module, call it from `DealFlowPipeline.discover()` after scout and technical recall artifacts are built, persist `discovery_delta.json`, and surface a compact summary while keeping Step 1 tiering and ranking unchanged.

**Tech Stack:** Python 3, pytest, existing dealflow pipeline contracts

---

### Task 1: Add failing tests for the read-only Delta artifact

**Files:**
- Modify: `/Users/aeternusholdings/Documents/AeternusAgents-opus46/tests/test_dealflow_pipeline.py`
- Create: `/Users/aeternusholdings/Documents/AeternusAgents-opus46/tests/test_discovery_delta.py`

**Step 1: Write the failing tests**

- Add a pipeline-level discover test that expects:
  - `discovery_delta.json` to be written
  - the discover summary to expose a compact `discovery_delta_summary`
- Add pure tests for:
  - signal normalization
  - cohort assignment
  - delta score ordering

**Step 2: Run tests to verify they fail**

Run:

```bash
python3 -m pytest tests/test_dealflow_pipeline.py tests/test_discovery_delta.py -k 'discovery_delta' -v
```

Expected:
- failures because the module, artifact, and summary do not exist yet

### Task 2: Add the pure Discovery Delta module

**Files:**
- Create: `/Users/aeternusholdings/Documents/AeternusAgents-opus46/tradingagents/dealflow/discovery_delta.py`
- Modify: `/Users/aeternusholdings/Documents/AeternusAgents-opus46/tradingagents/dealflow/contracts.py` only if a small typed contract is needed

**Step 1: Write the minimal implementation**

- Add normalization for:
  - scout audit rows
  - `fvg_recall` rows
  - `fma_recall` rows
- Add symbol-level aggregation
- Add cohort flags:
  - `scout_only`
  - `technical_only`
  - `multi_channel`
- Add `delta_score`

**Step 2: Run pure tests**

Run:

```bash
python3 -m pytest tests/test_discovery_delta.py -v
```

Expected:
- pure module tests pass

### Task 3: Wire Delta into `discover()`

**Files:**
- Modify: `/Users/aeternusholdings/Documents/AeternusAgents-opus46/tradingagents/dealflow/pipeline.py`

**Step 1: Write the minimal integration**

- After building:
  - `fvg_recall`
  - `fma_recall`
  - `scout_audit`
- call `build_discovery_delta(...)`
- persist:
  - `eval_results/deal_flow/<date>/discovery_delta.json`
- store:
  - `self._last_discovery_delta`
- return a compact summary in `discover()`

**Step 2: Run targeted tests**

Run:

```bash
python3 -m pytest tests/test_dealflow_pipeline.py -k 'discovery_delta' -v
```

Expected:
- discover-path tests pass

### Task 4: Add focused regression on Step 1 discovery

**Files:**
- No new files unless regressions fail

Run:

```bash
python3 -m pytest tests/test_dealflow_pipeline.py tests/test_dealflow_hypothesis_ledger.py tests/test_dealflow_lane_metadata.py tests/test_hypothesis_ledger.py tests/test_hypothesis_ledger_metrics.py tests/test_discovery_delta.py -v
```

Expected:
- existing discovery behavior remains unchanged
- new Delta artifact path is covered

### Task 5: Update memory and architecture notes

**Files:**
- Modify: `/Users/aeternusholdings/Documents/AeternusAgents-opus46/memory/WORKING.md`
- Modify: `/Users/aeternusholdings/Documents/AeternusAgents-opus46/memory/2026-03-07.md`
- Modify: `/Users/aeternusholdings/Documents/AeternusAgents-opus46/memory/MEMORY.md`

**Step 1: Capture the decision and shipped surface**

- note that `Discovery Delta` is read-only in v1
- note it consumes:
  - scouts
  - `FVG_RECALL`
  - `FMA_RECALL`
- note that it writes `discovery_delta.json`
- note that it does not yet influence Step 1 membership

### Task 6: Request code review before calling it done

**Files:**
- No code changes

**Step 1: Use the required review workflow**

- Request review on the Discovery Delta implementation once focused tests pass
- Do not call the feature complete until the review findings are addressed or explicitly dispositioned
