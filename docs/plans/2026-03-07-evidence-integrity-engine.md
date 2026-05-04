# Evidence Integrity Engine Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a read-only Step 2 evidence-integrity layer that classifies all scored candidates and writes `evidence_integrity.json` without changing current gate behavior.

**Architecture:** Build a small pure helper module for classification, call it from the pipeline after candidate scoring, and persist a deterministic artifact plus compact summary. Keep v1 read-only so current `ACTIVE` / `LOW_DATA` semantics remain unchanged.

**Tech Stack:** Python 3, pytest, existing dealflow pipeline/artifact patterns.

---

### Task 1: Add failing tests for evidence-integrity classification

**Files:**
- Modify: `tests/test_dealflow_pipeline.py`
- Create: `tests/test_evidence_integrity.py`
- Test: `tests/test_evidence_integrity.py`, `tests/test_dealflow_pipeline.py`

**Step 1: Write the failing tests**

Add pure tests for:
- confirmed candidate classification
- sparse-but-interesting classification
- data-degraded classification
- low-signal classification

Add pipeline tests for:
- `evidence_integrity.json` gets written
- summary includes class counts
- pipeline behavior remains otherwise unchanged

**Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_evidence_integrity.py tests/test_dealflow_pipeline.py -k 'evidence_integrity' -v`
Expected: FAIL because module/behavior does not exist yet.

**Step 3: Commit**

```bash
git add tests/test_evidence_integrity.py tests/test_dealflow_pipeline.py
git commit -m "test: add evidence integrity coverage"
```

### Task 2: Implement pure evidence-integrity classifier

**Files:**
- Create: `tradingagents/dealflow/evidence_integrity.py`
- Test: `tests/test_evidence_integrity.py`

**Step 1: Write minimal implementation**

Implement pure helpers for:
- mapping signals by symbol/family
- deriving degraded/missing/strong families
- computing breadth/quality/degradation/asymmetry scores
- assigning integrity class
- building artifact payload

**Step 2: Run focused tests**

Run: `python3 -m pytest tests/test_evidence_integrity.py -v`
Expected: PASS.

**Step 3: Commit**

```bash
git add tradingagents/dealflow/evidence_integrity.py tests/test_evidence_integrity.py
git commit -m "feat: add evidence integrity classifier"
```

### Task 3: Wire evidence integrity into pipeline

**Files:**
- Modify: `tradingagents/dealflow/pipeline.py`
- Test: `tests/test_dealflow_pipeline.py`

**Step 1: Integrate after candidate scoring**

- call the classifier after `score_candidates()`
- write `eval_results/deal_flow/<date>/evidence_integrity.json`
- return compact summary in pipeline output
- keep current `ACTIVE` / `LOW_DATA` behavior unchanged

**Step 2: Run focused tests**

Run: `python3 -m pytest tests/test_dealflow_pipeline.py -k 'evidence_integrity' -v`
Expected: PASS.

**Step 3: Commit**

```bash
git add tradingagents/dealflow/pipeline.py tests/test_dealflow_pipeline.py
git commit -m "feat: persist evidence integrity artifacts"
```

### Task 4: Run focused regression and update memory

**Files:**
- Modify: `memory/WORKING.md`
- Modify: `memory/2026-03-07.md`
- Modify: `memory/MEMORY.md`

**Step 1: Run regression**

Run: `python3 -m pytest tests/test_evidence_integrity.py tests/test_dealflow_pipeline.py tests/test_dealflow_momentum.py -k 'evidence_integrity or collect_standalone_bootstraps_without_discover' -v`
Expected: PASS.

**Step 2: Update memory**

Document:
- read-only v1 behavior
- artifact path
- class vocabulary
- verification commands

**Step 3: Commit**

```bash
git add memory/WORKING.md memory/2026-03-07.md memory/MEMORY.md
git commit -m "docs: record evidence integrity rollout"
```
