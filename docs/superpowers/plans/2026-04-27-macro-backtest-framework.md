# Macro Backtest Framework Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a research-only macro framework backtester with horizons `(5, 10, 20, 30, 60, 90)`.

**Architecture:** Add small pure-function modules under `tradingagents/backtesting/macro/` for snapshots, forward returns, tables, and dealflow macro ablation. Keep network I/O in `scripts/backtest_macro_framework.py`; core modules accept already-loaded pandas objects to prevent lookahead and make tests deterministic.

**Tech Stack:** Python, pandas, pytest, existing `macro_engine.py` scoring helpers, existing dealflow score weights.

---

### Task 1: Forward returns
- Create `tradingagents/backtesting/macro/forward_returns.py`.
- Test `tests/test_macro_backtest_forward_returns.py`.
- Verify signal date uses next trading bar and supports horizons `(5,10,20,30,60,90)`.

### Task 2: Historical snapshots
- Create `tradingagents/backtesting/macro/historical_snapshots.py`.
- Test `tests/test_macro_backtest_snapshots.py`.
- Build snapshots from point-in-time sliced price/FRED inputs only.

### Task 3: Regime and sector tables
- Create `tradingagents/backtesting/macro/regime_tables.py`.
- Test `tests/test_macro_backtest_regime_tables.py`.
- Aggregate count, mean, median, hit rate, best, worst by regime/symbol/horizon.

### Task 4: Dealflow macro ablation
- Create `tradingagents/backtesting/macro/dealflow_ablation.py`.
- Test `tests/test_macro_backtest_ablation.py`.
- Compare macro-on vs macro-neutral rankings while holding all else constant.

### Task 5: Script wrapper
- Create `scripts/backtest_macro_framework.py`.
- Optionally register CLI import later; script must emit CSV/JSON artifacts and PIT disclaimer.
