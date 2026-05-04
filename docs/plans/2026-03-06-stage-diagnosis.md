# Stage Diagnosis Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a read-only `stage-diagnosis` CLI command that rolls up recent hypothesis-stage summaries and identifies which filters are costing the most optionality.

**Architecture:** Build one pure aggregation module that scans recent deal-flow review artifacts and computes per-stage rolling diagnostics, then add one dedicated CLI command that renders those diagnostics as compact operator tables and JSON.

**Tech Stack:** Python 3, Typer, Rich, pytest

---

### Task 1: Add failing aggregation and CLI tests

**Files:**
- Create: `tests/test_stage_diagnosis.py`
- Modify: `tests/test_cli_dealflow.py`

**Step 1: Write the failing aggregation tests**

- Add a test proving `performance_review.json` is preferred over `hindsight.json` when both exist for a cycle.
- Add a test proving the diagnosis ranks the stage with the highest false-negative cost / weakest recall first.

**Step 2: Write the failing CLI test**

- Add a `stage-diagnosis` CLI test that asserts the output includes:
  - `Stage Diagnosis`
  - a known stage id
  - the diagnosis recommendation line

**Step 3: Run tests to verify they fail**

Run:
```bash
python3 -m pytest tests/test_stage_diagnosis.py tests/test_cli_dealflow.py -k 'stage_diagnosis' -v
```

**Step 4: Commit**

```bash
git add tests/test_stage_diagnosis.py tests/test_cli_dealflow.py
git commit -m "test: add failing stage diagnosis coverage"
```

### Task 2: Implement the aggregation module

**Files:**
- Create: `tradingagents/dealflow/stage_diagnosis.py`

**Step 1: Implement cycle discovery**

- Scan dated directories under `eval_results/deal_flow`
- Sort by date descending
- Respect `last`

**Step 2: Implement summary loading**

- Prefer `performance_review.json`
- Fall back to `hindsight.json`
- Read `hypothesis_stage_summary`

**Step 3: Implement aggregation**

- Group by `stage_id`
- Compute:
  - `cycles_seen`
  - `sample_cycles`
  - `avg_edge_5d`
  - `avg_edge_20d`
  - `avg_edge_3m`
  - `avg_recall`
  - `total_false_negative_cost`
  - `avg_false_negative_cost`
  - `worst_cycle_date`
  - `worst_cycle_false_negative_cost`
  - `priority_score`

**Step 4: Implement recommendation**

- Return a short diagnosis string naming the first stage to inspect and why

**Step 5: Run tests**

Run:
```bash
python3 -m pytest tests/test_stage_diagnosis.py -v
```

**Step 6: Commit**

```bash
git add tradingagents/dealflow/stage_diagnosis.py tests/test_stage_diagnosis.py
git commit -m "feat: add rolling stage diagnosis aggregation"
```

### Task 3: Add the CLI command

**Files:**
- Modify: `cli/commands/dealflow.py`
- Modify: `cli/common.py`
- Modify: `tests/test_cli_dealflow.py`

**Step 1: Add the command**

- Add `stage-diagnosis`
- Support:
  - `--last`
  - `--lane`
  - `--top`
  - `--format`

**Step 2: Add rendering helpers**

- Add one compact Rich renderer for:
  - priority table
  - worst recent misses table
  - diagnosis line

**Step 3: Run CLI tests**

Run:
```bash
python3 -m pytest tests/test_cli_dealflow.py -k 'stage_diagnosis' -v
```

**Step 4: Run focused regressions**

Run:
```bash
python3 -m pytest tests/test_stage_diagnosis.py tests/test_cli_dealflow.py tests/test_hypothesis_ledger.py tests/test_hypothesis_ledger_metrics.py tests/test_hindsight.py tests/test_performance_tracker.py tests/test_dealflow_hypothesis_ledger.py tests/test_dealflow_lane_metadata.py tests/test_dealflow_momentum.py tests/test_portfolio_hypothesis_ledger.py tests/test_portfolio_construction.py -v
```

**Step 5: Commit**

```bash
git add cli/commands/dealflow.py cli/common.py tests/test_cli_dealflow.py
git commit -m "feat: add stage diagnosis operator command"
```

### Task 4: Update memory

**Files:**
- Modify: `memory/WORKING.md`
- Modify: `memory/2026-03-06.md`
- Modify: `memory/MEMORY.md`

**Step 1: Record the new operator surface**

- Note that the system now has a rolling diagnosis command for identifying filter leaks without reading raw rows

**Step 2: Commit**

```bash
git add memory/WORKING.md memory/2026-03-06.md memory/MEMORY.md docs/plans/2026-03-06-stage-diagnosis-design.md docs/plans/2026-03-06-stage-diagnosis.md
git commit -m "docs: record stage diagnosis operator surface"
```
