# Fundamental Architecture

## Design standard

The fundamental framework is a domain-owned subsystem. Code, command implementation, contracts, and output policy live under `tradingagents/research/fundamental/`.

Root-level modules may expose adapters for repo-wide compatibility, but they must not own fundamental business logic.

## Dependency direction

Allowed direction:

1. `src/cli/commands.py` parses operator inputs and calls framework services.
2. `src/daily_run/` orchestrates gates and artifact writes.
3. `src/sec_pipeline/`, `src/ingest/`, `src/features/`, and `src/selection/` provide deterministic domain services.
4. `src/config/paths.py` owns canonical filesystem defaults.

Forbidden direction:

- domain modules depending on root CLI command modules;
- selection/scoring code reading arbitrary run folders by convention;
- generated output files becoming source-of-truth code;
- duplicate docs/contracts in multiple places.

## Boundary map

| Area | Owns | Does not own |
|---|---|---|
| `src/cli/` | Fundamental CLI command implementation | Repo-wide CLI app creation |
| `src/daily_run/` | Daily gate sequence, stop gates, publish orchestration | SEC parsing internals, LLM provider internals |
| `src/sec_pipeline/` | SEC cache coverage, queue discovery, fetch materialization | Final ranking |
| `src/features/` | Pre-LLM scoring, LLM packets, post-LLM scoring | CLI parsing |
| `src/selection/` | Top 10 + Plus 5 + shadow refill | Universe construction |
| `docs/` | Framework contracts and runbooks | Generated run artifacts |
| `backtests/` | Backtest generators | Generated backtest output storage |
| `scripts/` | Fundamental analysis/report scripts | Root-level script ownership |
| `runs/` | Generated run outputs | Versioned source files |
| `Growth/` | Legacy/research experiments | Official daily final source of truth |

## Compatibility adapters

- `/cli/commands/fundamental.py` imports from `tradingagents.research.fundamental.src.cli.commands` so existing `python -m cli.main ...` commands keep working.
- `/scripts/analyze_fundamental_*.py` files are compatibility wrappers; canonical implementations live in `scripts/` under this framework.
- Existing root tests remain valid, but new fundamental tests should be co-located or indexed from `tests/README.md`.

## Cleanliness rules

- No ad hoc final filenames. Official final artifacts use stable names inside a date/quarter run folder.
- Diagnostics are not final outputs. Put them under `diagnostics/` or name them explicitly as diagnostics.
- Do not create temporary files in source folders.
- Do not copy docs/contracts to avoid drift. Move ownership or link from an index.
- Generated run data must stay ignored unless intentionally promoted as a fixture.
