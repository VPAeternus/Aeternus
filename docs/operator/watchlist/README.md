# Watchlist CLI

This document defines the approved operator contract for the manual watchlist.

## Purpose

The watchlist is a simple manual ticker feed into the pipeline.

It is not:
- a manual scoring surface
- a manual lane-selection surface
- a direct-to-research override

Today, watchlist symbols feed into discovery seeding. They are guaranteed entry into the pipeline's early universe construction flow, but they are not automatically sent straight to deep research.

## Approved Commands

Use only these three commands:

```bash
python3 -m cli.main watchlist add AAPL, MSFT, GOOGL
python3 -m cli.main watchlist remove TSLA, AAPL
python3 -m cli.main watchlist list
```

Historical/debug view:

```bash
python3 -m cli.main watchlist list --all
```

## Input Rules

- Input is not case sensitive.
- Symbols are normalized to uppercase.
- `.` is normalized to `-`.
- Comma-separated input is supported.
- Quoted and unquoted multi-symbol shell forms both work.

Examples:

```bash
python3 -m cli.main watchlist add aapl, msft, googl
python3 -m cli.main watchlist add 'AAPL, MSFT, GOOGL'
python3 -m cli.main watchlist remove tsla, aapl
python3 -m cli.main watchlist remove 'TSLA, AAPL'
```

## Stored Schema

Each watchlist item is intentionally minimal:

```json
{
  "symbol": "AAPL",
  "created_at": "2026-03-22T16:36:42.916969+00:00",
  "active": true,
  "context_snapshot": {
    "akg_found": true,
    "display_name": "Apple Inc",
    "sector": "semis_ai_infrastructure",
    "asset_class": "Equity",
    "aeternus_score": 80,
    "last_scored_date": "2026-03-10"
  }
}
```

## What Was Removed

These are not part of the watchlist contract anymore:

- `priority`
- `lane_preference`
- `note`
- `ttl_days`
- `expires_at`

Those concepts may still exist elsewhere in downstream pipeline logic, but they are no longer part of manual watchlist input.

## Context Enrichment

When a symbol is added, the system also performs an internal context lookup and stores a lightweight `context_snapshot`.

This snapshot is populated from internal Aeternus context, primarily AKG-backed company data. The goal is to make the watchlist immediately useful to the frontend without requiring a separate research run.

## List Semantics

- `watchlist list`
  - returns active items only
- `watchlist list --all`
  - returns active and inactive items

Removing a symbol does not delete history. It marks the item inactive.

## Pipeline Semantics

Watchlist items currently flow like this:

1. operator adds ticker(s) to watchlist
2. watchlist stores normalized active records
3. discovery loads active watchlist items
4. symbols are added to `manual_symbols_set`
5. pipeline continues through normal candidate_list / queue / research selection

That means:
- watchlist feeds the pipeline
- watchlist does not bypass the pipeline
- watchlist does not force immediate deep research

## Future Direction

A separate manual research path can be added later for:

- single-ticker investigation
- direct research run on user-selected names
- manual "research now" action from the frontend

That should be a separate command/workflow, not part of the watchlist contract.
