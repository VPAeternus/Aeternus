# Codex Execution Brief — Workspace Reorganization

## Your Mission

Execute the pre-live workspace reorganization defined in `tasks/REORGANIZATION_PLAN.md`. Read that file in full before starting. This brief adds execution context you need that the plan does not contain.

Work on branch `feature/opus46`. Do not create a new branch.

---

## Critical State Facts — Read Before Touching Anything

### 1. CLI is already split in this branch

`cli/main.py` is **35 LOC** — a thin entrypoint. `cli/commands/` already contains 10 files:
`auth.py`, `dealflow.py`, `execution.py`, `operator.py`, `performance.py`, `portfolio.py`, `scheduler.py`, `scoring.py`, `technical.py`, `__init__.py`

**Do not re-split the CLI.** Your only CLI task (R-001) is to read `cli/main.py` and verify all commands are covered by `cli/commands/`. If everything is covered, R-001 is done — no file changes needed.

### 2. Pre-existing test failures — do not treat as regressions

These tests currently fail and were failing before your work. Do not attempt to fix them:
- `tests/test_cli_dealflow.py` (~48 failures)
- `tests/test_cli_hedging.py` (3 failures)
- `tests/test_cli_score.py` (2 failures)
- `tests/test_paper_execution.py` (1 failure)
- `tests/test_operator_gateway_endpoints.py` (2 failures)

Baseline: 66 failing, 886+ passing. Your work must not increase the failure count.

### 3. No conftest.py exists

Tests use pytest's default flat discovery. When you move test files to subdirectories, pytest will find them automatically — no configuration changes needed, unless `pytest.ini` or `pyproject.toml` has explicit `testpaths` that need updating.

### 4. Do not touch these files/dirs

- `.env` (gitignored, contains live credentials)
- `eval_results/` (gitignored, runtime artifacts)
- `results/` (gitignored)
- `tradingagents/dataflows/data_cache/` (gitignored)
- `.claude/` (agent config)
- Any `__pycache__/` or `*.pyc` files

### 5. Shim policy

No compatibility shims that survive beyond the PR. The only exception: `tradingagents/graph/paper_execution.py` may remain as a re-export shim while you split it, but you must update all test monkeypatches to point to the new sub-modules and then make `paper_execution.py` a clean thin re-export (not a giant shim) before committing.

---

## Execution Order

Run tasks in this order. R-002 and R-003/R-004 are independent — if you have parallel capacity, run them simultaneously.

```
R-005  Haptic duplicate dedup     ~30 min    Do first, simplest
R-001  CLI audit                  ~30 min    Read-only verify; likely no changes
R-003  Phase 1 structural         ~2-3h      Biggest batch of file moves
R-004  OpenBB relocation          ~1h        After R-003 (plan_guard paths change in R-003)
R-002  paper_execution.py split   ~3-4h      Most complex; can run in parallel with R-003/R-004
```

---

## Task R-005: Haptic Engine Deduplication

Status: N/A in current tree — both documented HapticEngine paths are absent and `operator_ui/` has no haptic imports.
Do not recreate haptics here; revisit only if product needs haptic behavior restored.

Files: `operator_ui/src/components/shared/HapticEngine.ts` and `operator_ui/src/lib/HapticEngine.ts`

These were documented as byte-identical. Do this only if both files reappear:
1. Search the entire `operator_ui/` tree for imports of `components/shared/HapticEngine`.
2. Update any found imports to `lib/HapticEngine` (or `@/lib/HapticEngine` if the codebase uses path aliases).
3. Delete `operator_ui/src/components/shared/HapticEngine.ts`.
4. Verify: `cd operator_ui && npx tsc --noEmit 2>&1 | head -30` — no new type errors.

Commit: `chore: remove duplicate HapticEngine (keep lib canonical)`

---

## Task R-001: CLI Split Audit

Status: Passed current-tree audit — `cli/main.py` is thin import/registration only; no command implementation remains there.
Verification used `/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m cli.main --help`; command list loaded with no import errors.

1. Read `cli/main.py` (35 LOC).
2. Read each file in `cli/commands/`.
3. Confirm: every `@app.command()` registration in `cli/main.py` maps to an implementation in `cli/commands/`.
4. If all commands are covered: no file changes. Write a 2-line comment in this brief confirming audit passed.
5. If any command logic is still in `cli/main.py`: move it to the correct `cli/commands/` file in the same commit.

Verification: `python -m cli.main --help` — all commands listed, no import errors.

---

## Task R-003: Phase 1 Structural Cleanup

