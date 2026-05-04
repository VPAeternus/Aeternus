# Fundamental Pillar Autoresearch Harness Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a point-in-time SEC filing research harness that scores structured fundamental snapshots and evaluates them against forward returns without changing the live Aeternus fundamental pillar.

**Architecture:** Add a sidecar research package under `tradingagents/research/fundamental_autoresearch/` with isolated modules for universe definition, SEC/XBRL snapshot preparation, deterministic scoring, evaluation, and experiment artifacts. Reuse existing Aeternus price/fundamental utilities only where they are point-in-time safe; otherwise keep the harness self-contained.

**Tech Stack:** Python 3, pandas, numpy, pytest, SEC EDGAR APIs/XBRL JSON, existing Aeternus CLI/testing conventions.

---

### Task 1: Scaffold the harness package and baseline contracts

**Files:**
- Create: `tradingagents/research/fundamental_autoresearch/__init__.py`
- Create: `tradingagents/research/fundamental_autoresearch/contracts.py`
- Create: `tests/test_fundamental_autoresearch_contracts.py`

**Step 1: Write the failing test**

Add tests for:
- a snapshot row contract shape
- score result contract shape
- evaluation result contract shape

**Step 2: Run test to verify it fails**

Run:
```bash
python3 -m pytest tests/test_fundamental_autoresearch_contracts.py -v
```

Expected:
- import/module failure

**Step 3: Write minimal implementation**

Create typed dicts / dataclasses for:
- filing snapshot
- score result
- evaluation summary

**Step 4: Run test to verify it passes**

Run:
```bash
python3 -m pytest tests/test_fundamental_autoresearch_contracts.py -v
```

Expected:
- PASS

**Step 5: Commit**

```bash
git add tradingagents/research/fundamental_autoresearch/__init__.py tradingagents/research/fundamental_autoresearch/contracts.py tests/test_fundamental_autoresearch_contracts.py
git commit -m "feat: scaffold fundamental autoresearch contracts"
```

### Task 2: Add a stable v1 universe definition

**Files:**
- Create: `tradingagents/research/fundamental_autoresearch/universe.py`
- Test: `tests/test_fundamental_autoresearch_universe.py`

**Step 1: Write the failing test**

Test:
- returns a deterministic v1 universe list
- includes only liquid large-cap proxy names
- rejects unknown universe names

**Step 2: Run test to verify it fails**

Run:
```bash
python3 -m pytest tests/test_fundamental_autoresearch_universe.py -v
```

**Step 3: Write minimal implementation**

Implement:
- `get_v1_universe(name="large_cap_v1")`
- deterministic static symbol list for v1

**Step 4: Run test to verify it passes**

Run:
```bash
python3 -m pytest tests/test_fundamental_autoresearch_universe.py -v
```

**Step 5: Commit**

```bash
git add tradingagents/research/fundamental_autoresearch/universe.py tests/test_fundamental_autoresearch_universe.py
git commit -m "feat: add fundamental autoresearch v1 universe"
```

### Task 3: Build filing timestamp normalization and effective date logic

**Files:**
- Create: `tradingagents/research/fundamental_autoresearch/time_utils.py`
- Test: `tests/test_fundamental_autoresearch_time_utils.py`

**Step 1: Write the failing test**

Cover:
- accepted timestamp parsing
- market-hours same-day behavior if enabled
- default next-session effective date behavior
- after-hours acceptance rolls to next trading day

**Step 2: Run test to verify it fails**

Run:
```bash
python3 -m pytest tests/test_fundamental_autoresearch_time_utils.py -v
```

**Step 3: Write minimal implementation**

Implement helpers for:
- SEC timestamp normalization
- `compute_effective_market_date(...)`

**Step 4: Run test to verify it passes**

Run:
```bash
python3 -m pytest tests/test_fundamental_autoresearch_time_utils.py -v
```

**Step 5: Commit**

```bash
git add tradingagents/research/fundamental_autoresearch/time_utils.py tests/test_fundamental_autoresearch_time_utils.py
git commit -m "feat: add filing effective date logic"
```

### Task 4: Add raw SEC snapshot ingestion adapter

**Files:**
- Create: `tradingagents/research/fundamental_autoresearch/sec_ingest.py`
- Test: `tests/test_fundamental_autoresearch_sec_ingest.py`

**Step 1: Write the failing test**

Cover:
- parsing simplified SEC companyfacts/submissions payloads
- extracting 10-Q / 10-K observations
- preserving filed / accepted timestamps
- ignoring unsupported filing types in v1

**Step 2: Run test to verify it fails**

Run:
```bash
python3 -m pytest tests/test_fundamental_autoresearch_sec_ingest.py -v
```

**Step 3: Write minimal implementation**

Implement:
- SEC payload normalization
- filing row extraction helpers

Do not fetch network data in tests.

**Step 4: Run test to verify it passes**

Run:
```bash
python3 -m pytest tests/test_fundamental_autoresearch_sec_ingest.py -v
```

**Step 5: Commit**

```bash
git add tradingagents/research/fundamental_autoresearch/sec_ingest.py tests/test_fundamental_autoresearch_sec_ingest.py
git commit -m "feat: add sec filing ingestion adapter"
```

### Task 5: Add point-in-time feature builder

**Files:**
- Create: `tradingagents/research/fundamental_autoresearch/features.py`
- Test: `tests/test_fundamental_autoresearch_features.py`

**Step 1: Write the failing test**

Cover:
- growth features
- quality features
- health features
- valuation context fields
- missing-field / coverage behavior

**Step 2: Run test to verify it fails**

