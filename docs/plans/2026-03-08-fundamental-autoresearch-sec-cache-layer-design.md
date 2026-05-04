# Fundamental Autoresearch SEC Cache Layer Design

## Goal

Add the real SEC fetch/cache layer for the Fundamental Pillar Autoresearch Harness so the harness can prepare reproducible point-in-time rows from regulator-grade raw payloads instead of hand-built fixtures.

## Why This Slice

The harness scaffold is already in place:
- contracts
- universe
- filing time semantics
- SEC payload normalization
- prepared-row builder from cached data
- deterministic scoring/evaluation

The next bottleneck is raw data acquisition. Without a cache-first SEC layer, the harness remains a fixture-driven prototype instead of a real research engine.

## Recommended Architecture

Build a cache-first layer with three stages:

1. `fetch_raw_sec_payloads`
- fetch SEC `submissions` and `companyfacts`
- persist raw JSON locally

2. `build_filing_snapshots`
- use cached payloads to derive supported filing/event anchors

3. `build_prepared_feature_rows`
- use cached payloads + filing anchors to generate scoring-ready rows

The actual harness should always run from cache in tests and in reproducible experiments.

## Source Scope

v1 sources:
- SEC `submissions`
- SEC `companyfacts`

No other vendor fundamentals in this layer yet.

## Storage Layout

Use a dedicated harness-owned cache root:

- `eval_results/fundamental_autoresearch/sec_cache/submissions/<ticker>.json`
- `eval_results/fundamental_autoresearch/sec_cache/companyfacts/<ticker>.json`
- `eval_results/fundamental_autoresearch/sec_cache/prepared/<run_name>.json`

This keeps the system inspectable and reproducible.

## Safety and Testing

The fetcher must:
- set a proper SEC user agent
- support dependency injection for HTTP in tests
- never require live network in unit tests

Tests should remain fixture-driven while the live fetcher is used only in real runs.

## Shipping Standard

This slice is complete when:
- raw SEC payloads can be fetched and cached for the v1 universe
- prepared rows can be built from those cached payloads
- the existing scorer/evaluator can run on the resulting prepared dataset
- the whole path remains reproducible from cache
