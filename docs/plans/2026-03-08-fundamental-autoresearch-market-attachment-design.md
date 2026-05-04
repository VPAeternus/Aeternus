# Fundamental Autoresearch Market Attachment Design

## Goal

Make the Fundamental Pillar Autoresearch Harness produce its first real evaluable dataset by attaching deterministic sector identity and point-in-time forward returns to the prepared SEC filing rows.

## Why This Slice

The harness now has:
- SEC raw cache
- SEC-official ticker→CIK resolution
- filing-effective prepared rows
- deterministic scoring and evaluation

The first live `large_cap_v1` run proved the ingestion path works, but the dataset is not yet evaluable:
- all sectors are `Unknown`
- no forward returns are attached
- evaluation therefore produces `0` observations

This slice closes that gap without changing the score formula.

## Recommended Architecture

Add two explicit attachments:

1. `sector_map.py`
- owns a deterministic static sector map for `large_cap_v1`
- no network
- no inference

2. `market_data.py`
- downloads adjusted close history for the controlled universe
- computes forward returns from each row’s `effective_market_date`
- attaches:
  - `return_20d`
  - `return_60d`
  - `return_120d`
  - `return_252d`

Keep these concerns separate so debugging stays clean:
- sector identity bug
- return attachment bug
- scoring bug

## Data Contract

Prepared rows remain the core dataset shape and gain only the return fields:

- `return_20d`
- `return_60d`
- `return_120d`
- `return_252d`

The evaluator remains unchanged and continues to use sector-neutral `60d` rank IC as the primary metric.

## Point-in-Time Rules

- Use adjusted close history only
- Entry anchor is the first tradable session on or after `effective_market_date`
- Forward returns are measured from that entry anchor
- Missing price coverage should yield `None`, not synthetic values

This preserves the existing no-lookahead contract.

## CLI Surface

Add a thin enrichment command instead of overloading the existing prepare command:

- `fundamental-research-attach-returns`

Inputs:
- prepared dataset JSON path
- optional output path or run-name

Output:
- enriched prepared dataset JSON

This keeps:
- SEC prep
- market enrichment
- evaluation

as three separable stages.

## Testing

Add fixture-driven tests for:
- deterministic `large_cap_v1` sector mapping
- forward-return attachment from mocked adjusted close series
- missing price history behavior
- CLI round-trip for the new attachment command

No live yfinance calls in unit tests.

## Shipping Standard

This slice is complete when:
- `large_cap_v1` prepared rows carry deterministic sectors
- real forward returns can be attached reproducibly
- the live SEC-prepared dataset produces non-zero evaluation observations
- the scorer runs on a real enriched dataset end to end
