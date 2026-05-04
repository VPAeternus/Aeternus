# Evidence Integrity CLI And Scorecards Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add Evidence Integrity operator visibility and review scorecards without changing current Step 2 gating behavior.

**Architecture:** Extend the existing `evidence_integrity.py` module with shared scorecard rollups, embed those rollups into the existing hindsight/performance review artifacts, and render summary views in the existing CLI surfaces. Keep the rollout read-only and reuse the current `evidence_integrity.json` artifact instead of creating a new storage path.

**Tech Stack:** Python 3.14, pytest, Typer, Rich, existing dealflow review artifact pipeline

---

### Task 1: Add failing scorecard tests

**Files:**
- Modify: `tests/test_evidence_integrity.py`
- Modify: `tradingagents/dealflow/evidence_integrity.py`

**Step 1: Write the failing tests**

Add tests for:
- scorecard rollup by integrity class
- `vs_step2_baseline`
- `vs_other_cohorts`

**Step 2: Run test to verify it fails**

Run:
```bash
python3 -m pytest tests/test_evidence_integrity.py -k 'scorecards' -v
```

**Step 3: Write minimal implementation**

Add `build_evidence_integrity_scorecards(...)` to `tradingagents/dealflow/evidence_integrity.py`.

**Step 4: Run test to verify it passes**

Run:
```bash
python3 -m pytest tests/test_evidence_integrity.py -k 'scorecards' -v
```

### Task 2: Embed scorecards in hindsight and performance review

**Files:**
- Modify: `tradingagents/dealflow/hindsight.py`
- Modify: `tradingagents/dealflow/performance_tracker.py`
- Modify: `tests/test_hindsight.py`
- Modify: `tests/test_performance_tracker.py`

**Step 1: Write the failing tests**

Add tests asserting:
- `hindsight` includes `evidence_integrity_cohorts`
- `performance_review` includes `evidence_integrity_cohorts`

**Step 2: Run test to verify it fails**

Run:
```bash
python3 -m pytest tests/test_hindsight.py tests/test_performance_tracker.py -k 'evidence_integrity_cohorts' -v
```

**Step 3: Write minimal implementation**

Load `evidence_integrity.json`, compute the scorecards, and persist them into the result payloads.

**Step 4: Run test to verify it passes**

Run:
```bash
python3 -m pytest tests/test_hindsight.py tests/test_performance_tracker.py -k 'evidence_integrity_cohorts' -v
```

### Task 3: Add CLI renderers and tests

**Files:**
- Modify: `cli/common.py`
- Modify: `cli/commands/dealflow.py`
- Modify: `cli/commands/performance.py`
- Modify: `tests/test_cli_dealflow.py`

**Step 1: Write the failing tests**

Add tests asserting:
- live Step 2 flow renders `Evidence Integrity`
- `hindsight` renders `Evidence Integrity Cohort Scorecards`
- `performance-review` renders `Evidence Integrity Cohort Scorecards`

**Step 2: Run test to verify it fails**

Run:
```bash
python3 -m pytest tests/test_cli_dealflow.py -k 'evidence_integrity' -v
```

**Step 3: Write minimal implementation**

Add shared renderers and wire them into existing commands.

**Step 4: Run test to verify it passes**

Run:
```bash
python3 -m pytest tests/test_cli_dealflow.py -k 'evidence_integrity' -v
```

### Task 4: Run focused regression

**Files:**
- Verify touched files only

**Step 1: Run focused regression**

Run:
```bash
python3 -m pytest tests/test_evidence_integrity.py tests/test_hindsight.py tests/test_performance_tracker.py tests/test_cli_dealflow.py -k 'evidence_integrity or evidence_integrity_cohorts' -v
```

**Step 2: Run broader touched-surface regression**

Run:
```bash
python3 -m pytest tests/test_evidence_integrity.py tests/test_dealflow_pipeline.py tests/test_hindsight.py tests/test_performance_tracker.py tests/test_cli_dealflow.py -k 'evidence_integrity or collect_standalone_bootstraps_without_discover' -v
```

### Task 5: Update memory and document verification

**Files:**
- Modify: `memory/WORKING.md`
- Modify: `memory/2026-03-08.md` or append to `memory/2026-03-07.md` if daily file policy remains same-day only
- Modify: `memory/MEMORY.md`

**Step 1: Update session state**

Record:
- new CLI surface
- new review scorecards
- verification commands/results

**Step 2: Re-read diff for accuracy**

Run:
```bash
git diff -- docs/plans/2026-03-08-evidence-integrity-cli-scorecards-design.md docs/plans/2026-03-08-evidence-integrity-cli-scorecards.md tradingagents/dealflow/evidence_integrity.py tradingagents/dealflow/hindsight.py tradingagents/dealflow/performance_tracker.py cli/common.py cli/commands/dealflow.py cli/commands/performance.py tests/test_evidence_integrity.py tests/test_hindsight.py tests/test_performance_tracker.py tests/test_cli_dealflow.py memory/WORKING.md memory/MEMORY.md memory/2026-03-08.md memory/2026-03-07.md
```
