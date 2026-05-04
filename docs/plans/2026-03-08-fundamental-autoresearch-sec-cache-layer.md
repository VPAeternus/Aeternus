# Fundamental Autoresearch SEC Cache Layer Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a cache-first SEC fetch layer that stores raw `submissions` and `companyfacts` payloads locally and drives prepared-row generation for the Fundamental Pillar Autoresearch Harness.

**Architecture:** Add `sec_fetch.py` for raw payload retrieval and cache persistence, extend `prepare.py` with deterministic cache-path helpers and prepared-row writing, and keep all tests fixture-driven with injected HTTP clients. The harness remains sidecar-only and reproducible from local cache.

**Tech Stack:** Python 3, requests-compatible HTTP, pathlib/json, pytest, SEC EDGAR APIs.

---

### Task 1: Add SEC cache path helpers

**Files:**
- Create: `tradingagents/research/fundamental_autoresearch/sec_fetch.py`
- Test: `tests/test_fundamental_autoresearch_sec_fetch.py`

**Step 1: Write the failing test**

Cover:
- deterministic submissions cache path
- deterministic companyfacts cache path

**Step 2: Run test to verify it fails**

Run:
```bash
python3 -m pytest tests/test_fundamental_autoresearch_sec_fetch.py -v
```

**Step 3: Write minimal implementation**

Implement small helpers:
- `submissions_cache_path(...)`
- `companyfacts_cache_path(...)`

**Step 4: Run test to verify it passes**

Run:
```bash
python3 -m pytest tests/test_fundamental_autoresearch_sec_fetch.py -v
```

**Step 5: Commit**

```bash
git add tradingagents/research/fundamental_autoresearch/sec_fetch.py tests/test_fundamental_autoresearch_sec_fetch.py
git commit -m "feat: add sec cache path helpers"
```

### Task 2: Add raw SEC fetch functions with injected HTTP client

**Files:**
- Modify: `tradingagents/research/fundamental_autoresearch/sec_fetch.py`
- Test: `tests/test_fundamental_autoresearch_sec_fetch.py`

**Step 1: Write the failing test**

Cover:
- fetch submissions payload
- fetch companyfacts payload
- pass required user agent header
- raise cleanly on non-200 status

**Step 2: Run test to verify it fails**

Run:
```bash
python3 -m pytest tests/test_fundamental_autoresearch_sec_fetch.py -k 'fetch_' -v
```

**Step 3: Write minimal implementation**

Implement:
- `fetch_submissions_payload(...)`
- `fetch_companyfacts_payload(...)`

Use injected session/client in tests.

**Step 4: Run test to verify it passes**

Run:
```bash
python3 -m pytest tests/test_fundamental_autoresearch_sec_fetch.py -k 'fetch_' -v
```

**Step 5: Commit**

```bash
git add tradingagents/research/fundamental_autoresearch/sec_fetch.py tests/test_fundamental_autoresearch_sec_fetch.py
git commit -m "feat: add raw sec fetch functions"
```

### Task 3: Add cache persistence helpers

**Files:**
- Modify: `tradingagents/research/fundamental_autoresearch/sec_fetch.py`
- Test: `tests/test_fundamental_autoresearch_sec_fetch.py`

**Step 1: Write the failing test**

Cover:
- writing submissions cache
- writing companyfacts cache
- round-tripping JSON content

**Step 2: Run test to verify it fails**

Run:
```bash
python3 -m pytest tests/test_fundamental_autoresearch_sec_fetch.py -k 'cache_' -v
```

**Step 3: Write minimal implementation**

Implement:
- `cache_submissions_payload(...)`
- `cache_companyfacts_payload(...)`

**Step 4: Run test to verify it passes**

Run:
```bash
python3 -m pytest tests/test_fundamental_autoresearch_sec_fetch.py -k 'cache_' -v
```

**Step 5: Commit**

