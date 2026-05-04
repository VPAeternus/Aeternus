# Universe Filter Audit Design

## Goal

Make the first universe filter a first-class operator-visible stage so daily runs can verify:

- the first filter actually ran
- which tiers contributed names
- whether discovery sources and technical recall channels are represented
- whether the filtered universe looks healthy before collectors begin

## Problem

Today the first universe filter runs implicitly inside `discover()`.

That means:

- operators can run discovery but still not know whether the first filter behaved correctly
- the stage has no dedicated artifact
- there is no explicit CLI checkpoint comparable to `x-feed --status`

This makes daily debugging harder than it needs to be.

## Design

Add a first-class `Universe Filter Audit` layer with:

1. A persisted artifact:
   - `eval_results/deal_flow/<date>/universe_filter.json`

2. A report builder:
   - create a normalized report from:
     - filtered universe rows
     - tier map
     - universe ledger
     - scout/discovery source counts
     - recall channel selections
     - manual/X-feed inclusion counts

3. A CLI surface:
   - `python3 -m cli.main universe-filter --date YYYY-MM-DD --status`
   - `python3 -m cli.main universe-filter --date YYYY-MM-DD --format json`

4. Read-only status checks:
   - no runtime behavior change
   - no pipeline split
   - this remains an audit surface over the current first-filter implementation

## Report Contents

The report should contain:

- `as_of_date`
- `universe_size`
- `tier_counts`
- `source_counts`
- `overlap_counts`
- `rule_snapshot`
- `health_checks`
- `sample_symbols`

### Tier counts

- `T1_ANCHOR`
- `T2_NEIGHBOR`
- `T3_SCOUT`
- `T3B_FVG_RECALL`
- `T3C_FMA_RECALL`
- `T4_DARK`
- `T5_RESCAN`
- `T6_PORTFOLIO`
- `MANUAL`

### Source counts

- manual X-feed merged symbols
- breakout alerts
- IV force queue
- insider buy clusters
- insider sell clusters
- FVG recall selected
- FMA recall selected

### Overlap counts

- `fvg_fma_overlap`
- `manual_technical_overlap`
- `scout_technical_overlap`

### Health checks

- `universe_nonzero`
- `tier_diversity_ok`
- `technical_recall_present`
- `manual_xfeed_present`

## Persistence

The report should be generated and written during `discover()` alongside:

- `scout_audit.json`
- `fvg_recall.json`
- `fma_recall.json`
- `discovery_delta.json`

This keeps the actual execution order unchanged while making the stage visible.

## CLI Behavior

### `--status`

Compact operator summary:

- date
- readiness/health label
- universe size
- tier counts
- key source counts
- flagged problems if any

### `--format json`

Return the full report from disk.

### Missing artifact

If `universe_filter.json` is missing for the date:

- fail clearly
- tell the operator to run `discover` first

## Testing

Add focused tests for:

- report builder correctness
- `discover()` persistence of `universe_filter.json`
- CLI `--status` output
- CLI JSON loading behavior

## Non-Goals

- no runtime refactor to split the first filter out of `discover()`
- no new gating behavior in workflow-run
- no change to universe composition logic

## Success Criteria

- operators can inspect the first universe filter explicitly every run
- the stage is debuggable before collectors begin
- daily runbooks can point to a first-class first-filter artifact and CLI
