# Fundamental Autoresearch Ticker CIK Resolver Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a cache-first SEC `company_tickers.json` resolver so the fundamental autoresearch harness can resolve ticker→CIK mappings without a user-supplied JSON file.

**Architecture:** Extend `sec_fetch.py` with SEC official ticker-map fetch/cache/resolve helpers, then switch the `fundamental-research-cache-fill` CLI to use the resolver directly. Keep all tests offline by injecting fake sessions and monkeypatching the resolver in CLI tests.

**Tech Stack:** Python 3, pathlib/json, requests-compatible HTTP, pytest, Typer.

---

### Task 1: Add SEC official company ticker-map fetch/cache helpers

**Files:**
- Modify: `tradingagents/research/fundamental_autoresearch/sec_fetch.py`
- Test: `tests/test_fundamental_autoresearch_sec_fetch.py`

**Step 1: Write the failing test**

Cover:
- deterministic company-tickers cache path
- SEC ticker-map fetch uses `User-Agent`
- cached round-trip for raw company-tickers payload

**Step 2: Run test to verify it fails**

Run:
```bash
python3 -m pytest tests/test_fundamental_autoresearch_sec_fetch.py -k 'company_tickers' -v
```

**Step 3: Write minimal implementation**

Implement:
- `company_tickers_cache_path(...)`
- `fetch_company_tickers_payload(...)`
- `cache_company_tickers_payload(...)`
- `load_company_tickers_payload(...)`

**Step 4: Run test to verify it passes**

Run:
```bash
python3 -m pytest tests/test_fundamental_autoresearch_sec_fetch.py -k 'company_tickers' -v
```

### Task 2: Add ticker→CIK resolver with cached SEC fallback

**Files:**
- Modify: `tradingagents/research/fundamental_autoresearch/sec_fetch.py`
- Test: `tests/test_fundamental_autoresearch_sec_fetch.py`

**Step 1: Write the failing test**

Cover:
- resolve requested tickers from live SEC payload
- fall back to cached SEC payload when live fetch fails
- raise clearly when neither live nor cached SEC payload exists
- handle dot/hyphen ticker aliasing

**Step 2: Run test to verify it fails**

Run:
```bash
python3 -m pytest tests/test_fundamental_autoresearch_sec_fetch.py -k 'resolve_ticker_cik_map' -v
```

**Step 3: Write minimal implementation**

Implement:
- `resolve_ticker_cik_map(...)`
- small internal alias-normalization helper

**Step 4: Run test to verify it passes**

Run:
```bash
python3 -m pytest tests/test_fundamental_autoresearch_sec_fetch.py -k 'resolve_ticker_cik_map' -v
```

### Task 3: Switch CLI cache-fill to resolver-owned mapping

**Files:**
- Modify: `cli/commands/fundamental_research.py`
- Test: `tests/test_cli_fundamental_research.py`

**Step 1: Write the failing test**

Cover:
- cache-fill command no longer requires `--ticker-cik-json`
- command calls `resolve_ticker_cik_map(...)`
- resolved map flows into `fill_sec_cache_for_universe(...)`

**Step 2: Run test to verify it fails**

Run:
```bash
python3 -m pytest tests/test_cli_fundamental_research.py -k 'cache_fill_command_runs' -v
```

**Step 3: Write minimal implementation**

Remove the manual mapping requirement from the CLI and use the resolver directly.

**Step 4: Run test to verify it passes**

Run:
```bash
python3 -m pytest tests/test_cli_fundamental_research.py -k 'cache_fill_command_runs' -v
```

### Task 4: Run the focused harness regression sweep

**Files:**
- No new files

**Step 1: Run focused verification**

Run:
```bash
python3 -m pytest tests/test_fundamental_autoresearch_sec_fetch.py tests/test_fundamental_autoresearch_prepare.py tests/test_cli_fundamental_research.py -v
python3 -m pytest tests/test_fundamental_autoresearch_contracts.py tests/test_fundamental_autoresearch_universe.py tests/test_fundamental_autoresearch_time_utils.py tests/test_fundamental_autoresearch_sec_ingest.py tests/test_fundamental_autoresearch_features.py tests/test_fundamental_autoresearch_score.py tests/test_fundamental_autoresearch_evaluate.py tests/test_fundamental_autoresearch_artifacts.py tests/test_fundamental_autoresearch_sec_fetch.py tests/test_fundamental_autoresearch_prepare.py tests/test_cli_fundamental_research.py -v
```

**Step 2: Update memory**

Update:
- `memory/WORKING.md`
- `memory/2026-03-08.md`
- `memory/MEMORY.md` only if the architectural contract changed materially
