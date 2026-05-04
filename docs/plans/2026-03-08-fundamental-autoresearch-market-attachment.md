# Fundamental Autoresearch Market Attachment Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add deterministic sector identity and forward-return attachment so the fundamental autoresearch harness can evaluate real SEC-prepared rows end to end.

**Architecture:** Add a static `large_cap_v1` sector map, a small market-data attachment module that computes forward returns from adjusted close history, and a thin CLI command to enrich prepared datasets before scoring. Keep SEC prep, market enrichment, and evaluation as separate stages.

**Tech Stack:** Python 3, pathlib/json, yfinance, pandas, pytest, Typer.

---

### Task 1: Add deterministic `large_cap_v1` sector map

**Files:**
- Create: `tradingagents/research/fundamental_autoresearch/sector_map.py`
- Test: `tests/test_fundamental_autoresearch_sector_map.py`

**Step 1: Write the failing test**

Cover:
- known `large_cap_v1` sector mappings
- unknown universe names rejected or unsupported cleanly

**Step 2: Run test to verify it fails**

Run:
```bash
python3 -m pytest tests/test_fundamental_autoresearch_sector_map.py -v
```

**Step 3: Write minimal implementation**

Implement:
- `get_large_cap_v1_sector_map()`

**Step 4: Run test to verify it passes**

Run:
```bash
python3 -m pytest tests/test_fundamental_autoresearch_sector_map.py -v
```

### Task 2: Add market data attachment module

**Files:**
- Create: `tradingagents/research/fundamental_autoresearch/market_data.py`
- Test: `tests/test_fundamental_autoresearch_market_data.py`

**Step 1: Write the failing test**

Cover:
- attach `20d / 60d / 120d / 252d` returns from adjusted close history
- use first tradable session on or after `effective_market_date`
- missing price history returns `None`

**Step 2: Run test to verify it fails**

Run:
```bash
python3 -m pytest tests/test_fundamental_autoresearch_market_data.py -v
```

**Step 3: Write minimal implementation**

Implement:
- adjusted-close download helper
- forward-return attachment helper

**Step 4: Run test to verify it passes**

Run:
```bash
python3 -m pytest tests/test_fundamental_autoresearch_market_data.py -v
```

### Task 3: Add CLI command for prepared-row market enrichment

**Files:**
- Modify: `cli/commands/fundamental_research.py`
- Test: `tests/test_cli_fundamental_research.py`

**Step 1: Write the failing test**

Cover:
- `fundamental-research-attach-returns`
- input prepared dataset path
- output enriched dataset path

**Step 2: Run test to verify it fails**

Run:
```bash
python3 -m pytest tests/test_cli_fundamental_research.py -k 'attach_returns' -v
```

**Step 3: Write minimal implementation**

Implement:
- CLI command
- file read / enrich / write path

**Step 4: Run test to verify it passes**

Run:
```bash
python3 -m pytest tests/test_cli_fundamental_research.py -k 'attach_returns' -v
```

### Task 4: Use the static sector map in the first real `large_cap_v1` prep flow

**Files:**
- Modify: `cli/commands/fundamental_research.py`
- Modify: `tradingagents/research/fundamental_autoresearch/prepare.py` only if needed
- Test: `tests/test_cli_fundamental_research.py`

**Step 1: Write the failing test**

Cover:
- `fundamental-research-prepare` fills sectors automatically for `large_cap_v1` symbols when no sector-map JSON is provided

**Step 2: Run test to verify it fails**

Run:
```bash
python3 -m pytest tests/test_cli_fundamental_research.py -k 'prepare_command_uses_large_cap_sector_map' -v
```

**Step 3: Write minimal implementation**

Thread the static sector map into the command when symbols are a subset of `large_cap_v1`.

**Step 4: Run test to verify it passes**

Run:
```bash
python3 -m pytest tests/test_cli_fundamental_research.py -k 'prepare_command_uses_large_cap_sector_map' -v
```

### Task 5: Run the first real evaluable dataset flow

**Files:**
- No new files required

**Step 1: Run focused verification**

Run:
```bash
python3 -m pytest tests/test_fundamental_autoresearch_sector_map.py tests/test_fundamental_autoresearch_market_data.py tests/test_cli_fundamental_research.py -v
python3 -m pytest tests/test_fundamental_autoresearch_contracts.py tests/test_fundamental_autoresearch_universe.py tests/test_fundamental_autoresearch_time_utils.py tests/test_fundamental_autoresearch_sec_ingest.py tests/test_fundamental_autoresearch_features.py tests/test_fundamental_autoresearch_score.py tests/test_fundamental_autoresearch_evaluate.py tests/test_fundamental_autoresearch_artifacts.py tests/test_fundamental_autoresearch_sec_fetch.py tests/test_fundamental_autoresearch_prepare.py tests/test_fundamental_autoresearch_sector_map.py tests/test_fundamental_autoresearch_market_data.py tests/test_cli_fundamental_research.py -v
```

**Step 2: Run the real flow**

Run:
```bash
python3 -m cli.main fundamental-research-cache-fill --symbols "<large_cap_v1 list>" --format json
python3 -m cli.main fundamental-research-prepare --symbols "<large_cap_v1 list>" --run-name large_cap_v1-latest --format json
python3 -m cli.main fundamental-research-attach-returns --prepared-json eval_results/fundamental_autoresearch/sec_cache/prepared/large_cap_v1-latest.json --output-json eval_results/fundamental_autoresearch/sec_cache/prepared/large_cap_v1-latest-with-returns.json --format json
python3 -m cli.main fundamental-research --prepared-json eval_results/fundamental_autoresearch/sec_cache/prepared/large_cap_v1-latest-with-returns.json --experiment-name live-sec-latest-with-returns --format json
```

**Step 3: Update memory**

Update:
- `memory/WORKING.md`
- `memory/2026-03-08.md`
- `memory/MEMORY.md` only if the architectural contract changed materially
