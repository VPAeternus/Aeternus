# Deep Selection Integrity Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a read-only Step 4 artifact that measures the deep-selection boundary and separates auto-selected names from manual / IV / held-position injections.

**Architecture:** Build one pure report helper, call it from the pipeline after the research queue is built, and persist a dated JSON artifact beside the existing Step 2 and Step 3 artifacts. Keep behavior unchanged.

**Tech Stack:** Python 3, pytest, existing deal-flow artifact pipeline

---

### Task 1: Add pure Deep Selection Integrity rollup

**Files:**
- Create: `tradingagents/dealflow/deep_selection_integrity.py`
- Test: `tests/test_deep_selection_integrity.py`

**Step 1: Write the failing test**

Cover:
- selected rows
- near misses
- injected-selected subset
- false negatives ordering

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_deep_selection_integrity.py -v`

**Step 3: Write minimal implementation**

Implement a pure `build_deep_selection_integrity_report(...)` helper.

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_deep_selection_integrity.py -v`

### Task 2: Persist artifact in the pipeline

**Files:**
- Modify: `tradingagents/dealflow/pipeline.py`
- Test: `tests/test_dealflow_pipeline.py`

**Step 1: Write the failing pipeline persistence test**

Cover:
- artifact written to `eval_results/deal_flow/<date>/deep_selection_integrity.json`
- coverage summary populated

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_dealflow_pipeline.py -k 'deep_selection_integrity' -v`

**Step 3: Write minimal implementation**

Call the new report helper after research queue construction and persist it through the existing artifact writer.

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_dealflow_pipeline.py -k 'deep_selection_integrity' -v`

### Task 3: Focused regression

**Files:**
- Test: `tests/test_deep_selection_integrity.py`
- Test: `tests/test_dealflow_pipeline.py`

**Step 1: Run focused regression**

Run:

```bash
python3 -m pytest tests/test_deep_selection_integrity.py tests/test_dealflow_pipeline.py -k 'deep_selection_integrity or collect_standalone_bootstraps_without_discover' -v
```

**Step 2: Verify expected result**

Expected: all selected tests pass, no Step 2 or Step 3 regressions in the touched pipeline path.

### Task 4: Memory updates

**Files:**
- Modify: `memory/WORKING.md`
- Modify: `memory/2026-03-08.md`
- Modify: `memory/MEMORY.md`

**Step 1: Document the new Step 4 artifact**

Include:
- artifact path
- groups
- verification commands
- current recommendation: artifact-only until real cycles accumulate
