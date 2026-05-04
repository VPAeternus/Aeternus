# Multi-Lane Probability Funnel Phase 1 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a hypothesis-ledger foundation around the existing deal-flow funnel and attach lane metadata without changing current ranking behavior.

**Architecture:** Keep the current `discover -> collect -> queue -> analyze -> portfolio -> hindsight` path intact, but instrument each major filter cut as a measured kept-vs-dropped experiment. Add lane-oriented metadata (`3m upside` and `emergence`) to current candidate and queue artifacts so later lane routing can be validated before it is allowed to drive orchestration.

**Tech Stack:** Python 3, Typer CLI, existing deal-flow artifacts under `eval_results/`, AKG-backed universe, pytest, JSON persistence

---

### Task 1: Define the hypothesis-ledger contract

**Files:**
- Create: `tradingagents/dealflow/hypothesis_ledger.py`
- Create: `tests/test_hypothesis_ledger.py`

**Step 1: Write the failing test**

```python
from pathlib import Path

from tradingagents.dealflow.hypothesis_ledger import (
    build_stage_snapshot_paths,
    make_ledger_row,
)


def test_make_ledger_row_sets_counts_and_identity(tmp_path: Path):
    row = make_ledger_row(
        run_id="2026-03-06-123000-manual",
        source_date="2026-03-06",
        lane="shared",
        stage_id="shortlist_cut",
        rule_snapshot={"top_k": 30},
        kept_symbols=["AAPL", "NVDA"],
        dropped_symbols=["MU"],
        base_dir=tmp_path,
    )

    assert row["run_id"] == "2026-03-06-123000-manual"
    assert row["stage_id"] == "shortlist_cut"
    assert row["input_count"] == 3
    assert row["kept_count"] == 2
    assert row["dropped_count"] == 1
    assert row["kept_symbols_path"]
    assert row["dropped_symbols_path"]
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_hypothesis_ledger.py::test_make_ledger_row_sets_counts_and_identity -v`

Expected: FAIL with missing module or missing symbol errors.

**Step 3: Write minimal implementation**

Implement:

- `build_stage_snapshot_paths(...)`
- `write_symbol_snapshot(...)`
- `make_ledger_row(...)`

The row should be append-only and deterministic. It should write `kept` and `dropped` symbol lists to disk and return a row dict with counts and file paths.

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_hypothesis_ledger.py -v`

Expected: PASS for contract and snapshot-path tests.

**Step 5: Commit**

```bash
git add tests/test_hypothesis_ledger.py tradingagents/dealflow/hypothesis_ledger.py
git commit -m "feat: add hypothesis ledger contract"
```

### Task 2: Instrument the shortlist cut in the current collect pipeline

**Files:**
- Modify: `tradingagents/dealflow/pipeline.py`
- Test: `tests/test_dealflow_hypothesis_ledger.py`

**Step 1: Write the failing test**

```python
def test_collect_writes_shortlist_cut_ledger_row(tmp_path, monkeypatch):
    ...
    assert row["stage_id"] == "shortlist_cut"
    assert row["kept_count"] == len(shortlist["candidates"])
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_dealflow_hypothesis_ledger.py::test_collect_writes_shortlist_cut_ledger_row -v`

Expected: FAIL because the collect path does not emit any ledger rows yet.

**Step 3: Write minimal implementation**

In `DealFlowPipeline.collect(...)`:

- identify the scored candidate pool before `rank_candidates(...)`
- identify the shortlisted names after ranking/manual merge
- compute the dropped eligible set
- emit one ledger row for `shortlist_cut`

Persist under the same dated `eval_results/deal_flow/{date}/...` tree.

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_dealflow_hypothesis_ledger.py -k shortlist_cut -v`

Expected: PASS and no changes to shortlist behavior.

**Step 5: Commit**

```bash
git add tests/test_dealflow_hypothesis_ledger.py tradingagents/dealflow/pipeline.py
git commit -m "feat: log shortlist cut to hypothesis ledger"
```

### Task 3: Instrument deep-selection and portfolio-inclusion cuts

**Files:**
- Modify: `tradingagents/dealflow/pipeline.py`
- Modify: `cli/commands/portfolio.py`
- Test: `tests/test_dealflow_hypothesis_ledger.py`
- Test: `tests/test_portfolio_hypothesis_ledger.py`

**Step 1: Write the failing tests**

```python
def test_build_research_queue_writes_deep_selection_ledger_row():
    ...


def test_portfolio_plan_writes_portfolio_inclusion_ledger_row():
    ...
```

**Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_dealflow_hypothesis_ledger.py -k deep_selection -v`

Run: `python3 -m pytest tests/test_portfolio_hypothesis_ledger.py -v`

Expected: FAIL because neither stage currently records kept-vs-dropped rows.

**Step 3: Write minimal implementation**

Add ledger emission for:

- `deep_selection_cut` in `_build_research_queue(...)`
- `portfolio_inclusion_cut` in `portfolio_plan(...)`

Each row should record:

- stage id
- shared lane for Phase 1
- kept vs dropped symbols
- rule snapshot (`deep_k`, quotas, portfolio min score, max positions, etc.)

**Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_dealflow_hypothesis_ledger.py tests/test_portfolio_hypothesis_ledger.py -v`

Expected: PASS with unchanged queue and portfolio behavior.

**Step 5: Commit**

```bash
git add tests/test_dealflow_hypothesis_ledger.py tests/test_portfolio_hypothesis_ledger.py tradingagents/dealflow/pipeline.py cli/commands/portfolio.py
git commit -m "feat: log deep selection and portfolio inclusion cuts"
```

### Task 4: Add lane metadata to current candidates and queue items

**Files:**
- Modify: `tradingagents/dealflow/contracts.py`
- Modify: `tradingagents/dealflow/scoring.py`
- Modify: `tradingagents/dealflow/pipeline.py`
- Test: `tests/test_dealflow_lane_metadata.py`

**Step 1: Write the failing test**

```python
def test_score_candidates_emits_lane_metadata_fields():
    ...
    assert "upside_3m_score" in candidate
    assert "emergence_proxy_score" in candidate
    assert "lane_candidates" in candidate
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_dealflow_lane_metadata.py -v`

Expected: FAIL because current candidates only expose the single active lane and core/momentum scores.

**Step 3: Write minimal implementation**

Extend the candidate and queue contracts with Phase 1 metadata only:

- `upside_3m_score`
- `emergence_proxy_score`
- `narrative_ignition_score`
- `fundamentals_acceleration_score`
- `relative_strength_score`
- `lane_candidates`

Keep current ranking behavior unchanged. These fields are informational in Phase 1.

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_dealflow_lane_metadata.py -v`

Expected: PASS and existing deal-flow tests remain green.

**Step 5: Commit**

```bash
git add tests/test_dealflow_lane_metadata.py tradingagents/dealflow/contracts.py tradingagents/dealflow/scoring.py tradingagents/dealflow/pipeline.py
git commit -m "feat: add phase-1 lane metadata to dealflow artifacts"
```

### Task 5: Add counterfactual metrics to the ledger reader

**Files:**
- Modify: `tradingagents/dealflow/hypothesis_ledger.py`
- Create: `tests/test_hypothesis_ledger_metrics.py`

**Step 1: Write the failing test**

```python
def test_compute_stage_metrics_returns_kept_vs_dropped_edge():
    ...
    assert metrics["edge_5d"] == 0.05
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_hypothesis_ledger_metrics.py -v`

Expected: FAIL because metrics helpers do not exist yet.

**Step 3: Write minimal implementation**

Add pure functions to compute:

- kept mean return
- dropped mean return
- edge
- future winner recall
- false-negative cost

Use simple input maps first so the logic is testable without live artifacts.

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_hypothesis_ledger_metrics.py -v`

Expected: PASS for deterministic metric helpers.

**Step 5: Commit**

```bash
git add tests/test_hypothesis_ledger_metrics.py tradingagents/dealflow/hypothesis_ledger.py
git commit -m "feat: add hypothesis ledger metrics helpers"
```

### Task 6: Run regression verification and document the new foundation

**Files:**
- Modify: `memory/WORKING.md`
- Modify: `memory/MEMORY.md`
- Modify or Create: `memory/2026-03-06.md`

**Step 1: Run focused regression tests**

Run:

```bash
python3 -m pytest tests/test_hypothesis_ledger.py -v
python3 -m pytest tests/test_dealflow_hypothesis_ledger.py -v
python3 -m pytest tests/test_portfolio_hypothesis_ledger.py -v
python3 -m pytest tests/test_dealflow_lane_metadata.py -v
python3 -m pytest tests/test_cli_dealflow.py -v
python3 -m pytest tests/test_reanalysis.py -v
```

Expected: PASS.

**Step 2: Run broader safety verification**

Run:

```bash
python3 -m pytest tests/test_session_assembler.py -v
python3 -m pytest tests/test_dealflow_scheduler.py -v
python3 -m pytest tests/test_dealflow_smart_money.py -v
```

Expected: PASS.

**Step 3: Update memory**

Record:

- hypothesis-ledger foundation added
- lane metadata added without routing split
- current next step is Phase 2 lane validation and L2 split design

**Step 4: Commit**

```bash
git add memory/WORKING.md memory/MEMORY.md memory/2026-03-06.md
git commit -m "docs: record multi-lane funnel phase 1 foundation"
```
