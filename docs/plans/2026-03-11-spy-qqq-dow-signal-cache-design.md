# SPY QQQ DOW Signal Cache Design

## Goal

Build a persistent technical signal cache for the current `SPY + QQQ + DOW` constituent universe so the system can:

- backfill and reuse daily price history instead of redownloading everything
- compute `KAMA + bullish FVG regime` signals once and update incrementally
- answer `is this ticker in the buy zone right now?` without rerunning a full replay
- produce broader, more trustworthy signal statistics than the small ad hoc basket probes

## Problem

Today the technical replay work is still one-off and artifact-driven.

That means:

- each broader experiment redownloads history and recomputes features from scratch
- there is no canonical current-universe store for `SPY`, `QQQ`, and `DOW`
- there is no persistent daily signal state table
- there is no fast operator query for current buy-zone status
- the system cannot cheaply react when a new ticker is flagged by X-feed, discovery, or manual review

This is workable for experiments, but not for a durable signal engine.

## Constraints

- first slice uses **current constituents only**
- this is for broad signal validation and live screening, not point-in-time index reconstruction
- historical results must be labeled as **current-constituent replay**
- implementation should reuse existing repo patterns:
  - SQLite persistence
  - `eval_results/control/*` database/artifact layout
  - current `kama_recall.py` feature logic
  - existing CLI command surface in `cli/commands/technical.py`

## Approaches

### 1. SQLite signal engine

Store:

- current universe membership
- daily OHLCV history
- daily computed signal state
- current buy-zone snapshot

Pros:

- matches existing repository patterns
- good fit for incremental updates
- easy to query from CLI and future pipeline steps
- simple enough for the first live slice

Cons:

- less ideal than columnar analytics stores for very large historical research later

### 2. DuckDB + Parquet analytics store

Pros:

- strong for wide historical scans
- very good for batch analytics and slicing

Cons:

- weaker operationally for “what changed for this ticker today?”
- adds complexity before the signal engine behavior is stable

### 3. JSON artifact cache only

Pros:

- fastest to hack together

Cons:

- poor queryability
- weak incremental semantics
- quickly becomes messy once the universe expands

## Recommendation

Use **SQLite** for the first slice.

It is the cleanest fit for:

- incremental history sync
- persistent signal state
- current buy-zone queries
- future pipeline integration

If the research surface later expands beyond this universe and into heavier analytics, a DuckDB mirror can be added later without replacing the live operational store.

## Scope

First slice covers:

- current `SPY`, `QQQ`, and `DOW` constituents
- daily OHLCV cache
- daily `KAMA + bullish FVG regime` signal state
- current buy-zone snapshot
- CLI commands to:
  - refresh universe membership
  - sync prices and signals
  - query buy-zone status for one ticker
  - summarize current buy-zone names

## Non-Goals

- no point-in-time constituent reconstruction
- no full live pipeline wiring yet
- no transaction-cost model
- no portfolio auto-promotion from this engine in the first slice
- no replacement of existing `kama-backtest` replay artifacts

## Data Model

Database path:

- `eval_results/control/technical_signal_cache.db`

### `universe_membership_current`

Columns:

- `source_index` (`SPY`, `QQQ`, `DOW`)
- `ticker`
- `company_name`
- `sector`
- `as_of_date`
- `fetched_at_utc`

Primary key:

- `(source_index, ticker)`

Purpose:

- canonical current constituent store
- source tagging for later audits and filtering

### `market_history_daily`

Columns:

- `ticker`
- `date`
- `open`
- `high`
- `low`
- `close`
- `volume`
- `source`
- `updated_at_utc`

Primary key:

- `(ticker, date)`

Purpose:

- cached daily price history
- no recomputation from scratch on every run

### `signal_kama_fvg_daily`

Columns:

- `ticker`
- `date`
- `fast_kama`
- `slow_kama`
- `kama_spread_pct`
- `cross_up`
- `bullish_state`
- `bullish_fvg_regime_active`
- `bullish_fvg_streak`
- `bullish_fvg_regime_age_bars`
- `buy_zone`
- `buy_zone_reason`
- `score`
- `computed_at_utc`

Primary key:

- `(ticker, date)`

Purpose:

