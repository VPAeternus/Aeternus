# Technical Ignition Scout Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a discovery-only `technical_ignition` scout that promotes cached `BUY_TRIGGER` / `BUY_ZONE` names into the filtered universe and exposes them through existing discovery artifacts.

**Architecture:** Read current technical setup state from the SQLite cache, convert fresh setup rows into scout-style promoted symbols plus audit signals, and thread those symbols into `discover()` through a dedicated universe tier. Reuse the existing `scout_audit`, `universe_filter`, and `discovery_delta` paths instead of inventing parallel reporting.

**Tech Stack:** Python, pytest, Typer/Rich CLI, SQLite-backed cache, existing dealflow pipeline artifacts

---

### Task 1: Add scout unit tests

**Files:**
- Create: `tests/test_technical_ignition_scout.py`
- Reference: `tradingagents/dealflow/technical_signal_store.py`

**Step 1: Write the failing tests**

Add tests for:
- promoting only `BUY_TRIGGER` / `BUY_ZONE` rows for the requested date
- leaving `TREND_UP_NOT_FRESH` rows in audit-only stale output
- returning empty output when the DB is missing

**Step 2: Run test to verify it fails**

Run:
```bash
python3 -m pytest tests/test_technical_ignition_scout.py -q
```

Expected:
- fail because the scout module does not exist yet

**Step 3: Write minimal implementation**

Create `tradingagents/dealflow/sources/technical_ignition_scout.py` with:
- cache DB path constant
- `scan_technical_ignition_setups(...)`
- row normalization for promoted and stale entries
- generated `signals` payload for promoted rows

**Step 4: Run test to verify it passes**

Run:
```bash
python3 -m pytest tests/test_technical_ignition_scout.py -q
```

Expected:
- pass

### Task 2: Add filtered-universe tier support

**Files:**
- Modify: `tradingagents/dealflow/akg_universe.py`
- Test: `tests/test_akg_universe_filter.py`

**Step 1: Write the failing test**

Add a test proving `technical_ignition_symbols`:
- are included in the filtered universe
- receive tier `T3D_TECHNICAL_IGNITION`
- are not mislabeled as `MANUAL`

**Step 2: Run test to verify it fails**

Run:
```bash
python3 -m pytest tests/test_akg_universe_filter.py -k technical_ignition -q
```

Expected:
- fail because the universe builder has no such parameter / tier

**Step 3: Write minimal implementation**

Update:
- `build_filtered_universe(...)`
- `build_universe_from_akg(...)`

Add:
- `technical_ignition_symbols` optional parameter
- `T3D_TECHNICAL_IGNITION` assignment
- rule snapshot count for the new tier

**Step 4: Run test to verify it passes**

Run:
```bash
python3 -m pytest tests/test_akg_universe_filter.py -k technical_ignition -q
```

Expected:
- pass

### Task 3: Add discover integration tests

**Files:**
- Modify: `tests/test_dealflow_pipeline.py`
- Reference: `tradingagents/dealflow/pipeline.py`

**Step 1: Write the failing tests**

Add tests proving `discover()`:
- runs the scout
- threads promoted symbols into universe build
- persists `technical_ignition` details inside `scout_audit.json`
- exposes promoted rows through `signals`

**Step 2: Run test to verify it fails**

Run:
```bash
python3 -m pytest tests/test_dealflow_pipeline.py -k technical_ignition -q
```

Expected:
- fail because `discover()` and `_build_scout_audit()` do not yet support the scout

**Step 3: Write minimal implementation**

Update `tradingagents/dealflow/pipeline.py` to:
- call the scout inside `discover()`
- pass promoted symbols into `build_universe_from_akg(...)`
- return `technical_ignition_symbols` and `technical_ignition_count`
- extend `_build_scout_audit(...)` with a `technical_ignition` section and promoted `signals`

**Step 4: Run test to verify it passes**

Run:
```bash
python3 -m pytest tests/test_dealflow_pipeline.py -k technical_ignition -q
```

Expected:
- pass

### Task 4: Add config and source exports

**Files:**
- Modify: `tradingagents/default_config.py`
- Modify: `tradingagents/dealflow/sources/__init__.py`
- Modify: `tradingagents/dealflow/sources/README.md`

**Step 1: Write the failing test**

Add or extend a focused test if needed to prove default config exposes the DB path / enable flag used by the pipeline.

**Step 2: Run test to verify it fails**

Run the focused config/scout test.

**Step 3: Write minimal implementation**

Add:
- `dealflow_technical_ignition_enabled`
- `dealflow_technical_signal_db_path`

Export the scout in `sources/__init__.py`.
Document it in `sources/README.md`.

**Step 4: Run test to verify it passes**

Run the focused config/scout test.

### Task 5: Run focused regression suite

**Files:**
- Test only

**Step 1: Run the combined focused suite**

Run:
```bash
python3 -m pytest tests/test_technical_ignition_scout.py tests/test_akg_universe_filter.py tests/test_dealflow_pipeline.py tests/test_technical_market_cache.py tests/test_cli_dealflow.py -k 'technical_ignition or buy_zone or technical_signal_sync' -q
```

Expected:
- all targeted tests pass

**Step 2: Run a live discover smoke**

Run:
```bash
python3 -m cli.main discover --date 2026-03-10 --format json
```

Expected:
- success
- output includes `technical_ignition_count`
- persisted `scout_audit.json` includes `technical_ignition`

### Task 6: Update memory

**Files:**
- Modify: `memory/WORKING.md`
- Modify: `memory/2026-03-11.md`
- Modify: `memory/MEMORY.md` only if the architecture decision is durable

**Step 1: Record what changed**

Document:
- the new scout
- the new universe tier
- focused tests run
- live smoke result

**Step 2: Keep entries concise**

Do not add redundant changelog detail.
