# FVG Step 1 Recall Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a bullish FVG replay and backtest tool for a narrow semis / AI universe so the system can validate whether FVG-based recall features deserve promotion into Step 1.

**Architecture:** Add one pure replay module that computes point-in-time bullish FVG features, event-study outputs, and daily basket scores from OHLCV history, then expose it through one CLI command that writes inspectable JSON artifacts under `eval_results/deal_flow/fvg_backtest/`.

**Tech Stack:** Python 3, pandas, numpy, yfinance, Typer, Rich, pytest

---

### Task 1: Add failing pure feature tests

**Files:**
- Create: `tests/test_fvg_recall.py`

**Step 1: Write the failing FVG detection tests**

- Add a synthetic OHLCV helper with deterministic dates and volume.
- Add a test proving bullish FVG is detected only when `low[t] > high[t-2]`.
- Add a test proving tiny gaps below the ATR-normalized floor are rejected.

**Step 2: Write the failing confirmation/score tests**

- Add a test proving repeated same-direction bullish FVGs score higher than alternating gaps.
- Add a test proving the score uses only current and prior bars, not future bars.

**Step 3: Run tests to verify they fail**

Run:
```bash
python3 -m pytest tests/test_fvg_recall.py -v
```

**Step 4: Commit**

```bash
git add tests/test_fvg_recall.py
git commit -m "test: add failing fvg recall coverage"
```

### Task 2: Implement the pure FVG replay engine

**Files:**
- Create: `tradingagents/dealflow/fvg_recall.py`

**Step 1: Add narrow-universe constants and data contracts**

- Define the default semis / AI ticker list in the module.
- Add helpers for:
  - OHLCV normalization
  - ATR calculation
  - forward-return calculation

**Step 2: Implement point-in-time bullish FVG features**

- Implement:
  - bullish FVG presence
  - ATR-normalized gap size
  - same-direction FVG count
  - alternating gap count
  - gap persistence
  - price-above-gap-midpoint
  - relative strength
  - volume z-score
  - distance to 52-week high
  - trend alignment

**Step 3: Implement event-study output**

- Build one event row per bullish FVG event with:
  - ticker
  - event date
  - feature snapshot
  - forward returns at `5d / 20d / 60d / 90d`

**Step 4: Implement daily basket output**

- Build one score row per ticker/day.
- Rank each date.
- Compute top-`N` basket forward returns for the same horizons.

**Step 5: Add summary helpers**

- Summarize:
  - event counts
  - hit rates
  - average / median forward returns
  - top-`N` basket returns

**Step 6: Run tests**

Run:
```bash
python3 -m pytest tests/test_fvg_recall.py -v
```

**Step 7: Commit**

```bash
git add tradingagents/dealflow/fvg_recall.py tests/test_fvg_recall.py
git commit -m "feat: add bullish fvg replay engine"
```

### Task 3: Add failing CLI coverage

**Files:**
- Modify: `tests/test_cli_dealflow.py`

**Step 1: Add the failing CLI test**

- Add a test for `fvg-backtest` that patches the pure module result and asserts:
  - command exits successfully
  - output includes `FVG Backtest`
  - output includes at least one horizon metric
  - output includes the artifact path

**Step 2: Run test to verify it fails**

Run:
```bash
python3 -m pytest tests/test_cli_dealflow.py -k 'fvg_backtest' -v
```

**Step 3: Commit**

```bash
git add tests/test_cli_dealflow.py
git commit -m "test: add failing fvg backtest cli coverage"
```

### Task 4: Add the CLI command and artifact writing

**Files:**
- Modify: `cli/commands/technical.py`
- Modify: `cli/common.py`

**Step 1: Add `fvg-backtest` command**

- Add options for:
  - `--tickers`
  - `--start`
  - `--end`
  - `--top-n`
  - `--format`
  - `--artifact-dir`

**Step 2: Add compact rendering**

- Print:
  - event-study summary
  - top-`N` basket summary
  - best/worst tickers
  - output path

**Step 3: Persist artifacts**

- Write:
  - `events.json`
  - `daily_scores.json`
  - `summary.json`

**Step 4: Run CLI tests**

Run:
```bash
python3 -m pytest tests/test_cli_dealflow.py -k 'fvg_backtest' -v
```

**Step 5: Run focused regressions**

Run:
```bash
python3 -m pytest tests/test_fvg_recall.py tests/test_cli_dealflow.py tests/test_phase_engine.py tests/test_dealflow_pipeline.py tests/test_hindsight.py tests/test_performance_tracker.py -v
```

**Step 6: Commit**

```bash
git add cli/commands/technical.py cli/common.py tests/test_cli_dealflow.py
git commit -m "feat: add fvg backtest command"
```

### Task 5: Document and persist session context

**Files:**
- Modify: `memory/WORKING.md`
- Modify: `memory/2026-03-06.md`
- Modify: `memory/MEMORY.md`
- Create: `docs/plans/2026-03-06-fvg-step1-recall-design.md`
- Create: `docs/plans/2026-03-06-fvg-step1-recall.md`

**Step 1: Update memory**

- Record that the project now has a bullish FVG replay harness for narrow-universe Step 1 hypothesis testing.

**Step 2: Commit**

```bash
git add memory/WORKING.md memory/2026-03-06.md memory/MEMORY.md docs/plans/2026-03-06-fvg-step1-recall-design.md docs/plans/2026-03-06-fvg-step1-recall.md
git commit -m "docs: record fvg step1 recall experiment"
```