- durable per-day signal state
- base table for backtests, audits, and current status

### `buy_zone_state_current`

Columns:

- `ticker`
- `as_of_date`
- `in_buy_zone`
- `status_label`
- `reason`
- `last_cross_up_date`
- `bullish_fvg_regime_active`
- `bullish_fvg_streak`
- `bullish_fvg_regime_age_bars`
- `fast_kama`
- `slow_kama`
- `score`
- `updated_at_utc`

Primary key:

- `ticker`

Purpose:

- fast operator lookup for “is this in buy zone?”

## Buy-Zone Contract

First-slice contract:

- `BUY_TRIGGER`
  - latest bar has `cross_up = true`
  - latest bar is inside active bullish FVG regime
- `BUY_ZONE`
  - latest bar remains:
    - `bullish_state = true`
    - `bullish_fvg_regime_active = true`
  - and the last cross-up is still recent enough to matter

Default freshness rule:

- keep `BUY_ZONE` active for `10` bars after cross-up
- after that, status degrades to `TREND_UP_NOT_FRESH`

This gives operators two useful answers:

- a fresh trigger
- a still-valid but aging trend entry state

The freshness window should be config-driven.

## Universe Source Strategy

Use current constituent builders for:

- `SPY` → S&P 500 constituent table
- `QQQ` → Nasdaq-100 constituent table
- `DOW` → Dow Jones Industrial Average table

Implementation target:

- build current-universe snapshots from maintained public tables via `pandas.read_html`
- normalize symbols to the repo’s ticker conventions
- persist both the raw snapshot artifact and normalized DB rows

The key point is consistency, not perfect index-history reconstruction.

## Data Flow

### 1. Universe refresh

Command:

- `python3 -m cli.main technical-universe-refresh --sources SPY --sources QQQ --sources DOW`

Behavior:

- fetch current constituents
- normalize tickers
- write:
  - `universe_membership_current`
  - JSON artifact under `eval_results/control/technical_universe/`

### 2. Price/signal sync

Command:

- `python3 -m cli.main technical-signal-sync`

Behavior:

- load current deduped universe
- for each ticker:
  - fetch only missing/new daily OHLCV rows
  - recompute signal rows only for the affected tail window
  - refresh `buy_zone_state_current`

### 3. Buy-zone query

Command:

- `python3 -m cli.main buy-zone AAPL`

Behavior:

- read `buy_zone_state_current`
- return:
  - current status
  - reason
  - last trigger date
  - current regime state

### 4. Buy-zone summary

Command:

- `python3 -m cli.main buy-zone-summary`

Behavior:

- list current universe names in:
  - `BUY_TRIGGER`
  - `BUY_ZONE`
  - optionally `TREND_UP_NOT_FRESH`

## Incremental Recompute Rules

Universe changes:

- add new constituents on refresh
- keep removed names in history tables
- remove only from current membership and current buy-zone snapshot

History updates:

- fetch from last stored date forward
- on each ticker refresh, recompute only a bounded trailing window
  - enough bars to stabilize KAMA and FVG regime state
  - recommended initial tail window: `250` bars

Signal recompute:

- replace `signal_kama_fvg_daily` rows for the recompute window
- upsert `buy_zone_state_current`

## CLI And Operator Surface

Add commands to `cli/commands/technical.py`:

- `technical-universe-refresh`
- `technical-signal-sync`
- `buy-zone`
- `buy-zone-summary`

These should support:

- table output for operators
- JSON output for automation and future pipeline calls

## Testing

Add focused tests for:

- current-universe fetch/normalize behavior
- SQLite schema initialization and upserts
- incremental OHLCV write behavior
- signal recompute correctness on tail windows
- buy-zone classification:
  - `BUY_TRIGGER`
  - `BUY_ZONE`
  - `TREND_UP_NOT_FRESH`
  - `NOT_IN_BUY_ZONE`
- CLI JSON/table behavior

## Success Criteria

- current `SPY + QQQ + DOW` universe can be refreshed deterministically
- price history is cached and reused across runs
- current buy-zone state for any ticker is a fast DB lookup
- replay and live screening share one canonical signal-state computation path
- broader validation can run over a meaningful current-universe sample without repeating full history downloads every time
