## Interactive Manual Workflow Design

Date: 2026-03-12

### Goal

Add a human-operated `workflow-run --interactive` mode that guides the operator through:

1. Manual X-feed completion
2. Manual macro prompt completion
3. Manual earnings/options prompt completion
4. Scout execution
5. Collector execution
6. Analyze / portfolio / execution / sync / learning

The operator should no longer need to manually stitch together commands or repeatedly ask for progress.

### Non-goals

- Do not change the existing non-interactive `workflow-run` behavior.
- Do not make automation paths block on stdin.
- Do not add verbose debug logging by default.

### UX Contract

- Interactive mode is explicit: `workflow-run --interactive --mode manual`
- All manual inputs are mandatory in interactive mode.
- Prompt/response flow uses a multiline paste terminator: `END`
- After each pasted JSON payload:
  - validate
  - ingest
  - print a short confirmation
  - automatically move to the next step
- Before automated stages:
  - print a short stage banner
  - print a concise list of scouts/collectors about to run
- After each automated stage:
  - print short counts/status only

### Architectural Choice

Keep the existing `workflow-run` implementation as the default machine-friendly path.

Add an interactive branch that:

- directly orchestrates manual prompt/ingest loops
- directly runs `DealFlowPipeline.discover()` and `DealFlowPipeline.collect()`
- reuses existing analyze/portfolio/execute/sync/learning steps for the back half

This keeps the operator UX clean without making the default CLI brittle.

### Required Manual Stages

1. X-feed
   - Check readiness
   - For each missing pass:
     - print pass prompt
     - wait for JSON paste
     - ingest
     - confirm ticker/merge counts
   - confirm readiness at the end

2. Macro
   - If cache missing:
     - print macro prompt
     - wait for JSON paste
     - validate + save macro cache
     - confirm saved dimensions/sectors

3. Earnings/options
   - If scout artifact missing:
     - print prompt
     - wait for JSON paste
     - validate + save artifact
     - confirm setup count

### Automated Stage Updates

Discover:
- print scout list before running
- print counts after running:
  - breakout
  - technical ignition
  - earnings/options scout
  - insider sweep
  - FVG / FMA recall
  - universe size

Collect:
- print collector list before running
- print shortlist/research queue/deep-selection counts after running

Analyze:
- print queue size and selected count
- keep existing subcommand execution path

Portfolio / execution / sync / learning:
- keep existing step semantics
- add short console summaries in interactive mode

### Failure Policy

- Interactive mode remains fail-open only for learning degradation.
- Validation failures on manual inputs re-prompt immediately.
- Hard pipeline failures still exit non-zero and persist the workflow artifact.

### Test Focus

- `workflow-run --interactive --mode manual` blocks for missing manual inputs and ingests them
- stage output contains prompt and progress summaries
- non-interactive path remains unchanged
