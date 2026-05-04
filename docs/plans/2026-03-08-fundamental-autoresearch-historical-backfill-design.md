# Fundamental Autoresearch Historical Backfill Design

Date: 2026-03-08

## Objective

Extend the Fundamental Pillar Autoresearch Harness from latest-only filing snapshots to a point-in-time historical dataset covering all supported filings since 2009 for the `large_cap_v1` universe.

## Principles

- Use SEC-native data only.
- Keep the pipeline cache-first and reproducible.
- Treat filing snapshots, not calendar days, as the unit of truth.
- Preserve point-in-time semantics:
  - filing acceptance time
  - effective market date
  - first tradable session on or after effective date

## SEC History Contract

Use three cache layers:

- `submissions/<ticker>.json`
  - primary submissions payload
- `submissions_history/<ticker>/<file>.json`
  - historical submissions shard files referenced by `filings.files`
- `companyfacts/<ticker>.json`
  - point-in-time financial facts source

Historical shard files are fetched from:

- `https://data.sec.gov/submissions/<file_name>`

## Prep Contract

`build_prepared_rows_from_cache(...)` now supports:

- `include_history`
- `latest_only`
- `start_year`

Behavior:

- latest-only mode preserves existing v1 behavior
- all-filings mode loads:
  - base submissions payload
  - cached historical shard payloads
- filings are deduplicated by:
  - `filing_type`
  - `accepted_at`
  - `period_end`
- rows before `start_year` are excluded

## CLI Contract

`fundamental-research-cache-fill`
- new flag:
  - `--include-history`

`fundamental-research-prepare`
- new flags:
  - `--all-filings`
  - `--start-year`

## Success Criteria

- cache layer fetches and stores SEC historical shard files
- all-filings prep builds a large point-in-time dataset from cache
- returns attachment works on that dataset
- baseline evaluation runs on nontrivial `60d` sample size

## Non-Goals

- no live pillar integration
- no LLM inner loop
- no pre-2009 legacy filing parsing
- no benchmark-relative return attachment in this slice
