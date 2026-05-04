# Earnings Options Scout Refactor Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Move earnings/options discovery to a manual Grok scout in `discover` and move deterministic IV divergence analysis into `collect`.

**Architecture:** Add a new daily manual Grok artifact for public earnings/options setups, thread it through discovery as a scout contribution, then convert the current IV scanner from a discover-time force-queue override into a collect-time connector that emits normal signals. Keep the pipeline resilient when the manual artifact is absent.

**Tech Stack:** Python 3, Typer, pytest, existing dealflow pipeline and source adapters, Yahoo Finance for deterministic confirmation.

---

### Task 1: Add manual earnings/options scout CLI contract

**Files:**
- Create: `cli/commands/earnings_options_prompt.py`
- Modify: `cli/main.py`
- Test: `tests/test_earnings_options_prompt.py`

**Step 1: Write the failing tests**

Add tests that verify:
- `--generate` prints a prompt with the requested date
- `--ingest` validates required fields and saves a daily artifact
- malformed payloads are rejected

**Step 2: Run test to verify it fails**

Run:
```bash
python3 -m pytest tests/test_earnings_options_prompt.py -q
```

Expected: fail because the module/command does not exist.

**Step 3: Write minimal implementation**

Implement:
- prompt template generator
- payload validator
- save/load helpers for `eval_results/deal_flow/earnings_options_scout_YYYY-MM-DD.json`

**Step 4: Run test to verify it passes**

Run:
```bash
python3 -m pytest tests/test_earnings_options_prompt.py -q
```

Expected: PASS

**Step 5: Commit**

```bash
git add cli/commands/earnings_options_prompt.py cli/main.py tests/test_earnings_options_prompt.py
git commit -m "feat: add manual earnings options scout cli"
```

### Task 2: Add source loader for manual earnings/options scout

**Files:**
- Create: `tradingagents/dealflow/sources/earnings_options_scout.py`
- Modify: `tradingagents/dealflow/sources/__init__.py`
- Test: `tests/test_earnings_options_scout.py`

**Step 1: Write the failing tests**

Add tests for:
- loading a saved daily artifact
- returning promoted symbols
- gracefully handling missing files

**Step 2: Run test to verify it fails**

Run:
```bash
python3 -m pytest tests/test_earnings_options_scout.py -q
```

Expected: fail because the module does not exist.

**Step 3: Write minimal implementation**

Implement:
- artifact path helper
- `load_earnings_options_scout(as_of_date)`
- `scan_manual_earnings_options_setups(as_of_date)` returning promoted symbols and raw entries

**Step 4: Run test to verify it passes**

Run:
```bash
python3 -m pytest tests/test_earnings_options_scout.py -q
```

Expected: PASS

**Step 5: Commit**

```bash
git add tradingagents/dealflow/sources/earnings_options_scout.py tradingagents/dealflow/sources/__init__.py tests/test_earnings_options_scout.py
git commit -m "feat: add earnings options scout source loader"
```

### Task 3: Thread manual earnings/options scout into discovery

**Files:**
- Modify: `tradingagents/dealflow/pipeline.py`
- Modify: `tradingagents/dealflow/akg_universe.py`
- Test: `tests/test_dealflow_pipeline.py`
- Test: `tests/test_akg_universe_filter.py`

**Step 1: Write the failing tests**

Add tests that verify:
- discovery loads the manual earnings/options scout artifact
- promoted names are passed into the universe builder
- scout audit includes an `earnings_options` section
- discovery summary surfaces the count

**Step 2: Run test to verify it fails**

Run:
```bash
python3 -m pytest tests/test_dealflow_pipeline.py tests/test_akg_universe_filter.py -k 'earnings_options' -q
```

Expected: FAIL because discovery does not know about the scout.

**Step 3: Write minimal implementation**

Implement:
- load scout artifact in `discover()`
- include promoted symbols in the extra universe inputs
- persist audit output
- expose discovery summary count

Do not move IV logic yet in this task.

**Step 4: Run test to verify it passes**

Run:
```bash
python3 -m pytest tests/test_dealflow_pipeline.py tests/test_akg_universe_filter.py -k 'earnings_options' -q
```

Expected: PASS

**Step 5: Commit**

