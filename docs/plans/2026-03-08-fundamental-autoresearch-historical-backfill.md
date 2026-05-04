# Fundamental Autoresearch Historical Backfill Plan

Date: 2026-03-08

## Tasks

1. Add SEC historical submissions shard fetch/cache support.
2. Extend prep to build all supported filing snapshots since 2009.
3. Add CLI flags for history-aware cache fill and all-filings prepare.
4. Verify with focused tests.
5. Run the first real `large_cap_v1` historical backfill.
6. Attach forward returns and evaluate the baseline score.

## Verification

- focused harness regression suite
- first real dataset counts:
  - rows
  - date range
  - return coverage by horizon
- first real baseline summary artifact

## Result Target

Produce a real, point-in-time, `2009+` filing dataset large enough to judge whether the deterministic baseline fundamental score has predictive value before any scorer optimization.
