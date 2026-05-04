# KAMA FVG Regime Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Change the replay-only KAMA experiment so a KAMA bullish cross is only actionable inside an active bullish FVG regime.

**Architecture:** Reuse the existing FVG feature frame to derive a compact bullish-regime state machine, then gate KAMA events with that regime instead of treating KAMA and FVG as loose overlap families. Keep the work replay-only in `kama_recall.py` and `kama-backtest`; do not wire this into live discovery or portfolio admission yet.

**Tech Stack:** Python 3.14, pandas, pytest, Typer

---

### Task 1: Add failing regime-state tests

**Files:**
- Modify: `tests/test_kama_recall.py`

**Step 1: Write the failing test**

- Add a pure test for a bullish FVG regime helper:
  - bullish FVG on two successive events increments streak from `1` to `2`
  - no bearish FVG in between keeps the regime active
  - a bearish FVG resets the regime to inactive and streak `0`
- Add a second pure test:
  - no bearish FVG prints
  - regime expires after `max_age_bars`

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_kama_recall.py -k 'fvg_regime' -q`

Expected: FAIL because the helper does not exist yet.

### Task 2: Add failing KAMA gating test

**Files:**
- Modify: `tests/test_kama_recall.py`

**Step 1: Write the failing test**

- Add a focused test that proves `kama_active` only becomes `True` when:
  - `cross_up == True`
  - `bullish_fvg_regime_active == True`
- The same cross outside the regime should remain inactive.

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_kama_recall.py -k 'kama_active' -q`

Expected: FAIL because the current implementation treats any bullish cross as active.

### Task 3: Implement minimal regime helper and gate KAMA events

**Files:**
- Modify: `tradingagents/dealflow/kama_recall.py`

**Step 1: Write minimal implementation**

- Add a helper that builds:
  - `bullish_fvg_regime_active`
  - `bullish_fvg_streak`
  - `bullish_fvg_regime_age_bars`
- Use existing FVG feature data:
  - `bullish_fvg_present`
  - bearish FVG from `bear_gap_size` and ATR floor
- Set default `max_age_bars = 20`
- Change KAMA row building so:
  - `kama_active = cross_up and bullish_fvg_regime_active`
- Persist regime fields into replay rows for inspection.

**Step 2: Run focused tests**

Run: `python3 -m pytest tests/test_kama_recall.py -q`

Expected: PASS

### Task 4: Verify CLI and live smoke still work

**Files:**
- No new files required if output contract stays stable

**Step 1: Run focused technical replay tests**

Run: `python3 -m pytest tests/test_kama_recall.py tests/test_cli_dealflow.py -k 'kama or fma_backtest or fvg_backtest' -q`

Expected: PASS

**Step 2: Run live smoke**

Run: `python3 -m cli.main kama-backtest --tickers MU --tickers BE --benchmark QQQ --start 2020-01-01 --top-n 1 --format json`

Expected:
- command exits `0`
- artifact written under `eval_results/deal_flow/kama_backtest/<date>/`
- event count reflects KAMA crosses inside bullish FVG regime only

### Task 5: Record the rule change

**Files:**
- Modify: `memory/WORKING.md`
- Modify: `memory/2026-03-10.md`
- Modify: `memory/MEMORY.md`

**Step 1: Document**

- Note that KAMA replay no longer means loose KAMA/FVG overlap.
- Record the new contract:
  - FVG defines regime
  - KAMA cross is trigger inside the regime
  - regime expires after `20` bars without a new bullish FVG or immediately on bearish FVG
