# FVG QQQ Top-20 Proxy Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a current `QQQ` top-20 proxy universe and benchmark-aware artifact separation to the FVG replay.

**Architecture:** Extend the existing replay engine with a small universe resolver that can fetch the current `QQQ` top holdings from `yfinance`, then thread the selected universe and benchmark through the CLI. Keep the semis/AI path untouched and test the new proxy behavior with TDD.

**Tech Stack:** Python 3, Typer, pandas, yfinance, pytest

---

### Task 1: Add failing tests for proxy universe resolution and CLI threading

**Files:**
- Modify: `tests/test_fvg_recall.py`
- Modify: `tests/test_cli_dealflow.py`

**Step 1: Write the failing tests**

- Add a pure test proving the engine can resolve a `qqq_top20_proxy` universe from a stubbed `yfinance` holdings table.
- Add a pure test proving the default artifact path includes both `universe_name` and `benchmark`.
- Add a CLI test proving `fvg-backtest --universe qqq-top20-proxy --benchmark QQQ` threads both values into `run_fvg_backtest(...)`.

**Step 2: Run tests to verify they fail**

Run:
`python3 -m pytest tests/test_fvg_recall.py tests/test_cli_dealflow.py -k 'qqq_top20_proxy or benchmark_option' -v`

Expected: FAIL because the new universe and CLI options do not exist yet.

### Task 2: Implement the minimal proxy-universe resolution

**Files:**
- Modify: `tradingagents/dealflow/fvg_recall.py`
- Modify: `cli/commands/technical.py`

**Step 1: Add minimal implementation**

- Add a helper to fetch the current `QQQ` top holdings using `yfinance.Ticker("QQQ").funds_data.top_holdings`.
- Add a universe resolver so `run_fvg_backtest(...)` can accept a named universe.
- Add CLI `--universe` and `--benchmark` options while preserving `--tickers` override behavior.
- Change the default artifact path to include the selected universe and benchmark.

**Step 2: Run tests to verify they pass**

Run:
`python3 -m pytest tests/test_fvg_recall.py tests/test_cli_dealflow.py -k 'qqq_top20_proxy or benchmark_option' -v`

Expected: PASS

### Task 3: Run focused regression and the live proxy replay

**Files:**
- Modify: `memory/WORKING.md`
- Modify: `memory/2026-03-06.md`

**Step 1: Run focused regression**

Run:
`python3 -m pytest tests/test_fvg_recall.py tests/test_cli_dealflow.py -k 'fvg_recall or fvg_backtest' -v`

**Step 2: Run the live proxy replay**

Run:
`python3 -m cli.main fvg-backtest --universe qqq-top20-proxy --benchmark QQQ --start 1999-01-01 --top-n 3 --format json`

**Step 3: Record the result in memory**

- Note the proxy universe composition, sample caveat, and live replay readout.
