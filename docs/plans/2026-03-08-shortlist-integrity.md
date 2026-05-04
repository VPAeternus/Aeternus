# Shortlist Integrity Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a read-only Step 3 shortlist-integrity artifact that measures shortlist cut quality, deep-selection lift, and top false negatives.

**Architecture:** Build a small pure module that consumes existing scored-candidate, shortlist, and queue artifacts and writes one `shortlist_integrity.json` artifact. Keep the rollout read-only and avoid any ranking or quota changes. Start with artifact generation and focused tests before considering review/CLI surfaces.

**Tech Stack:** Python 3.14, pytest, existing dealflow artifact pipeline

---

### Task 1: Add failing tests for shortlist-integrity rollups

**Files:**
- Create: `tests/test_shortlist_integrity.py`
- Create: `tradingagents/dealflow/shortlist_integrity.py`

**Step 1: Write the failing test**

Add tests for:
- `selected_shortlist`
- `near_miss_eligible`
- `selected_for_deep`
- `top_false_negatives`
- baseline comparisons

**Step 2: Run test to verify it fails**

Run:
```bash
python3 -m pytest tests/test_shortlist_integrity.py -v
```

**Step 3: Write minimal implementation**

Add pure shortlist-integrity rollup helpers.

**Step 4: Run test to verify it passes**

Run:
```bash
python3 -m pytest tests/test_shortlist_integrity.py -v
```

### Task 2: Wire shortlist-integrity artifact persistence

**Files:**
- Modify: `tradingagents/dealflow/pipeline.py`
- Modify: `tests/test_dealflow_pipeline.py`

**Step 1: Write the failing test**

Add a pipeline test asserting:
- `shortlist_integrity.json` is persisted
- basic group counts are present

**Step 2: Run test to verify it fails**

Run:
```bash
python3 -m pytest tests/test_dealflow_pipeline.py -k 'shortlist_integrity' -v
```

**Step 3: Write minimal implementation**

Build and persist the artifact after shortlist and queue construction.

**Step 4: Run test to verify it passes**

Run:
```bash
python3 -m pytest tests/test_dealflow_pipeline.py -k 'shortlist_integrity' -v
```

### Task 3: Run focused regression

**Files:**
- Verify touched shortlist-integrity surface only

**Step 1: Run focused regression**

Run:
```bash
python3 -m pytest tests/test_shortlist_integrity.py tests/test_dealflow_pipeline.py -k 'shortlist_integrity or collect_standalone_bootstraps_without_discover' -v
```

### Task 4: Update memory

**Files:**
- Modify: `memory/WORKING.md`
- Modify: `memory/2026-03-08.md`
- Modify: `memory/MEMORY.md`

**Step 1: Record the rollout**

Capture:
- artifact location
- group definitions
- verification commands/results

**Step 2: Re-read the diff**

Run:
```bash
git diff -- docs/plans/2026-03-08-shortlist-integrity-design.md docs/plans/2026-03-08-shortlist-integrity.md tradingagents/dealflow/shortlist_integrity.py tradingagents/dealflow/pipeline.py tests/test_shortlist_integrity.py tests/test_dealflow_pipeline.py memory/WORKING.md memory/2026-03-08.md memory/MEMORY.md
```
