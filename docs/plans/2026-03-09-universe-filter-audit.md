# Universe Filter Audit Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a first-class first-universe-filter audit artifact and CLI so operators can verify the stage before collectors run.

**Architecture:** Keep the current runtime shape where the first filter still runs inside `discover()`, but add a dedicated report builder, persistence hook, and CLI status surface. This is a read-only observability improvement, not a pipeline behavior change.

**Tech Stack:** Python, Typer, Rich, pytest, existing dealflow artifacts

---

### Task 1: Add universe filter report builder

**Files:**
- Create: `tradingagents/dealflow/universe_filter.py`
- Test: `tests/test_universe_filter.py`

**Step 1: Write failing tests**

Add tests that assert the report builder returns:
- universe size
- tier counts
- source counts
- overlap counts
- health checks

**Step 2: Run the tests to verify failure**

Run:
```bash
python3 -m pytest tests/test_universe_filter.py -v
```

**Step 3: Implement minimal report builder**

Add a pure helper that accepts:
- `as_of_date`
- `universe`
- `tier_map`
- `ledger`
- discovery source lists/counts

And returns the normalized report payload.

**Step 4: Run tests to verify pass**

Run:
```bash
python3 -m pytest tests/test_universe_filter.py -v
```

### Task 2: Persist universe filter artifact in discover

**Files:**
- Modify: `tradingagents/dealflow/pipeline.py`
- Test: `tests/test_dealflow_pipeline.py`

**Step 1: Write failing pipeline test**

Add a test that `discover()` writes:
- `eval_results/deal_flow/<date>/universe_filter.json`

And that the summary includes a compact universe-filter summary.

**Step 2: Run the targeted test to verify failure**

Run:
```bash
python3 -m pytest tests/test_dealflow_pipeline.py -k 'universe_filter' -v
```

**Step 3: Implement persistence**

During `discover()`:
- build the report from current universe/tier/discovery inputs
- write `universe_filter.json`
- store a compact summary on the returned discovery summary

**Step 4: Run the targeted test to verify pass**

Run:
```bash
python3 -m pytest tests/test_dealflow_pipeline.py -k 'universe_filter' -v
```

### Task 3: Add CLI status surface

**Files:**
- Modify: `cli/commands/dealflow.py`
- Modify: `cli/common.py`
- Test: `tests/test_cli_dealflow.py`

**Step 1: Write failing CLI tests**

Add tests for:
- `universe-filter --status`
- `universe-filter --format json`
- missing artifact error path

**Step 2: Run the targeted tests to verify failure**

Run:
```bash
python3 -m pytest tests/test_cli_dealflow.py -k 'universe_filter' -v
```

**Step 3: Implement CLI**

Add:
- new `universe-filter` command
- shared renderer in `cli/common.py`
- status mode for compact operator output

**Step 4: Run targeted CLI tests**

Run:
```bash
python3 -m pytest tests/test_cli_dealflow.py -k 'universe_filter' -v
```

### Task 4: Run focused verification

**Files:**
- No new files

**Step 1: Run focused suite**

Run:
```bash
python3 -m pytest tests/test_universe_filter.py tests/test_dealflow_pipeline.py tests/test_cli_dealflow.py -k 'universe_filter or discover_persists' -v
```

**Step 2: Inspect a real artifact**

Run:
```bash
python3 -m cli.main universe-filter --date 2026-03-09 --status
python3 -m cli.main universe-filter --date 2026-03-09 --format json
```

**Step 3: Commit**

```bash
git add tradingagents/dealflow/universe_filter.py tradingagents/dealflow/pipeline.py cli/commands/dealflow.py cli/common.py tests/test_universe_filter.py tests/test_dealflow_pipeline.py tests/test_cli_dealflow.py docs/plans/2026-03-09-universe-filter-audit-design.md docs/plans/2026-03-09-universe-filter-audit.md
git commit -m "feat: add universe filter audit stage"
```
