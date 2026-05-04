# Task: S-002

## Tier
sonnet

## Summary
Split the 9,056-line `cli/main.py` into submodule command groups.

## Context
`cli/main.py` is a monolithic 9,056-line file with all CLI commands. It already imports from `cli.models` and `cli.utils`. The natural groupings based on the existing commands are:

- **Scoring & Analysis** — `score` (L8532), `analyze` (L8660), `analyze_batch`
- **Deal Flow** — `source` (L4128), `orchestrate` (L4255), `queue` (L4398)
- **Execution** — `execute_paper`, `execute_live`, `reconcile`, `workflow_run` (L4423)
- **Performance** — `track_record` (L3836), `performance` (L3879), `rating_history` (L3926)
- **Portfolio** — `portfolio_plan`, `capital_status`, `allocation_history`
- **Operator** — operator gateway commands
- **Config/Utility** — config, status, version, etc.

Typer supports `app.add_typer(sub_app, name="group")` for subcommand groups, but to preserve existing CLI interface (flat commands, no subgroups), use the pattern of defining commands in submodules and importing/registering them in main.py.

## Requirements
1. Create submodules under `cli/commands/`:
   - `cli/commands/__init__.py`
   - `cli/commands/scoring.py` — score, analyze, analyze_batch
   - `cli/commands/dealflow.py` — source, orchestrate, queue
   - `cli/commands/execution.py` — execute_paper, execute_live, reconcile, workflow_run
   - `cli/commands/performance.py` — track_record, performance, rating_history
   - `cli/commands/portfolio.py` — portfolio_plan, capital_status, allocation_history
   - `cli/commands/operator.py` — operator gateway commands
2. Move each command function and its helpers into the appropriate submodule
3. In `cli/main.py`, import and register commands from submodules. Keep main.py under 100 lines.
4. Preserve the exact same CLI interface — all command names, options, and help text must be identical
5. Shared helpers/constants used across groups stay in `cli/utils.py` or a new `cli/common.py`

## Files to Touch
- `cli/main.py` (rewrite to thin orchestrator)
- `cli/commands/__init__.py` (new)
- `cli/commands/scoring.py` (new)
- `cli/commands/dealflow.py` (new)
- `cli/commands/execution.py` (new)
- `cli/commands/performance.py` (new)
- `cli/commands/portfolio.py` (new)
- `cli/commands/operator.py` (new)
- `cli/utils.py` (may need to extract shared helpers)

## Acceptance Criteria
- [ ] `cli/main.py` is under 100 lines
- [ ] All CLI commands work identically: `aeternus --help` shows same commands
- [ ] `aeternus score AAPL --format json` works
- [ ] `aeternus source --help` works
- [ ] All existing tests pass: `python -m pytest tests/ -v`
- [ ] No circular imports

## Status
done
