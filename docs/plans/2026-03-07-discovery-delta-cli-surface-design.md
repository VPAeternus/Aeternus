# Discovery Delta CLI Surface Design

## Goal

Expose the new read-only `Discovery Delta` output in the existing operator-facing deal-flow CLI so the ranking is visible immediately after discovery and source generation.

## Recommendation

Add a thin Delta panel to the existing deal-flow surfaces instead of creating a new command.

Why this is the right shape:

- the operator already uses `discover` and `source` to inspect discovery output
- `Discovery Delta` is read-only and adjacent to Step 1, so it belongs near those commands
- a separate command would slow idea-to-product by creating another dead-end surface to remember

## Design

### Rendering

Add a new shared renderer in `cli/common.py`:

- `_render_discovery_delta_summary(summary: Dict[str, Any]) -> None`

The renderer should show:

- top delta symbols
- their `delta_score`
- number of independent channels
- source list
- compact cohort counts:
  - `scout_only`
  - `technical_only`
  - `multi_channel`

The first version should stay compact and table-based.

### Insertion Points

Use the renderer in:

- `dealflow discover`
- `dealflow source`

Those commands already represent the natural operator entry points for discovery and full Step 1 output.

The renderer should be optional:

- only render if `discovery_delta_summary` / `discovery_delta` is present
- otherwise remain silent

### Payload Shape

The pipeline already returns:

- `discover()["discovery_delta_summary"]`

To support richer rendering, `discover()` should also return:

- `discover()["discovery_delta"]`

This keeps the CLI read-only and avoids forcing it to reopen artifacts from disk.

## Guardrails

- no new command in v1
- no mutation of Step 1 behavior
- no artifact schema churn beyond what the pipeline already owns
- keep the renderer compact; do not turn the CLI into a dashboard

## Success Criteria

The feature is successful if:

- `dealflow discover` shows the top Delta names after a run
- `dealflow source` shows the same Delta surface during full shortlist generation
- nothing changes in ranking, universe size, or Step 1 selection semantics
