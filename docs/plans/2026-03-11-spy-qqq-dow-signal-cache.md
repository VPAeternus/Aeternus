# SPY QQQ DOW Signal Cache Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a SQLite-backed technical signal cache for the current `SPY + QQQ + DOW` universe that can backfill OHLCV, persist `KAMA + bullish FVG regime` state, and answer buy-zone queries without rerunning full replays.

**Architecture:** Add a small SQLite repository under `eval_results/control/technical_signal_cache.db`, feed it with current-universe snapshots plus cached daily OHLCV, and compute a canonical per-day signal table plus a current buy-zone snapshot. Keep the first slice current-constituent only and reuse the existing `kama_recall.py` / `fvg_recall.py` feature logic rather than inventing a second technical engine.

**Tech Stack:** Python 3, SQLite (`sqlite3`), pandas, yfinance, Typer/Rich, pytest

---

### Task 1: Add the SQLite store and schema

**Files:**
- Create: `tradingagents/dealflow/technical_signal_store.py`
- Test: `tests/test_technical_signal_store.py`

**Step 1: Write the failing test**

Cover:

- schema initialization creates:
  - `universe_membership_current`
  - `market_history_daily`
  - `signal_kama_fvg_daily`
  - `buy_zone_state_current`
- upsert behavior is idempotent

**Step 2: Run test to verify it fails**

Run:

```bash
python3 -m pytest tests/test_technical_signal_store.py -q
```

Expected:

- FAIL because the store module does not exist yet

**Step 3: Write minimal implementation**

Implement:

- `SQLiteTechnicalSignalStore`
- `initialize()`
- `connection()`
- upsert helpers for each table
- simple query helpers for current buy-zone status

**Step 4: Run test to verify it passes**

Run:

```bash
python3 -m pytest tests/test_technical_signal_store.py -q
```

Expected:

- PASS

**Step 5: Commit**

```bash
git add tests/test_technical_signal_store.py tradingagents/dealflow/technical_signal_store.py
git commit -m "feat: add technical signal sqlite store"
```

### Task 2: Add current-universe builders for SPY QQQ DOW

**Files:**
- Create: `tradingagents/dealflow/current_universe.py`
- Test: `tests/test_current_universe.py`

**Step 1: Write the failing test**

Cover:

- `fetch_current_universe(["SPY","QQQ","DOW"])` normalizes rows into:
  - `source_index`
  - `ticker`
  - `company_name`
  - `sector`
- duplicate tickers across sources are preserved at source-row level
- symbol normalization handles expected punctuation conventions

**Step 2: Run test to verify it fails**

Run:

```bash
python3 -m pytest tests/test_current_universe.py -q
```

Expected:

- FAIL because the module does not exist yet

**Step 3: Write minimal implementation**

Implement:

- current constituent fetchers using `pandas.read_html`
- normalized output rows
- a dedupe helper for ticker-level universe sync
- raw snapshot artifact serializer

**Step 4: Run test to verify it passes**

Run:

```bash
python3 -m pytest tests/test_current_universe.py -q
```

Expected:

- PASS

**Step 5: Commit**

```bash
git add tests/test_current_universe.py tradingagents/dealflow/current_universe.py
git commit -m "feat: add current universe builders for spy qqq dow"
```

### Task 3: Add incremental OHLCV sync helpers

**Files:**
- Create: `tradingagents/dealflow/technical_market_cache.py`
- Modify: `tradingagents/dataflows/y_finance.py`
- Test: `tests/test_technical_market_cache.py`

**Step 1: Write the failing test**

Cover:

- first sync backfills history for a ticker into `market_history_daily`
- second sync only appends missing dates
- unchanged symbols do not rewrite the entire history table

**Step 2: Run test to verify it fails**

Run:

```bash
python3 -m pytest tests/test_technical_market_cache.py -q
```

Expected:

- FAIL because the sync helper does not exist yet

**Step 3: Write minimal implementation**

Implement:

- tail-aware history sync for a list of tickers
- reuse `yfinance` fetch logic
- persist normalized OHLCV rows into SQLite

**Step 4: Run test to verify it passes**

Run:

```bash
python3 -m pytest tests/test_technical_market_cache.py -q
```

Expected:

- PASS

**Step 5: Commit**

```bash
git add tests/test_technical_market_cache.py tradingagents/dealflow/technical_market_cache.py tradingagents/dataflows/y_finance.py
git commit -m "feat: add incremental technical market cache sync"
```

### Task 4: Add canonical KAMA FVG signal-state computation

**Files:**
- Create: `tradingagents/dealflow/technical_signal_engine.py`
- Modify: `tradingagents/dealflow/kama_recall.py`
- Test: `tests/test_technical_signal_engine.py`

