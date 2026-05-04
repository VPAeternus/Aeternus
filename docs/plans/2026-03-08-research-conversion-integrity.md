# Research Conversion Integrity Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a read-only Step 5 artifact that measures research execution quality, portfolio conversion, and later forward returns from `analyze-batch`.

**Architecture:** Build one pure report helper driven by the existing batch summary plus an optional same-date portfolio plan, persist it from `analyze-batch`, and keep all execution behavior unchanged.

**Tech Stack:** Python 3, pytest, existing deal-flow and paper-execution artifacts

---

### Task 1: Add pure Research Conversion Integrity rollup

**Files:**
- Create: `tradingagents/dealflow/research_conversion_integrity.py`
- Test: `tests/test_research_conversion_integrity.py`

**Step 1: Write the failing test**

Cover:
- cohort classification
- portfolio inclusion
- realized horizon carry-through

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_research_conversion_integrity.py -v`

**Step 3: Write minimal implementation**

Implement a pure `build_research_conversion_integrity_report(...)`.

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_research_conversion_integrity.py -v`

### Task 2: Persist artifact from analyze-batch

**Files:**
- Modify: `cli/commands/scoring.py`
- Test: `tests/test_cli_dealflow.py`

**Step 1: Write the failing persistence test**

Cover:
- `research_conversion_integrity.json` written under `eval_results/deal_flow/<date>/`
- artifact includes portfolio flag when a plan exists

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_cli_dealflow.py -k 'research_conversion_integrity' -v`

**Step 3: Write minimal implementation**

After `analyze-batch` builds `summary`, build the report and persist it.

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_cli_dealflow.py -k 'research_conversion_integrity' -v`

### Task 3: Focused regression

**Files:**
- Test: `tests/test_research_conversion_integrity.py`
- Test: `tests/test_cli_dealflow.py`

**Step 1: Run focused regression**

Run:

```bash
python3 -m pytest tests/test_research_conversion_integrity.py tests/test_cli_dealflow.py -k 'research_conversion_integrity or load_batch_summary' -v
```

**Step 2: Verify expected result**

Expected: all touched tests pass, existing batch summary helpers remain intact.

### Task 4: Memory updates

**Files:**
- Modify: `memory/WORKING.md`
- Modify: `memory/2026-03-08.md`
- Modify: `memory/MEMORY.md`

**Step 1: Document the new Step 5 artifact**

Include:
- artifact path
- core groups
- verification commands
- current recommendation: artifact-only until real cycles accumulate
