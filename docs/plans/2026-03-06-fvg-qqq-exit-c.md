# FVG QQQ Exit C Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a `QQQ`-only strategy backtest that buys on confirmed bullish FVG entries and exits with Exit C.

**Architecture:** Extend the existing FVG replay module with one single-instrument strategy path instead of creating a separate subsystem. Reuse the current feature engine, use `SPY` as the relative-strength benchmark for `QQQ`, and expose a narrow CLI command that returns trade stats plus exit-reason breakdown.

**Tech Stack:** Python 3, pandas, yfinance, Typer, pytest

---

### Task 1: Add failing tests for QQQ strategy behavior

**Files:**
- Modify: `tests/test_fvg_recall.py`
- Modify: `tests/test_cli_dealflow.py`

**Step 1: Write the failing test**

- Add a pure test that proves a `QQQ` strategy trade enters on confirmed bullish FVG and exits on `close < SMA50`.
- Add a pure test that proves the exit reason can also be `fvg_midpoint_rs_break` and `timeout_90d`.
- Add a CLI test for a new `fvg-qqq-backtest` command.

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_fvg_recall.py tests/test_cli_dealflow.py -k 'qqq_strategy or fvg_qqq_backtest' -v`

Expected: FAIL because the strategy path does not exist yet.

### Task 2: Implement the minimal strategy engine

**Files:**
- Modify: `tradingagents/dealflow/fvg_recall.py`
- Modify: `cli/commands/technical.py`

**Step 1: Write minimal implementation**

- Add one pure backtest function that:
  - loads `QQQ` and `SPY`
  - enters on bullish FVG + `RS20 > 0` + `SMA50 > SMA200`
  - exits on:
    - `close < SMA50`
    - or `RS20 < 0` and `close < FVG midpoint`
    - or `90` trading-day timeout
  - executes next-day open
  - holds at most one position at a time
- Return:
  - trade list
  - total trades
  - win rate
  - average trade return
  - total compounded return
  - max drawdown
  - average hold days
  - exit-reason counts

**Step 2: Run test to verify it passes**

Run: `python3 -m pytest tests/test_fvg_recall.py tests/test_cli_dealflow.py -k 'qqq_strategy or fvg_qqq_backtest' -v`

Expected: PASS

### Task 3: Run focused regression and live QQQ strategy backtest

**Files:**
- Modify: `memory/WORKING.md`
- Modify: `memory/2026-03-06.md`

**Step 1: Run focused regression**

Run: `python3 -m pytest tests/test_fvg_recall.py tests/test_cli_dealflow.py -k 'fvg_recall or fvg_backtest or fvg_qqq_backtest' -v`

**Step 2: Run the live strategy backtest**

Run: `python3 -m cli.main fvg-qqq-backtest --start 1999-01-01 --format json`

**Step 3: Record results**

- Save the trade and summary artifacts.
- Log total return, win rate, max drawdown, average hold, and exit-reason mix in memory.
