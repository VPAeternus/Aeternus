# FVG QQQ Execution Timing Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add explicit `next_open` vs `signal_close` execution timing to the `QQQ` FVG strategy backtest and comparison runner.

**Architecture:** Extend the existing strategy simulation path with one timing parameter, keep `next_open` as the default, and thread the same option through the CLI and comparison artifact. Cover the behavior with tests before changing implementation.

**Tech Stack:** Python 3, pandas, pytest, Typer

---

### Task 1: Add failing strategy timing tests

**Files:**
- Modify: `/Users/aeternusholdings/Documents/AeternusAgents-opus46/tests/test_fvg_recall.py`

**Step 1: Write the failing tests**

- Add a test that requests `execution_timing="signal_close"` and asserts entry fills on the signal bar close instead of the next bar open.
- Add a test that asserts the exit fill also uses the triggering bar close in `signal_close` mode.

**Step 2: Run tests to verify they fail**

Run:

```bash
python3 -m pytest tests/test_fvg_recall.py -k 'signal_close' -v
```

### Task 2: Thread the timing through the strategy path

**Files:**
- Modify: `/Users/aeternusholdings/Documents/AeternusAgents-opus46/tradingagents/dealflow/fvg_recall.py`

**Step 1: Write the minimal implementation**

- Add `normalize_execution_timing(...)`
- Add `execution_timing` to `run_fvg_strategy_backtest(...)`
- Add `execution_timing` to `run_fvg_strategy_exit_comparison(...)`
- Update `_simulate_fvg_strategy_trades(...)` to switch entry/exit fills by timing mode
- Persist `execution_timing` in returned payloads

**Step 2: Run tests to verify they pass**

Run:

```bash
python3 -m pytest tests/test_fvg_recall.py -k 'signal_close' -v
```

### Task 3: Thread timing through the CLI and compare both assumptions

**Files:**
- Modify: `/Users/aeternusholdings/Documents/AeternusAgents-opus46/cli/commands/technical.py`
- Modify: `/Users/aeternusholdings/Documents/AeternusAgents-opus46/tests/test_cli_dealflow.py`

**Step 1: Write the failing CLI test**

- Add a test that `fvg-qqq-backtest` passes `execution_timing` through to the strategy or comparison runner.

**Step 2: Run tests to verify it fails**

Run:

```bash
python3 -m pytest tests/test_cli_dealflow.py -k 'execution_timing' -v
```

**Step 3: Write minimal CLI implementation**

- Add `--execution-timing` with values `next_open` and `signal_close`
- Thread the argument into both single-run and compare-exits paths

**Step 4: Run focused regression**

Run:

```bash
python3 -m pytest tests/test_fvg_recall.py tests/test_cli_dealflow.py -k 'fvg_qqq_backtest or signal_close or execution_timing' -v
```

### Task 4: Run the live comparison

**Files:**
- No code changes

**Step 1: Conservative comparison**

Run:

```bash
python3 -m cli.main fvg-qqq-backtest --start 1999-01-01 --compare-exits --execution-timing next_open --format json
```

**Step 2: Optimistic comparison**

Run:

```bash
python3 -m cli.main fvg-qqq-backtest --start 1999-01-01 --compare-exits --execution-timing signal_close --format json
```

**Step 3: Summarize the deltas**

- Compare returns and drawdowns for `exit_c`, `sma50_only`, `timeout_90d_only`, and `buy_and_hold`
- Keep the answer explicit that `signal_close` is optimistic and non-executable as modeled
