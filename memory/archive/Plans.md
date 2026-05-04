# Aeternus Plans (Milestones + Validation)

## Planning Rules

1. Each milestone must produce user-visible capability.
2. Each milestone must have explicit validation commands.
3. No milestone is complete without tests and audit coverage.

## Milestone Roadmap

## M1 - Deal Flow Team v1 (Implemented)
- Goal: deterministic Top-20 queue generation from multi-family signals.
- Outputs:
  - `aeternus source`
  - `aeternus queue`
  - `aeternus analyze --from-queue-id`
  - `eval_results/deal_flow/<date>/*.json` artifacts
- Validation:
  - `./.venv/bin/python -m pytest tests/test_cli_dealflow.py -q`
  - `./.venv/bin/python -m cli.main source --date <YYYY-MM-DD> --trigger daily --top-k 20 --format table`
  - `./.venv/bin/python -m cli.main queue --date <YYYY-MM-DD> --format table`

## M2 - Smart Money Connectors (Implemented)
- Goal: replace placeholder smart-money signals with live 13F + Congress families.
- Outputs:
  - SEC 13F ingestion adapter
  - Senate/House disclosure ingestion adapter
  - normalized smart-money signals integrated into scoring pipeline
- Validation:
  - unit tests for parsing/normalization
  - integration tests proving non-fatal fallback and schema completeness
  - replay test on historical day producing non-placeholder smart-money evidence

## M3 - Social Data Hardening (In Progress)
- Goal: upgrade social/news from proxy fallback to robust direct connectors.
- Outputs:
  - Direct X connector
  - Reddit connector hardening
  - influencer-quality weighting
- Validation:
  - rate-limit behavior tests
  - connector health metrics
  - deterministic scoring under partial source availability

## M4 - Batch Deep Research Orchestration (Implemented)
- Goal: process `selected_for_deep=true` queue items in one command.
- Outputs:
  - queue batch execution command
  - per-item and aggregate run artifacts
  - failure isolation (one symbol failure does not terminate batch)
- Validation:
  - integration tests for 6-8 symbol batch
  - artifact completeness checks

## M5 - Portfolio Construction + Execution Wiring (In Progress)
- Goal: convert research outputs into portfolio/execution decisions with audit trace.
- Outputs:
  - position sizing policy
  - execution request object and paper/live execution adapters
  - lifecycle linkage to track record
- Validation:
  - end-to-end simulation from source -> research -> order intent
  - audit event completeness per position lifecycle

## M6 - Hedging Operationalization
- Goal: run adaptive hedge engine in scheduled loop with state continuity.
- Outputs:
  - scheduler integration
  - emergency override behavior
  - hedge attribution in portfolio reporting
- Validation:
  - deterministic boundary tests
  - scheduled run smoke tests
  - no-op behavior under data insufficiency

## M7 - Performance Attribution Loop
- Goal: measure which signal families drive realized winners and tune weights safely.
- Outputs:
  - attribution report by signal family and horizon
  - controlled weight tuning procedure with rollback
- Validation:
  - reproducible attribution backtests
  - no-regression checks on existing score behavior

## Current Active Milestone

`M3 - Social Data Hardening` (direct X complete; Reddit hardening pending)

## Exit Criteria For "Investable v1"

1. Daily source/queue runs stable.
2. Smart-money family is live (not placeholder).
3. Deep research batch mode operational.
4. Recommendation-to-order audit chain complete.
5. Hedge engine runs scheduled with state persistence.
