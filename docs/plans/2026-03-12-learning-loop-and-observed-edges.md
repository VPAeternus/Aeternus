# Learning Loop and Observed Edges Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make each workflow cycle attempt hindsight and signal-family IC generation, safely write measured quality back into live weights, add a small observed-edge pass, and persist source/scout attribution for later edge analysis.

**Architecture:** Add a fail-open `learning` phase to `workflow-run` that calls existing hindsight and performance utilities, writes validated adaptive weight artifacts, records per-date learning status, and optionally reinforces a few high-precision observed edges in the AKG. Persist a normalized source-attribution artifact per cycle so hindsight can judge discovery families by realized edge.

**Tech Stack:** Python 3, Typer CLI, pytest, JSON artifacts, SQLite, existing AKG JSON store

---

### Task 1: Add workflow learning status tests

**Files:**
- Modify: `tests/test_cli_dealflow.py`
- Modify: `cli/commands/dealflow.py`

**Step 1: Write the failing test**

Add tests that:
- `workflow-run` records a `learning` step when orchestration succeeds
- a hindsight/performance failure marks `learning_status=DEGRADED` without failing the workflow
- an invalid weight output marks learning `BLOCKED` and preserves workflow completion

**Step 2: Run test to verify it fails**

Run:
```bash
python3 -m pytest tests/test_cli_dealflow.py -k 'workflow_run_learning' -q
```

**Step 3: Write minimal implementation**

Add a post-run learning phase inside `workflow-run` and persist it into the workflow artifact.

**Step 4: Run test to verify it passes**

Run:
```bash
python3 -m pytest tests/test_cli_dealflow.py -k 'workflow_run_learning' -q
```

### Task 2: Add learning runner utility

**Files:**
- Create: `tradingagents/dealflow/learning_loop.py`
- Modify: `cli/commands/dealflow.py`
- Test: `tests/test_learning_loop.py`

**Step 1: Write the failing test**

Add tests for a helper that:
- runs hindsight and performance review
- returns `OK`, `DEGRADED`, or `BLOCKED`
- writes `eval_results/deal_flow/<date>/learning_status.json`

**Step 2: Run test to verify it fails**

Run:
```bash
python3 -m pytest tests/test_learning_loop.py -q
```

**Step 3: Write minimal implementation**

Create a small orchestration helper around:
- `compute_hindsight(...)`
- `compute_performance_review(...)`
- weight writeback helpers
- observed edge update

**Step 4: Run test to verify it passes**

Run:
```bash
python3 -m pytest tests/test_learning_loop.py -q
```

### Task 3: Implement signal-family weight writeback

**Files:**
- Create: `tradingagents/dealflow/ic_weight_writeback.py`
- Modify: `tradingagents/dealflow/scoring.py`
- Test: `tests/test_ic_weight_writeback.py`

**Step 1: Write the failing test**

Add tests that:
- recent `signal_family_ic` rows produce bounded family weights
- insufficient data skips updates
- malformed candidate payload is rejected

**Step 2: Run test to verify it fails**

Run:
```bash
python3 -m pytest tests/test_ic_weight_writeback.py -q
```

**Step 3: Write minimal implementation**

Generate and validate:
- `eval_results/control/ic_signal_weights.json`

Ensure deal-flow scoring can read the artifact if present.

**Step 4: Run test to verify it passes**

Run:
```bash
python3 -m pytest tests/test_ic_weight_writeback.py -q
```

### Task 4: Replace ensemble-weight stub with safe bounded updates

**Files:**
- Modify: `tradingagents/graph/ensemble_weights.py`
- Modify: `tests/test_ensemble_weights.py`

**Step 1: Write the failing test**

Add tests that:
- `update_weights(...)` applies small clamped deltas from input IC
- result stays normalized
- clamps remain respected
- insufficient data leaves weights unchanged

**Step 2: Run test to verify it fails**

Run:
```bash
python3 -m pytest tests/test_ensemble_weights.py -q
```

**Step 3: Write minimal implementation**