```bash
git add tradingagents/research/fundamental_autoresearch/sec_fetch.py tests/test_fundamental_autoresearch_sec_fetch.py
git commit -m "feat: add sec cache persistence helpers"
```

### Task 4: Add universe-level cache fill helper

**Files:**
- Modify: `tradingagents/research/fundamental_autoresearch/sec_fetch.py`
- Test: `tests/test_fundamental_autoresearch_sec_fetch.py`

**Step 1: Write the failing test**

Cover:
- filling cache for multiple symbols
- skipping symbols with missing CIK mapping or fetch failures only when configured

**Step 2: Run test to verify it fails**

Run:
```bash
python3 -m pytest tests/test_fundamental_autoresearch_sec_fetch.py -k 'fill_' -v
```

**Step 3: Write minimal implementation**

Implement:
- `fill_sec_cache_for_universe(...)`

**Step 4: Run test to verify it passes**

Run:
```bash
python3 -m pytest tests/test_fundamental_autoresearch_sec_fetch.py -k 'fill_' -v
```

**Step 5: Commit**

```bash
git add tradingagents/research/fundamental_autoresearch/sec_fetch.py tests/test_fundamental_autoresearch_sec_fetch.py
git commit -m "feat: add sec cache fill helper"
```

### Task 5: Extend prep layer to persist prepared dataset artifact

**Files:**
- Modify: `tradingagents/research/fundamental_autoresearch/prepare.py`
- Test: `tests/test_fundamental_autoresearch_prepare.py`

**Step 1: Write the failing test**

Cover:
- writing prepared rows to a deterministic artifact path
- round-tripping the prepared dataset

**Step 2: Run test to verify it fails**

Run:
```bash
python3 -m pytest tests/test_fundamental_autoresearch_prepare.py -k 'prepared artifact' -v
```

**Step 3: Write minimal implementation**

Implement:
- prepared artifact writer / loader helpers

**Step 4: Run test to verify it passes**

Run:
```bash
python3 -m pytest tests/test_fundamental_autoresearch_prepare.py -k 'prepared artifact' -v
```

**Step 5: Commit**

```bash
git add tradingagents/research/fundamental_autoresearch/prepare.py tests/test_fundamental_autoresearch_prepare.py
git commit -m "feat: persist prepared fundamental dataset"
```

### Task 6: Add thin CLI for SEC cache fill and prep

**Files:**
- Modify: `cli/commands/fundamental_research.py`
- Test: `tests/test_cli_fundamental_research.py`

**Step 1: Write the failing test**

Cover:
- cache-fill command path
- prep-from-cache command path

**Step 2: Run test to verify it fails**

Run:
```bash
python3 -m pytest tests/test_cli_fundamental_research.py -k 'cache or prepare' -v
```

**Step 3: Write minimal implementation**

Add commands/options for:
- filling raw SEC cache
- building prepared dataset from cache

**Step 4: Run test to verify it passes**

Run:
```bash
python3 -m pytest tests/test_cli_fundamental_research.py -k 'cache or prepare' -v
```

**Step 5: Commit**

```bash
git add cli/commands/fundamental_research.py tests/test_cli_fundamental_research.py
git commit -m "feat: add sec cache and prep cli"
```

### Task 7: Run focused regression and update memory

**Files:**
- Modify: `memory/WORKING.md`
- Modify: `memory/2026-03-08.md`
- Modify: `memory/MEMORY.md`

**Step 1: Run focused regression**

Run:
```bash
python3 -m pytest tests/test_fundamental_autoresearch_sec_fetch.py tests/test_fundamental_autoresearch_prepare.py tests/test_cli_fundamental_research.py -v
```

**Step 2: Update memory**

Record:
- cache-first SEC policy
- sidecar-only status remains unchanged
- next remaining step after this slice

**Step 3: Commit**

```bash
git add memory/WORKING.md memory/2026-03-08.md memory/MEMORY.md
git commit -m "docs: record sec cache layer for fundamental autoresearch"
```
