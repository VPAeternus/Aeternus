# Task: H-001

## Tier
haiku

## Summary
Write tests for the cli/commands/ submodules created by S-002.

## Context
After S-002 splits `cli/main.py` into `cli/commands/` submodules, this task adds targeted import and smoke tests for each submodule. Existing CLI tests in `tests/test_cli_*.py` cover end-to-end behavior — this task adds unit-level coverage for the new module structure.

**Depends on:** S-002 must be completed first.

## Requirements
1. Create `tests/test_cli_commands_import.py` that verifies each submodule imports cleanly:
   - `from cli.commands.scoring import *`
   - `from cli.commands.dealflow import *`
   - `from cli.commands.execution import *`
   - `from cli.commands.performance import *`
   - `from cli.commands.portfolio import *`
   - `from cli.commands.operator import *`
2. Verify no circular imports by importing `cli.main` after importing each submodule
3. Verify `app` from `cli.main` has the expected command count (use `len(app.registered_commands)` or equivalent)
4. Use pytest parametrize where appropriate

## Files to Touch
- `tests/test_cli_commands_import.py` (new)

## Acceptance Criteria
- [ ] All import tests pass
- [ ] No circular import detected
- [ ] Command count assertion matches expected total
- [ ] All existing tests still pass: `python -m pytest tests/ -v`

## Status
done
