# FVG Regime And Confirmation Slice Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Extend the bullish FVG replay harness with a simple market-regime split and explicit confirmation slices so the system can decide whether FVG is robust enough to graduate toward Step 1.

**Architecture:** Keep all behavior inside the existing `tradingagents/dealflow/fvg_recall.py` replay surface, add simple regime tagging and explicit slice membership, and extend the current `summary.json` output from `aeternus fvg-backtest`.

**Tech Stack:** Python 3, pandas, numpy, yfinance, Typer, Rich, pytest

---

### Task 1: Add failing tests for regime and slice rollups

**Files:**
- Modify: `tests/test_fvg_recall.py`

**Step 1: Add a failing regime test**

- Add a test proving the replay can classify rows into a simple market regime using benchmark trend / volatility inputs.

**Step 2: Add a failing slice test**

- Add a test proving the explicit slice ladder works:
  - `raw_fvg`
  - `fvg_plus_rs`
  - `fvg_plus_rs_trend`
  - `fvg_plus_rs_trend_volume`

**Step 3: Add a failing summary test**

- Add a test proving the summary now includes:
  - `by_regime`
  - `by_slice`

**Step 4: Run tests to verify they fail**

Run:
```bash
python3 -m pytest tests/test_fvg_recall.py -v
```

**Step 5: Commit**

```bash
git add tests/test_fvg_recall.py
git commit -m "test: add failing fvg regime and slice coverage"
```

### Task 2: Implement simple regime tagging and explicit slices

**Files:**
- Modify: `tradingagents/dealflow/fvg_recall.py`

**Step 1: Add simple regime helpers**

- Implement a lightweight benchmark-based regime label:
  - `bull`
  - `bear`
  - `high_vol`

**Step 2: Add explicit slice membership**

- Add boolean membership or labels for:
  - `raw_fvg`
  - `fvg_plus_rs`
  - `fvg_plus_rs_trend`
  - `fvg_plus_rs_trend_volume`

**Step 3: Extend event and daily rows**

- Persist regime and slice membership into replay rows.

**Step 4: Extend summary output**

- Add:
  - `by_regime`
  - `by_slice`

**Step 5: Run tests**

Run:
```bash
python3 -m pytest tests/test_fvg_recall.py -v
```

**Step 6: Commit**

```bash
git add tradingagents/dealflow/fvg_recall.py tests/test_fvg_recall.py
git commit -m "feat: add fvg regime and confirmation slices"
```

### Task 3: Extend CLI coverage and rerun focused regressions

**Files:**
- Modify: `tests/test_cli_dealflow.py`
- Modify: `cli/commands/technical.py`

**Step 1: Extend CLI assertion coverage**

- Verify the command still renders a usable summary after the new fields are added.

**Step 2: Run focused regressions**

Run:
```bash
python3 -m pytest tests/test_fvg_recall.py tests/test_cli_dealflow.py -k 'fvg_recall or fvg_backtest' -v
python3 -m pytest tests/test_phase_engine.py -v
```

**Step 3: Commit**

```bash
git add tests/test_cli_dealflow.py cli/commands/technical.py
git commit -m "test: extend fvg backtest operator coverage"
```

### Task 4: Run live replay and record findings

**Files:**
- Modify: `memory/WORKING.md`
- Modify: `memory/2026-03-06.md`
- Modify: `memory/MEMORY.md`
- Modify: `docs/plans/2026-03-06-fvg-regime-slice-design.md`
- Modify: `docs/plans/2026-03-06-fvg-regime-slice.md`

**Step 1: Run live replay**

Run:
```bash
python3 -m cli.main fvg-backtest --start 1999-01-01 --top-n 3 --format json
```

**Step 2: Record the results**

- Note the regime and slice readout in memory.
- Capture whether the signal survives outside obvious bull conditions.

**Step 3: Commit**

```bash
git add memory/WORKING.md memory/2026-03-06.md memory/MEMORY.md docs/plans/2026-03-06-fvg-regime-slice-design.md docs/plans/2026-03-06-fvg-regime-slice.md
git commit -m "docs: record fvg regime and slice replay findings"
```
