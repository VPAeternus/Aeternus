# Fundamental Framework Index

Use this as the first file for LLM/code review.

## What this framework does

1. Builds the main fundamental universe.
2. Refreshes SEC evidence and Companyfacts.
3. Scores broad-universe base fundamentals.
4. Applies Tier 0-4, HP, and RM buckets.
5. Runs LLM extraction only on Tier 1-4 names with fresh earnings evidence.
6. Merges prior-quarter comparison data for QoQ-aware scoring.
7. Publishes Top 10 core + Plus 5 exception + shadow refill review outputs.

## Critical commands

| Command | Purpose | Implementation |
|---|---|---|
| `fundamental-run-today` | Official gated daily workflow | `src/cli/commands.py` |
| `fundamental` | Legacy scout-smoke/quarter workflow | `src/cli/commands.py` |
| `fundamental-top10` | Legacy Top 10 selector | `src/cli/commands.py`, `src/selection/high_conviction_top10.py` |
| `fundamental-top15` | Top 10 + Plus 5 selector | `src/cli/commands.py`, `src/selection/high_conviction_top10.py` |
| `fundamental-top15-refill-shadow` | Shadow refill variant | `src/cli/commands.py`, `src/selection/high_conviction_top10.py` |

Root compatibility wrapper: `/cli/commands/fundamental.py`.

## Critical production modules

| Path | Role |
|---|---|
| `src/daily_run/orchestrator.py` | 10-gate daily workflow |
| `src/daily_run/models.py` | run config, gates, state |
| `src/daily_run/universe.py` | main list + scout append gate |
| `src/daily_run/coverage.py` | SEC coverage loading/raw-doc assembly |
| `src/daily_run/scoring_inputs.py` | tradable date, entry price, score-ready quarantine |
| `src/daily_run/eligibility.py` | Tier assignment + LLM readiness |
| `src/daily_run/llm_validation.py` | post-LLM result validation |
| `src/daily_run/finalize.py` | final score reconciliation + publish |
| `src/sec_pipeline/cache_coverage_manifest.py` | SEC evidence discovery and fetch queue |
| `src/sec_pipeline/cache_download_queue.py` | SEC queue materialization |
| `src/features/llm_packets.py` | LLM packet construction; default 8-K/press-release only |
| `src/pipeline/run_on_new_filing.py` | signal table/final scoring assembly |
| `src/selection/high_conviction_top10.py` | Top 10 + Plus 5 + shadow refill selection |
| `src/config/paths.py` | canonical framework filesystem paths |
| `backtests/pit_panel.py` | PIT backtest panel exporter |
| `backtests/high_conviction_top10.py` | Top 10 backtest exporter |
| `backtests/high_conviction_top15_exception_sleeve.py` | Top 10 + Plus 5 backtest exporter |
| `scripts/analyze_top10_observed_backtest.py` | Top 10 observed-data analysis report generator |
| `scripts/analyze_top15_exception_sleeve.py` | Top 10 + Plus 5 observed-data analysis report generator |

Compatibility wrappers remain at `/scripts/analyze_fundamental_top10_observed_backtest.py` and `/scripts/analyze_fundamental_top15_exception_sleeve.py`.

## Operating contracts

| Path | Contract |
|---|---|
| `docs/scoring_input_contract.md` | required inputs before scoring/LLM/final publish |
| `docs/daily_run_gate_sequence.md` | official daily gates and stop conditions |
| `docs/daily_universe_llm_funnel_contract.md` | broad universe + tier-filtered LLM funnel |
| `ARTIFACTS.md` | output folders, filenames, retention policy |
| `ARCHITECTURE.md` | subsystem boundaries and dependency direction |

## Test map

See `tests/README.md` for source-of-truth test files. Focused suites:

- root CLI tests: `/tests/test_cli_fundamental_*.py`
- daily-run tests: `/tests/test_fundamental_daily_*.py`
- packet/SEC parser tests: `/tests/test_llm_packets.py`, `/tests/test_sec_coverage_manifest_parser.py`
- selection tests: `/tests/test_fundamental_high_conviction_top10.py`, `/tests/test_high_conviction_top15_exception_sleeve.py`
- package-local tests: `tests/`

## Output map

Forward default:

- `runs/<date>/<quarter>/daily/`
- `runs/<date>/<quarter>/legacy_scout/`
- `runs/<date>/selection/`
- `runs/backtests/`

Legacy archives:

- `/eval_results/fundamental/`
- `/outputs/fundamental_backtest/`

## Non-negotiable rules

- Main list first; daily scouts append, they do not replace the main list.
- LLM does not run on all 1,200+ names.
- Tier 1-4 LLM requires fresh earnings 8-K or press-release evidence.
- 10-Q/10-K alone supports base scoring, not official high-conviction LLM selection.
- Prior-quarter comparison data is required for final Top 10 + Plus 5 + shadow refill; use `--prior-final-scores` for official daily runs.
- Final scores plus explicit quarantines must reconcile to broad universe count before publish.
- Stable final filenames only; run/date/quarter goes in folder path.