```bash
git add tradingagents/dealflow/pipeline.py tradingagents/dealflow/akg_universe.py tests/test_dealflow_pipeline.py tests/test_akg_universe_filter.py
git commit -m "feat: thread earnings options scout into discovery"
```

### Task 4: Convert IV math into a collect-time connector

**Files:**
- Modify: `tradingagents/dealflow/sources/iv_scanner.py`
- Modify: `tradingagents/dealflow/pipeline.py`
- Test: `tests/test_iv_scanner.py`
- Test: `tests/test_dealflow_pipeline.py`

**Step 1: Write the failing tests**

Add tests that verify:
- the IV source can emit `DealFlowSignal` rows for a narrowed universe
- earnings dates are fetched before option chains
- option-chain logic is skipped for out-of-window names
- `collect()` includes the new connector health entry

**Step 2: Run test to verify it fails**

Run:
```bash
python3 -m pytest tests/test_iv_scanner.py tests/test_dealflow_pipeline.py -k 'earnings_iv_divergence or iv_collector' -q
```

Expected: FAIL because the current source only returns discover-style force-queue output.

**Step 3: Write minimal implementation**

Implement:
- a collector-facing function such as `collect_earnings_iv_signals(universe, *, as_of_date, config)`
- signal family name:
  - `earnings_iv_divergence`
- connector health should reflect actual coverage

Keep the implementation simple:
- fetch earnings dates once per ticker
- only fetch option chains for earnings-window candidates
- reuse helper functions where possible

**Step 4: Run test to verify it passes**

Run:
```bash
python3 -m pytest tests/test_iv_scanner.py tests/test_dealflow_pipeline.py -k 'earnings_iv_divergence or iv_collector' -q
```

Expected: PASS

**Step 5: Commit**

```bash
git add tradingagents/dealflow/sources/iv_scanner.py tradingagents/dealflow/pipeline.py tests/test_iv_scanner.py tests/test_dealflow_pipeline.py
git commit -m "feat: move iv divergence into collect connector"
```

### Task 5: Remove default discover-time IV force-queue behavior

**Files:**
- Modify: `tradingagents/dealflow/pipeline.py`
- Test: `tests/test_dealflow_pipeline.py`

**Step 1: Write the failing tests**

Add tests that verify:
- `discover()` no longer calls the quantitative IV scanner by default
- `_inject_force_queue_candidates()` is not used in the normal path
- queue items are not synthesized from `IV_FORCE_QUEUE` under default config

**Step 2: Run test to verify it fails**

Run:
```bash
python3 -m pytest tests/test_dealflow_pipeline.py -k 'iv_force_queue' -q
```

Expected: FAIL because the old path is still active.

**Step 3: Write minimal implementation**

Implement:
- remove discover-time IV scan from the default path
- disable force-queue injection unless explicitly enabled by config, or remove it if no migration path is needed

**Step 4: Run test to verify it passes**

Run:
```bash
python3 -m pytest tests/test_dealflow_pipeline.py -k 'iv_force_queue' -q
```

Expected: PASS

**Step 5: Commit**

```bash
git add tradingagents/dealflow/pipeline.py tests/test_dealflow_pipeline.py
git commit -m "refactor: retire default iv force queue path"
```

### Task 6: Add focused operator verification

**Files:**
- Modify: `memory/WORKING.md`
- Modify: `memory/2026-03-11.md`

**Step 1: Run focused tests**

Run:
```bash
python3 -m pytest tests/test_earnings_options_prompt.py tests/test_earnings_options_scout.py tests/test_iv_scanner.py tests/test_dealflow_pipeline.py tests/test_akg_universe_filter.py -k 'earnings_options or iv_force_queue or earnings_iv_divergence' -q
```

Expected: PASS

**Step 2: Run live smoke**

Run:
```bash
python3 -m cli.main earnings-options-prompt --generate --date 2026-03-11
python3 -m cli.main discover --date 2026-03-11 --format table
python3 -m cli.main collect --date 2026-03-11 --trigger manual --profile daily --top-k 30 --format table
```

Expected:
- prompt renders
- discover completes without quantitative IV scan bottleneck
- collect shows the new IV connector health entry

**Step 3: Update memory**

Record:
- design decision
- files changed
- test evidence
- any remaining limitations

**Step 4: Commit**

```bash
git add memory/WORKING.md memory/2026-03-11.md
git commit -m "docs: record earnings options scout refactor"
```