Implement a conservative bounded updater that:
- nudges weights from IC input
- clamps per model
- renormalizes
- appends update metadata to history

**Step 4: Run test to verify it passes**

Run:
```bash
python3 -m pytest tests/test_ensemble_weights.py -q
```

### Task 5: Persist normalized source attribution

**Files:**
- Create: `tradingagents/dealflow/source_attribution.py`
- Modify: `tradingagents/dealflow/pipeline.py`
- Modify: `tradingagents/dealflow/hindsight.py`
- Test: `tests/test_source_attribution.py`

**Step 1: Write the failing test**

Add tests that:
- a cycle writes `source_attribution.json`
- each ticker row captures discovery sources, collector families, shortlist/deep flags
- hindsight can summarize source-level edge from the artifact

**Step 2: Run test to verify it fails**

Run:
```bash
python3 -m pytest tests/test_source_attribution.py -q
```

**Step 3: Write minimal implementation**

Persist the normalized attribution artifact and expose summary hooks to hindsight.

**Step 4: Run test to verify it passes**

Run:
```bash
python3 -m pytest tests/test_source_attribution.py -q
```

### Task 6: Add high-precision observed-edge builder

**Files:**
- Create: `tradingagents/dealflow/observed_edges.py`
- Modify: `tradingagents/graph/knowledge_graph.py`
- Modify: `tradingagents/dealflow/learning_loop.py`
- Test: `tests/test_observed_edges.py`

**Step 1: Write the failing test**

Add tests that:
- repeated same-day ticker co-mentions create or reinforce `co_mentioned` edges
- explicit theme-beneficiary evidence reinforces `catalyst_beneficiary`
- running twice is idempotent

**Step 2: Run test to verify it fails**

Run:
```bash
python3 -m pytest tests/test_observed_edges.py -q
```

**Step 3: Write minimal implementation**

Build edges from daily manual-X/news attribution evidence and save back into the AKG.

**Step 4: Run test to verify it passes**

Run:
```bash
python3 -m pytest tests/test_observed_edges.py -q
```

### Task 7: Wire learning phase into workflow-run

**Files:**
- Modify: `cli/commands/dealflow.py`
- Modify: `tests/test_cli_dealflow.py`

**Step 1: Write the failing test**

Add a workflow test that:
- successful workflow run includes `steps.learning`
- degraded learning does not fail the workflow
- operator-visible workflow status becomes `COMPLETED_WITH_LEARNING_DEGRADED` when appropriate

**Step 2: Run test to verify it fails**

Run:
```bash
python3 -m pytest tests/test_cli_dealflow.py -k 'learning' -q
```

**Step 3: Write minimal implementation**

Call the learning runner after execution/sync and persist the result into the workflow artifact and audit log.

**Step 4: Run test to verify it passes**

Run:
```bash
python3 -m pytest tests/test_cli_dealflow.py -k 'learning' -q
```

### Task 8: Focused verification

**Files:**
- No code changes

**Step 1: Run focused tests**

Run:
```bash
python3 -m pytest \
  tests/test_learning_loop.py \
  tests/test_ic_weight_writeback.py \
  tests/test_ensemble_weights.py \
  tests/test_source_attribution.py \
  tests/test_observed_edges.py \
  tests/test_cli_dealflow.py \
  -q
```

**Step 2: Run one live workflow smoke**

Run:
```bash
python3 -m cli.main workflow-run --mode manual --date 2026-03-11 --skip-execution --skip-sync --format json
```

**Expected:**
- workflow completes
- `steps.learning` exists
- `learning_status.json` is written for the run date

### Task 9: Update session memory

**Files:**
- Modify: `memory/WORKING.md`
- Modify: `memory/2026-03-12.md`
- Modify: `memory/MEMORY.md` only if an architectural decision changed materially

**Step 1: Record what changed**

Document:
- fail-open learning policy
- weight writeback behavior
- observed-edge builder scope
- source-attribution artifact

**Step 2: Save**

No extra implementation required beyond the memory update.
