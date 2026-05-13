# Fundamental Framework

Canonical home for the Aeternus fundamental research framework.

Point an LLM reviewer at this folder first. It contains the production code, CLI implementation, operating contracts, output contract, and test map for the framework.

## Read first

1. `FRAMEWORK_INDEX.md` — map of critical code, commands, docs, tests, and artifacts.
2. `ARCHITECTURE.md` — subsystem boundaries and dependency direction.
3. `ARTIFACTS.md` — stable output filenames, run-folder layout, and retention rules.
4. `docs/scoring_input_contract.md` — non-negotiable data requirements before scoring/LLM/final publish.
5. `docs/daily_run_gate_sequence.md` — official daily run gate sequence.
6. `docs/daily_universe_llm_funnel_contract.md` — broad-universe + tier-filtered LLM funnel.

## Runtime entrypoints

Root CLI remains `python -m cli.main ...` for operator convenience. The fundamental command implementation lives here:

- `src/cli/commands.py`

Root adapter:

- `/cli/commands/fundamental.py` — thin compatibility wrapper only.

Primary commands:

- `python -m cli.main fundamental-run-today --mode broad-master-final ...`
- `python -m cli.main fundamental-top15 --scores-csv ...`
- `python -m cli.main fundamental-top15-refill-shadow --scores-csv ...`

## Canonical output root

New fundamental CLI defaults write generated run artifacts under:

`tradingagents/research/fundamental/runs/<date>/<quarter>/<workflow>/`

`runs/` is git-ignored except `.gitkeep`. Generated outputs are operational artifacts, not source files.

## Production code layout

- `src/daily_run/` — gated daily orchestration.
- `src/sec_pipeline/` — SEC coverage/fetch/materialization.
- `src/features/` — pre/post LLM features and scoring packets.
- `src/selection/` — Top 10 + Plus 5 + shadow refill selection.
- `src/pipeline/` — quarter/dealflow pipeline adapters.
- `src/ingest/` — CIK, filings, prices, XBRL ingestion.
- `src/config/` — cache and canonical path config.
- `backtests/` — PIT/backtest generators with framework-local default output roots.
- `scripts/` — fundamental analysis/report generators; root `/scripts/` files are wrappers only.
- `Growth/` — research/backtest legacy workspace; not the daily-run source of truth.