**Step 1: Write the failing test**

Cover:

- compute per-day signal rows from cached OHLCV
- `buy_zone` classification:
  - `BUY_TRIGGER`
  - `BUY_ZONE`
  - `TREND_UP_NOT_FRESH`
  - `NOT_IN_BUY_ZONE`
- bounded tail recompute replaces only recent rows

**Step 2: Run test to verify it fails**

Run:

```bash
python3 -m pytest tests/test_technical_signal_engine.py -q
```

Expected:

- FAIL because the engine does not exist yet

**Step 3: Write minimal implementation**

Implement:

- shared signal-row builder from OHLCV
- latest-state classifier
- recompute window support
- write paths into:
  - `signal_kama_fvg_daily`
  - `buy_zone_state_current`

**Step 4: Run test to verify it passes**

Run:

```bash
python3 -m pytest tests/test_technical_signal_engine.py -q
```

Expected:

- PASS

**Step 5: Commit**

```bash
git add tests/test_technical_signal_engine.py tradingagents/dealflow/technical_signal_engine.py tradingagents/dealflow/kama_recall.py
git commit -m "feat: add canonical technical signal engine"
```

### Task 5: Add CLI commands

**Files:**
- Modify: `cli/commands/technical.py`
- Modify: `tests/test_cli_dealflow.py`

**Step 1: Write the failing test**

Cover CLI commands:

- `technical-universe-refresh`
- `technical-signal-sync`
- `buy-zone`
- `buy-zone-summary`

Validate:

- JSON output shape
- human-readable table output
- missing ticker / missing DB cases fail clearly

**Step 2: Run test to verify it fails**

Run:

```bash
python3 -m pytest tests/test_cli_dealflow.py -k "technical_universe_refresh or technical_signal_sync or buy_zone" -q
```

Expected:

- FAIL because the commands do not exist yet

**Step 3: Write minimal implementation**

Implement CLI wiring into the new modules and use the existing Rich output style from `technical.py`.

**Step 4: Run test to verify it passes**

Run:

```bash
python3 -m pytest tests/test_cli_dealflow.py -k "technical_universe_refresh or technical_signal_sync or buy_zone" -q
```

Expected:

- PASS

**Step 5: Commit**

```bash
git add cli/commands/technical.py tests/test_cli_dealflow.py
git commit -m "feat: add technical signal cache cli commands"
```

### Task 6: Add end-to-end slice verification

**Files:**
- Modify: `tests/test_cli_dealflow.py`
- Optionally create: `tests/fixtures/current_universe/`

**Step 1: Write the failing test**

Cover:

- refresh current universe
- sync a small mocked subset of prices
- verify `buy-zone-summary` returns expected tickers and statuses

**Step 2: Run test to verify it fails**

Run:

```bash
python3 -m pytest tests/test_cli_dealflow.py -k "buy_zone_summary_end_to_end" -q
```

Expected:

- FAIL until all pieces are wired together

**Step 3: Write minimal implementation**

Only add the wiring needed to satisfy the end-to-end flow.

**Step 4: Run test to verify it passes**

Run:

```bash
python3 -m pytest tests/test_cli_dealflow.py -k "buy_zone_summary_end_to_end" -q
```

Expected:

- PASS

**Step 5: Commit**

```bash
git add tests/test_cli_dealflow.py tests/fixtures/current_universe
git commit -m "test: verify technical signal cache end to end"
```

### Task 7: Run focused verification and live smoke

**Files:**
- No code changes required unless a failure appears

**Step 1: Run focused tests**

```bash
python3 -m pytest \
  tests/test_technical_signal_store.py \
  tests/test_current_universe.py \
  tests/test_technical_market_cache.py \
  tests/test_technical_signal_engine.py \
  tests/test_cli_dealflow.py -k "technical_universe_refresh or technical_signal_sync or buy_zone" -q
```

Expected:

- PASS

**Step 2: Run live smoke on real universe metadata**

```bash
python3 -m cli.main technical-universe-refresh --sources SPY --sources QQQ --sources DOW --format table
python3 -m cli.main technical-signal-sync --format table
python3 -m cli.main buy-zone NVDA --format table
python3 -m cli.main buy-zone-summary --format table
```

Expected:

- current-universe snapshot persisted
- DB created under `eval_results/control/technical_signal_cache.db`
- buy-zone query returns a deterministic status row

**Step 3: Commit**

```bash
git add docs/plans/2026-03-11-spy-qqq-dow-signal-cache-design.md docs/plans/2026-03-11-spy-qqq-dow-signal-cache.md
git commit -m "docs: add technical signal cache design and plan"
```
