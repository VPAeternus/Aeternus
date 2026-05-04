# Stage Metric Review Surfaces Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Surface hypothesis-ledger stage metrics in `hindsight` and `performance-review` artifacts and CLI output so operators can judge each filter without opening raw ledger files.

**Architecture:** Add one summary helper on top of the existing append-only hypothesis ledger, then have `compute_hindsight(...)` and `compute_performance_review(...)` attach that summary to their result JSON. The CLI commands render those summaries directly, keeping the artifacts as the source of truth and the terminal as a thin presentation layer.

**Tech Stack:** Python 3, Typer, Rich, pytest

---

### Task 1: Add failing artifact-summary tests

**Files:**
- Modify: `tests/test_hindsight.py`
- Modify: `tests/test_performance_tracker.py`

**Step 1: Write failing tests**

- Add a hindsight test asserting `compute_hindsight(...)` includes `hypothesis_stage_summary` with at least one stage row and the expected `edge_5d`.
- Add a performance-review test asserting `compute_performance_review(...)` includes `hypothesis_stage_summary` with stage rows carrying `edge_5d` / `edge_20d`.

**Step 2: Run tests to verify they fail**

Run:
```bash
python3 -m pytest tests/test_hindsight.py -k stage_summary -v
python3 -m pytest tests/test_performance_tracker.py -k stage_summary -v
```

**Step 3: Commit**

```bash
git add tests/test_hindsight.py tests/test_performance_tracker.py
git commit -m "test: add failing stage summary artifact coverage"
```

### Task 2: Add the summary helper and wire result artifacts

**Files:**
- Modify: `tradingagents/dealflow/hypothesis_ledger.py`
- Modify: `tradingagents/dealflow/hindsight.py`
- Modify: `tradingagents/dealflow/performance_tracker.py`

**Step 1: Write the failing test if Task 1 did not already cover the helper behavior**

- If needed, add a narrow helper-level test in `tests/test_hypothesis_ledger_metrics.py` for summary ordering and selected fields.

**Step 2: Implement the helper**

- Add a compact helper that reads `rows.json` and returns an ordered stage summary with:
  - `stage_id`
  - `kept_count`
  - `dropped_count`
  - `edge_5d`
  - `edge_20d`
  - `edge_3m`
  - `future_winner_recall`
  - `false_negative_cost`
  - `sample_size`

**Step 3: Wire the artifacts**

- After enrichment, attach `hypothesis_stage_summary` to hindsight and performance-review result payloads before writing their JSON artifacts.

**Step 4: Run tests**

Run:
```bash
python3 -m pytest tests/test_hypothesis_ledger_metrics.py tests/test_hindsight.py tests/test_performance_tracker.py -v
```

**Step 5: Commit**

```bash
git add tradingagents/dealflow/hypothesis_ledger.py tradingagents/dealflow/hindsight.py tradingagents/dealflow/performance_tracker.py tests/test_hypothesis_ledger_metrics.py tests/test_hindsight.py tests/test_performance_tracker.py
git commit -m "feat: add stage summary review artifacts"
```

### Task 3: Render summaries in CLI commands

**Files:**
- Modify: `cli/commands/dealflow.py`
- Modify: `cli/commands/performance.py`
- Modify: `tests/test_cli_dealflow.py`

**Step 1: Write failing CLI tests**

- Add one hindsight CLI test asserting the table output contains the stage-summary title and a known stage name.
- Add one performance-review CLI test asserting the output contains the stage-summary title and a known stage name.

**Step 2: Run tests to verify they fail**

Run:
```bash
python3 -m pytest tests/test_cli_dealflow.py -k 'hindsight_stage_summary or performance_review_stage_summary' -v
```

**Step 3: Implement minimal rendering**

- Add one compact Rich table in each command that renders the artifact summary block if present.
- Keep JSON output unchanged except for including the artifact field already written by Task 2.

**Step 4: Run focused regressions**

Run:
```bash
python3 -m pytest tests/test_cli_dealflow.py -k 'hindsight_stage_summary or performance_review_stage_summary' -v
python3 -m pytest tests/test_dealflow_hypothesis_ledger.py tests/test_hypothesis_ledger.py tests/test_hypothesis_ledger_metrics.py tests/test_hindsight.py tests/test_performance_tracker.py tests/test_cli_dealflow.py -k 'hindsight or performance_review or hypothesis_ledger' -v
```

**Step 5: Commit**

```bash
git add cli/commands/dealflow.py cli/commands/performance.py tests/test_cli_dealflow.py
git commit -m "feat: render stage summary review tables"
```
