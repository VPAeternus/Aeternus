# FMA Step 1 Recall Replay Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a replay surface for the existing `F=MA` momentum logic so it can be evaluated as a potential Step 1 additive recall channel.

**Architecture:** Build a small `fma_recall` replay module that mirrors the FVG replay workflow, supports the current live formula and one shadow variant, and reports event/basket/overlap metrics on the narrow semis/AI universe and the QQQ top-20 proxy.

**Tech Stack:** Python 3, pandas, yfinance, pytest, Typer CLI

---

### Task 1: Add failing FMA replay tests

**Files:**
- Create: `/Users/aeternusholdings/Documents/AeternusAgents-opus46/tests/test_fma_recall.py`
- Modify: `/Users/aeternusholdings/Documents/AeternusAgents-opus46/tests/test_cli_dealflow.py`

**Step 1: Write the failing tests**

- Add pure tests for:
  - live FMA snapshot scoring
  - shadow FMA snapshot scoring
  - overlap bucket computation with FVG flags
  - summary payload shape
- Add a CLI smoke test for the new backtest command.

**Step 2: Run tests to verify they fail**

Run:

```bash
python3 -m pytest tests/test_fma_recall.py tests/test_cli_dealflow.py -k 'fma_recall or fma_backtest' -v
```

### Task 2: Implement the FMA replay module

**Files:**
- Create: `/Users/aeternusholdings/Documents/AeternusAgents-opus46/tradingagents/dealflow/fma_recall.py`

**Step 1: Write minimal implementation**

- Add replay helpers for:
  - universe resolution
  - historical download
  - `fma_live` feature computation
  - `fma_best_shadow` feature computation
  - event rows and daily basket rows
  - overlap buckets versus FVG-style confirmation flags

**Step 2: Run the pure tests**

```bash
python3 -m pytest tests/test_fma_recall.py -v
```

### Task 3: Add CLI integration

**Files:**
- Modify: `/Users/aeternusholdings/Documents/AeternusAgents-opus46/cli/commands/technical.py`

**Step 1: Write minimal implementation**

- Add `aeternus fma-backtest`
- Support:
  - `--start`
  - `--end`
  - `--top-n`
  - `--universe`
  - `--benchmark`
  - `--format`

**Step 2: Run CLI tests**

```bash
python3 -m pytest tests/test_cli_dealflow.py -k 'fma_backtest' -v
```

### Task 4: Run focused regression and live replays

**Files:**
- No code changes unless regressions fail

Run:

```bash
python3 -m pytest tests/test_fma_recall.py tests/test_cli_dealflow.py -k 'fma_recall or fma_backtest' -v
python3 -m pytest tests/test_phase_engine.py -v
python3 -m cli.main fma-backtest --start 1999-01-01 --universe semis_ai_narrow --benchmark SMH --top-n 3 --format json
python3 -m cli.main fma-backtest --start 1999-01-01 --universe qqq_top20_proxy --benchmark QQQ --top-n 3 --format json
```

### Task 5: Document the read and next promotion decision

**Files:**
- Modify: `/Users/aeternusholdings/Documents/AeternusAgents-opus46/memory/WORKING.md`
- Modify: `/Users/aeternusholdings/Documents/AeternusAgents-opus46/memory/2026-03-06.md`
- Modify: `/Users/aeternusholdings/Documents/AeternusAgents-opus46/memory/MEMORY.md` only if the replay leads to a durable architectural decision

**Step 1: Capture what shipped**

- Note whether `fma_live` is strong enough for Step 1 promotion
- Note whether the shadow variant materially outperforms live
- Note whether `FMA` adds unique recall beyond `FVG`
