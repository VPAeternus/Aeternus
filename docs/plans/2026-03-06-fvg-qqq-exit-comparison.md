# FVG QQQ Exit Comparison Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Compare `Exit C`, `SMA50-only`, `90d-only`, and `QQQ` buy-and-hold under the same confirmed bullish FVG entry.

**Architecture:** Extend the existing `QQQ` strategy path with a small `exit_mode` parameter and a comparison runner that reuses the same entry logic. Surface the comparison through the existing CLI with a `--compare-exits` mode so we can judge whether Exit C actually earns its complexity.

**Tech Stack:** Python 3, pandas, yfinance, Typer, pytest

---

### Task 1: Add failing tests for exit-mode comparison

**Files:**
- Modify: `tests/test_fvg_recall.py`
- Modify: `tests/test_cli_dealflow.py`

**Step 1: Write the failing test**

- Add a pure test proving `run_fvg_strategy_backtest(...)` can run with explicit exit modes.
- Add a pure test for a comparison runner returning `exit_c`, `sma50_only`, `timeout_90d_only`, and `buy_and_hold`.
- Add a CLI test for `fvg-qqq-backtest --compare-exits --format json`.

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_fvg_recall.py tests/test_cli_dealflow.py -k 'compare_exits or exit_mode' -v`

Expected: FAIL because the exit comparison path does not exist yet.

### Task 2: Implement minimal comparison support

**Files:**
- Modify: `tradingagents/dealflow/fvg_recall.py`
- Modify: `cli/commands/technical.py`

**Step 1: Write minimal implementation**

- Add `exit_mode` support to the strategy runner.
- Add a comparison runner that:
  - executes `exit_c`
  - executes `sma50_only`
  - executes `timeout_90d_only`
  - computes `buy_and_hold` on the same `QQQ` history
- Keep output compact and directly comparable.

**Step 2: Run test to verify it passes**

Run: `python3 -m pytest tests/test_fvg_recall.py tests/test_cli_dealflow.py -k 'compare_exits or exit_mode' -v`

Expected: PASS

### Task 3: Run focused regression and live comparison

**Files:**
- Modify: `memory/WORKING.md`
- Modify: `memory/2026-03-06.md`

**Step 1: Run focused regression**

Run: `python3 -m pytest tests/test_fvg_recall.py tests/test_cli_dealflow.py -k 'fvg_recall or fvg_backtest or fvg_qqq_backtest' -v`

**Step 2: Run live comparison**

Run: `python3 -m cli.main fvg-qqq-backtest --start 1999-01-01 --compare-exits --format json`

**Step 3: Record the result**

- Log the winner, the simplest acceptable exit, and whether Exit C earns its extra complexity.
