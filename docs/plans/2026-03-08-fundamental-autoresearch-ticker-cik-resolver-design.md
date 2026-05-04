# Fundamental Autoresearch Ticker CIK Resolver Design

## Goal

Replace the temporary user-supplied ticker-to-CIK mapping path with a harness-owned resolver that uses SEC's official `company_tickers.json` as the only source of truth for ticker→CIK resolution.

## Why This Slice

The SEC cache layer is functional, but `fundamental-research-cache-fill` still requires a manual mapping file. That is fine for scaffolding, but it is not the right contract for a regulator-grade sidecar truth engine. The harness should own its own SEC identity resolution.

## Recommended Architecture

Add a small resolver layer inside `sec_fetch.py`:

1. Fetch SEC `company_tickers.json`
2. Cache the raw payload locally under the harness cache root
3. Build a filtered ticker→CIK map for the requested universe
4. Fall back only to the last cached SEC snapshot if the live fetch fails
5. Fail clearly if neither live nor cached SEC metadata is available

This keeps lineage clean: SEC official file only, cached SEC file only as fallback, no third-party mapping sources.

## Resolver Contract

The resolver should:

- use `https://www.sec.gov/files/company_tickers.json`
- send a proper SEC `User-Agent`
- persist the raw payload to a deterministic cache path
- normalize ticker aliases enough to handle SEC punctuation differences such as `BRK-B` vs `BRK.B`
- return only the requested universe entries
- fail loudly if a requested ticker cannot be resolved and no cached SEC metadata exists

## CLI Impact

`fundamental-research-cache-fill` should no longer require `--ticker-cik-json`.

Instead it should:
- resolve the map internally from SEC live/cache
- then pass that map into the existing cache-fill helper

This keeps the operator surface clean and makes the harness runnable without hand-built glue files.

## Testing

Tests should stay fully offline and fixture-driven.

Add coverage for:
- deterministic SEC ticker-map cache path
- live SEC ticker-map fetch with required `User-Agent`
- fallback to cached SEC payload when live fetch fails
- clear error when neither live nor cached SEC payload exists
- ticker alias handling for dot/hyphen variants
- CLI cache-fill using the resolver instead of a user-supplied JSON path

## Shipping Standard

This slice is complete when:
- the harness can resolve `large_cap_v1` ticker→CIK mappings from SEC official metadata
- the resolver is cache-first and reproducible
- the CLI no longer depends on a manual mapping file
- focused harness tests stay green