This is a batch of file moves with no business-logic changes. All moves are documented in `tasks/REORGANIZATION_PLAN.md` Section "Task R-003". Execute each sub-task:

### 3a. Root manual scripts
Move to `scripts/manual_validation/`:
- `manual_verify_cli.py`
- `test.py` → rename to `manual_dataflow_probe.py`
- `test_audit.py` → rename to `manual_audit_probe.py`
- `test_sector.py` → rename to `manual_sector_probe.py`

No wrappers. These have no automated callers.

### 3b. `scripts/` domain subfolders
Create these subdirectories and move files as listed in the plan. Then **mandatory** — update all callers in the same commit:

**`package.json`**: update every script path under the `"scripts"` key that references a moved file.

**`.github/workflows/primus-release-gate.yml`**: update `scripts/smoke_operator_gateway.py` → `scripts/gateway/smoke_operator_gateway.py`.

**`tradingagents/default_config.py`**: find the key `dealflow_house_feed_script_path` and update its default value to `scripts/dealflow/build_house_ptr_feed.py`.

**`tradingagents/dealflow/house_feed.py`**: find the fallback script path string and update to `scripts/dealflow/build_house_ptr_feed.py`.

**`scripts/dev/aeternus_plan_guard.py`**: update all path classification rules that reference old `scripts/*.py` paths to use the new `scripts/<domain>/` paths.

**`tests/test_aeternus_plan_guard.py`**: update path assertions to match new locations.

**`tests/test_primus_preopen_scheduler.py`**: update module import path if it imports `scripts.primus_preopen_scheduler` (new path: `scripts.control.primus_preopen_scheduler`).

**Any docs** under `docs/` referencing explicit `scripts/...` command paths: update with `sed` or targeted edits.

### 3c. `tests/` domain subfolders
Create subdirectories and move test files as listed in the plan. No import changes needed — test files only import production code. Check `pytest.ini` and `pyproject.toml` for explicit `testpaths` — if found, add the new subdirectories.

Verification after R-003:
```bash
python -m pytest tests/ -q 2>&1 | tail -5      # baseline: 66 fail, 886+ pass — no change
python -m cli.main --help                       # all commands present
python -m cli.main score AAPL --format table    # end-to-end smoke (requires API key)
# Path audit — should return no results:
grep -rn "scripts/smoke_operator_gateway\|scripts/build_house_ptr_feed\|scripts/primus_preopen_scheduler" \
  package.json .github tradingagents cli tests 2>/dev/null | grep -v ".pyc"
```

Commit: `chore(reorg): restructure scripts/ and tests/ into domain subdirectories`

---

## Task R-004: OpenBB Relocation

Move `internal/odp/openbb/` → `vendor/openbb/`.

**Step 1 — check for nested `.git`:**
```bash
ls internal/odp/openbb/.git 2>/dev/null && echo "IS SUBMODULE" || echo "plain directory"
```

**If plain directory:**
```bash
mkdir -p vendor
git mv internal/odp/openbb vendor/openbb
# Remove internal/ if now empty
rmdir internal/odp 2>/dev/null; rmdir internal 2>/dev/null
```

**If git submodule:**
```bash
git submodule deinit internal/odp/openbb
git rm internal/odp/openbb
git submodule add <original-remote-url> vendor/openbb
```
Get the original remote URL from `.gitmodules` before removing.

**Step 2 — update path classifiers** in `scripts/dev/aeternus_plan_guard.py`:
Search for any string containing `internal/odp/openbb` and replace with `vendor/openbb`.

**Step 3 — update tests** in `tests/test_aeternus_plan_guard.py`:
Same replacement.

**Step 4 — add to `.gitignore` if not present:**
Add `vendor/` to `.gitignore` if it isn't there, or add a comment explaining it's vendored deps.

Verification:
```bash
python -m pytest tests/test_aeternus_plan_guard.py -q
ls vendor/openbb | head -5   # confirm files present
```

Commit: `chore: relocate openbb subtree from internal/odp to vendor/`

---

## Task R-002: `paper_execution.py` Decomposition

**Read the full file before writing a single line.** `tradingagents/graph/paper_execution.py` is 2915 LOC. Understand all function signatures and their callers before splitting.

### Step 1 — Caller audit (read-only)
Run these to map all callers before touching anything:
```bash
grep -rn "from tradingagents.graph.paper_execution import\|from tradingagents.graph import paper_execution\|tradingagents\.graph\.paper_execution\." \
  cli/ tradingagents/ tests/ scripts/ 2>/dev/null | grep -v ".pyc"
```