Run:
```bash
python3 -m pytest tests/test_fundamental_autoresearch_features.py -v
```

**Step 3: Write minimal implementation**

Implement deterministic feature construction from normalized filing rows.

**Step 4: Run test to verify it passes**

Run:
```bash
python3 -m pytest tests/test_fundamental_autoresearch_features.py -v
```

**Step 5: Commit**

```bash
git add tradingagents/research/fundamental_autoresearch/features.py tests/test_fundamental_autoresearch_features.py
git commit -m "feat: add fundamental autoresearch features"
```

### Task 6: Add baseline deterministic scorer

**Files:**
- Create: `tradingagents/research/fundamental_autoresearch/score.py`
- Test: `tests/test_fundamental_autoresearch_score.py`

**Step 1: Write the failing test**

Cover:
- score output shape
- sub-score presence
- stable deterministic output for fixed inputs
- missing-data penalty behavior

**Step 2: Run test to verify it fails**

Run:
```bash
python3 -m pytest tests/test_fundamental_autoresearch_score.py -v
```

**Step 3: Write minimal implementation**

Implement:
- baseline weighted formula
- sub-scores
- total score

Keep it simple and transparent.

**Step 4: Run test to verify it passes**

Run:
```bash
python3 -m pytest tests/test_fundamental_autoresearch_score.py -v
```

**Step 5: Commit**

```bash
git add tradingagents/research/fundamental_autoresearch/score.py tests/test_fundamental_autoresearch_score.py
git commit -m "feat: add baseline fundamental autoresearch scorer"
```

### Task 7: Add forward-return evaluation engine

**Files:**
- Create: `tradingagents/research/fundamental_autoresearch/evaluate.py`
- Test: `tests/test_fundamental_autoresearch_evaluate.py`

**Step 1: Write the failing test**

Cover:
- attaching forward returns at `20d`, `60d`, `120d`, `252d`
- sector-neutral rank IC at `60d`
- coverage reporting
- quintile spread reporting

**Step 2: Run test to verify it fails**

Run:
```bash
python3 -m pytest tests/test_fundamental_autoresearch_evaluate.py -v
```

**Step 3: Write minimal implementation**

Implement:
- evaluation summary builder
- primary metric calculation
- secondary metrics

**Step 4: Run test to verify it passes**

Run:
```bash
python3 -m pytest tests/test_fundamental_autoresearch_evaluate.py -v
```

**Step 5: Commit**

```bash
git add tradingagents/research/fundamental_autoresearch/evaluate.py tests/test_fundamental_autoresearch_evaluate.py
git commit -m "feat: add fundamental autoresearch evaluator"
```

### Task 8: Add experiment artifact writer

**Files:**
- Create: `tradingagents/research/fundamental_autoresearch/artifacts.py`
- Test: `tests/test_fundamental_autoresearch_artifacts.py`

**Step 1: Write the failing test**

Cover:
- writing summary artifact
- deterministic artifact paths
- storing metadata, score version, and evaluation summary

**Step 2: Run test to verify it fails**

Run:
```bash
python3 -m pytest tests/test_fundamental_autoresearch_artifacts.py -v
```

**Step 3: Write minimal implementation**

Implement a small artifact writer under a dedicated results directory.

**Step 4: Run test to verify it passes**

Run:
```bash
python3 -m pytest tests/test_fundamental_autoresearch_artifacts.py -v
```

**Step 5: Commit**

```bash
git add tradingagents/research/fundamental_autoresearch/artifacts.py tests/test_fundamental_autoresearch_artifacts.py
git commit -m "feat: add autoresearch artifact writer"
```

### Task 9: Add a thin CLI entrypoint

**Files:**
- Modify: `cli/main.py`
- Create: `cli/commands/fundamental_research.py`
- Test: `tests/test_cli_fundamental_research.py`

**Step 1: Write the failing test**

Cover:
- command loads
- command runs on mocked prepared data
- command writes summary artifact

**Step 2: Run test to verify it fails**

Run:
```bash
python3 -m pytest tests/test_cli_fundamental_research.py -v
```

**Step 3: Write minimal implementation**

Add a CLI command that:
- loads prepared input
- runs score + evaluate
- writes artifact
- prints concise summary

**Step 4: Run test to verify it passes**

Run:
```bash
python3 -m pytest tests/test_cli_fundamental_research.py -v
```

**Step 5: Commit**

```bash
git add cli/main.py cli/commands/fundamental_research.py tests/test_cli_fundamental_research.py
git commit -m "feat: add fundamental autoresearch cli"
```

### Task 10: Add documentation, memory, and focused regression

**Files:**
- Modify: `memory/WORKING.md`
- Modify: `memory/MEMORY.md`
- Modify: `memory/2026-03-08.md`

**Step 1: Run focused regression**

Run:
```bash
python3 -m pytest tests/test_fundamental_autoresearch_contracts.py tests/test_fundamental_autoresearch_universe.py tests/test_fundamental_autoresearch_time_utils.py tests/test_fundamental_autoresearch_sec_ingest.py tests/test_fundamental_autoresearch_features.py tests/test_fundamental_autoresearch_score.py tests/test_fundamental_autoresearch_evaluate.py tests/test_fundamental_autoresearch_artifacts.py tests/test_cli_fundamental_research.py -v
```

Expected:
- PASS

**Step 2: Update memory**

Document:
- why the harness is sidecar-only in v1
- why `2009+` is the clean start
- why the event unit is filing-effective, not daily

**Step 3: Commit**

```bash
git add memory/WORKING.md memory/MEMORY.md memory/2026-03-08.md
git commit -m "docs: record fundamental autoresearch harness v1"
```