### Step 2 — Function grouping
Assign every function/class in `paper_execution.py` to one of these modules:

| New module | What goes here |
|---|---|
| `execution_plan.py` | Order planning: `build_execution_plan`, intent generators, position sizing logic |
| `execution_adapters.py` | Broker dispatch: paper vs Alpaca routing, `execute_paper_orders`, `execute_alpaca_orders` |
| `execution_readiness.py` | Pre-trade gates: `check_execution_readiness`, `position_parity_check`, blocker detection |
| `execution_reconcile.py` | Post-trade: `reconcile_execution`, `pull_broker_orders`, `pull_broker_positions`, sync logic |
| `execution_positions.py` | Exit management: `manage_exits`, `evaluate_exit_signals`, `refresh_open_orders`, THESIS_INVALIDATED, CONVICTION_DECAY logic |

Group by cohesion, not by line order. Functions that call each other frequently belong in the same module.

### Step 3 — Create the new modules
Write each new file. Import from sibling modules within `tradingagents/graph/` as needed. Avoid circular imports — if A and B would import each other, move the shared type/constant to `execution_plan.py` (lowest in the dependency chain).

### Step 4 — Update `paper_execution.py` to a thin re-export
Replace the body of `paper_execution.py` with re-exports of everything that was there. This keeps existing callers working while tests are updated:
```python
# paper_execution.py — compatibility re-exports
# TODO: update callers to import from sub-modules directly
from tradingagents.graph.execution_plan import *      # noqa: F401, F403
from tradingagents.graph.execution_adapters import *  # noqa: F401, F403
from tradingagents.graph.execution_readiness import * # noqa: F401, F403
from tradingagents.graph.execution_reconcile import * # noqa: F401, F403
from tradingagents.graph.execution_positions import * # noqa: F401, F403
```

### Step 5 — Update callers (same PR)
For each caller identified in Step 1: update its import to use the specific sub-module directly, not the wildcard re-export. Prioritize:
- `cli/commands/execution.py`
- `cli/commands/dealflow.py`
- `cli/commands/portfolio.py`
- `tradingagents/broker_adapters/alpaca_readonly.py`

### Step 6 — Update test monkeypatches (same PR)
`tests/test_paper_execution.py` monkeypatches symbols at `tradingagents.graph.paper_execution.*`. For each patched symbol, update the patch path to point to the sub-module where the symbol now lives.

Example:
```python
# Before:
monkeypatch.setattr("tradingagents.graph.paper_execution.fetch_alpaca_positions", ...)
# After (if fetch_alpaca_positions moved to execution_reconcile):
monkeypatch.setattr("tradingagents.graph.execution_reconcile.fetch_alpaca_positions", ...)
```

### Step 7 — Clean up `paper_execution.py`
Once all callers and tests are updated to use sub-modules directly, replace `paper_execution.py` with a minimal shim that only imports and re-exports what is still needed by any remaining callers. Ideally it becomes ~10 LOC.

### Verification
```bash
python -m pytest tests/test_paper_execution.py -q   # no new failures
python -m pytest tests/ -q 2>&1 | tail -5           # baseline unchanged
python -m cli.main --help                            # smoke
```

Commit: `refactor(execution): decompose paper_execution.py into 5 focused modules`

---

## Final Verification (Run After All Tasks Complete)

```bash
# Full test suite
python -m pytest tests/ -q 2>&1 | tail -5
# Should show: 66 failed, 886+ passed (same as baseline)

# CLI smoke
python -m cli.main --help
python -m cli.main score AAPL --format table

# No stale script paths
grep -rn "scripts/smoke_operator_gateway\|scripts/build_house_ptr_feed" \
  package.json .github tradingagents cli tests | grep -v ".pyc"

# No stale paper_execution monkeypatches pointing to old symbols
grep -rn "tradingagents\.graph\.paper_execution\." tests/ | grep -v ".pyc"
# Should be empty or only re-export references

# Frontend
cd operator_ui && npx tsc --noEmit 2>&1 | head -20
```

---

## What Is Explicitly Out of Scope

Do not touch these — they are deferred post-launch:
- `tradingagents/operator_gateway/service.py`
- `tradingagents/default_config.py` domain split
- `tradingagents/dealflow/pipeline.py`
- Frontend API module splits (`apps/primus-web/`, `operator_ui/src/api/`)
- Phase 3 top-level normalization (backend/, runtime_artifacts/, operator_ui rename)
- Any files not mentioned in this brief or the plan

If you encounter something that seems broken and unrelated to your tasks: note it, do not fix it.
