# Code Reorganization Plan — Go-Live Scope

**Status:** pending
**Scope:** Pre-live structural cleanup only. No cosmetic refactors, no deferred items.
**Principle:** Big-bang internal updates. Shims only where tests hard-patch module paths, within the same PR.

---

## Verified Current State (feature/opus46)

| Item | Actual state |
|---|---|
| `cli/main.py` | 35 LOC — already a thin entrypoint delegating to `cli/commands/` |
| `cli/commands/` | 10 command files: auth, dealflow, execution, operator, performance, portfolio, scheduler, scoring, technical + `__init__` |
| `tradingagents/graph/paper_execution.py` | 2915 LOC — needs decomposition |
| `internal/odp/openbb` | Vendored subtree, dominates file scan noise — needs relocation |
| `operator_ui/src/components/shared/HapticEngine.ts` | Exact duplicate of `operator_ui/src/lib/HapticEngine.ts` |

**Cross-worktree CLI regression:** Other worktrees (Sonnet/Haiku/Codex) deleted `cli/commands/` and reverted `cli/main.py` to 9056 LOC. Before any CLI work in those sessions: rebase from `feature/opus46` or restore `cli/commands/` from HEAD. Do not re-split what already exists.

---

## What We Are Doing (Go-Live Scope)

### Task R-001 — CLI Split Completion Audit (Haiku)
**Files:** `cli/main.py`, `cli/commands/*.py`

Verify the existing split is complete:
1. Read `cli/main.py` and each `cli/commands/*.py` to confirm all 34 registered commands have implementations in `commands/`.
2. Identify any commands still implemented directly in `cli/main.py` (vs just registered there).
3. If gaps found: move remaining command logic to the appropriate `cli/commands/` file and thin `cli/main.py` further.
4. Verify `pyproject.toml` entrypoint (`aeternus = "cli.main:main"`) still works after any changes.
5. Verify test patches: `tests/test_cli_dealflow.py` and `tests/test_cli_hedging.py` import from `cli.main`. If symbols moved, update the patches in the same PR — no compatibility shims.

**Verification:** `python -m cli.main --help` shows all commands. `python -m pytest tests/test_cli_dealflow.py tests/test_cli_hedging.py tests/test_cli_score.py -q` passes (no new failures vs baseline).

---

### Task R-002 — `paper_execution.py` Decomposition (Sonnet)
**Files:** `tradingagents/graph/paper_execution.py` (split into 5 modules)

**Why before go-live:** Execution, readiness, and reconciliation are distinct concerns. Auditing them for correctness is easier in focused files. This is the path real capital flows through.

**Proposed split:**

```
tradingagents/graph/paper_execution.py    → compatibility re-export surface (short-lived)
tradingagents/graph/execution_plan.py     → order planning, intent → order conversion
tradingagents/graph/execution_adapters.py → broker adapter dispatch, paper vs live routing
tradingagents/graph/execution_readiness.py → pre-trade readiness gates, position parity checks
tradingagents/graph/execution_reconcile.py → reconciliation, broker pull, position sync
tradingagents/graph/execution_positions.py → open-order management, exit rule evaluation
```

**Seam identification (read before splitting):**
- Planning functions: `build_execution_plan`, `generate_order_intents`, portfolio-plan helpers
- Adapter functions: `execute_paper_orders`, `execute_alpaca_orders`, mode routing
- Readiness functions: `check_execution_readiness`, `position_parity_check`, blocker detection
- Reconciliation functions: `reconcile_execution`, `pull_broker_orders`, `pull_broker_positions`
- Position/exit functions: `manage_exits`, `evaluate_exit_signals`, `refresh_open_orders`

**Shim policy:** Keep `tradingagents/graph/paper_execution.py` as a re-export shim for the duration of this PR only (tests monkeypatch `tradingagents.graph.paper_execution.*`). Update test patches to the correct sub-module paths within the same PR. Delete shim once patches are updated.

**Callers to update:**
- `cli/commands/execution.py` — imports from `paper_execution`
- `cli/commands/dealflow.py` — imports from `paper_execution`
- `cli/commands/portfolio.py` — imports from `paper_execution`
- `tradingagents/broker_adapters/alpaca_readonly.py`
- `tests/test_paper_execution.py` — update monkeypatch paths

**Verification:** `python -m pytest tests/test_paper_execution.py tests/test_cli_dealflow.py -q`. No new failures. Run `aeternus execute-paper --dry-run` end-to-end.

---

### Task R-003 — Phase 1 Structural Cleanup (Haiku)
**No business-logic changes. Pure file moves.**

#### 3a. Root manual scripts → `scripts/manual_validation/`
- `manual_verify_cli.py` → `scripts/manual_validation/`
- `test.py` → `scripts/manual_validation/manual_dataflow_probe.py`
- `test_audit.py` → `scripts/manual_validation/manual_audit_probe.py`
- `test_sector.py` → `scripts/manual_validation/manual_sector_probe.py`

No wrappers needed — these are manual scripts with no automated callers.

#### 3b. `scripts/` → domain subfolders
Create subfolders and move files (no wrappers needed — scripts have no importers):

```
scripts/gateway/      — run_operator_gateway.py, smoke_operator_gateway.py, export_operator_openapi.py, export_publisher_pack.py, publish_readable_reports.py, run_concierge_scenarios.py, run_signal_accountability.py, run_operator_gateway_lite.py
scripts/control/      — emit_engine_heartbeat.py, primus_preopen_scheduler.py
scripts/allocator/    — seed_allocator_market_snapshot.py, inject_regime_shock.py, run_allocator_alpha_day*.py
scripts/dealflow/     — build_house_ptr_feed.py, deal_source.py, social_dealflow.py
scripts/research/     — analyst_discovery_engine.py, analyst_discovery_report.py, integration_workflow.py, xai_quality_scorer*.py, backtest_*.py, export_accel_signals.py
scripts/reports/      — render_equity_report.py, generate_first_light_sequence.py, run_first_sync_normalization_audit.py
scripts/skills/       — openskills.sh, openskills_sync.py
scripts/dev/          — aeternus_plan_guard.py, primus_up.sh, primus_down.sh, primus_status.sh
scripts/manual_validation/ — (from 3a above)
```

**Mandatory caller updates (must happen in same PR):**
- `package.json` scripts section — update all `scripts/...` path references
- `.github/workflows/primus-release-gate.yml` — update `scripts/smoke_operator_gateway.py` reference
- `tradingagents/default_config.py` key `dealflow_house_feed_script_path` — update to `scripts/dealflow/build_house_ptr_feed.py`
- `tradingagents/dealflow/house_feed.py` fallback path — update
- `scripts/dev/aeternus_plan_guard.py` path classification rules — update all moved paths
- `tests/test_aeternus_plan_guard.py` path assertions — update
- `tests/test_primus_preopen_scheduler.py` module import path — update
- Any docs with explicit `scripts/...` commands

#### 3c. `tests/` → domain subfolders
Create subfolders and move test files. Pytest discovery continues to work (no `conftest.py` — flat discovery already in place via `pytest.ini` or default).

```
tests/cli/            — test_cli_*.py, test_aeternus_*.py
tests/graph/          — test_aeternus_scoring.py, test_paper_execution.py, test_verdict_*.py, test_structured_trader.py, test_exit_enforcement.py, test_portfolio_context.py, test_coherence_engine.py, test_fama_french.py, test_options_engine.py
tests/agents/         — test_fundamental_engine.py, test_macro_engine.py, test_momentum_*.py, test_phase_*.py, test_sentiment_*.py
tests/dealflow/       — test_dealflow_*.py, test_cashtag_*.py, test_x_social*.py, test_social_news*.py
tests/capital_allocator/ — test_capital_allocator_*.py
tests/operator_gateway/ — test_operator_gateway_*.py
tests/dataflows/      — test_dataflows.py, test_alpha_vantage*.py
tests/infrastructure/ — test_sar_audit*.py, test_primus_*.py, test_aeternus_plan_guard.py
tests/scripts/        — tests that run scripts end-to-end
```

**Mandatory caller updates:**
- `.github/workflows/primus-release-gate.yml` — any explicit test file references (e.g., `tests/test_operator_gateway_slo.py`)
- `pytest.ini` or `pyproject.toml` testpaths — add subdirectories if not using default discovery

**No import changes needed** — test files import production code, not each other.

---

### Task R-004 — OpenBB Relocation (Sonnet)
**Files:** `internal/odp/openbb/` → `vendor/openbb/`

**Why:** This subtree dominates file count in any repo scan (including what agents see). Moving it to `vendor/` signals "not product code" to all tools.

**Steps:**
1. Check for nested `.git` in `internal/odp/openbb/` — if present, handle as submodule (`git submodule deinit` + re-add at new path) or plain copy + remove `.git` if not tracked as submodule.
2. `git mv internal/odp/openbb vendor/openbb` (or manual copy + remove if submodule).
3. Update `scripts/dev/aeternus_plan_guard.py` path classifiers — any rules referencing `internal/odp/openbb` → `vendor/openbb`.
4. Update `tests/test_aeternus_plan_guard.py` assertions for new path.
5. Update any docs or scripts that reference `internal/odp/openbb`.
6. Add `vendor/` to `.gitignore` if not already present (or explicitly exclude from linting/scanning).

**Verification:** `python -m pytest tests/test_aeternus_plan_guard.py -q`. Confirm no import errors in any file that referenced the old path.

---

### Task R-005 — Haptic Engine Deduplication (Haiku)
**Files:** `operator_ui/src/components/shared/HapticEngine.ts`, `operator_ui/src/lib/HapticEngine.ts`

Byte-identical. Keep `operator_ui/src/lib/HapticEngine.ts` as canonical.
1. Search repo for all imports of `components/shared/HapticEngine`.
2. Update to `lib/HapticEngine`.
3. Delete `operator_ui/src/components/shared/HapticEngine.ts`.

**Verification:** TypeScript compile clean in `operator_ui/`.

---

## What We Are NOT Doing (Deferred)

These items are explicitly out of scope until post-launch:

| Item | Reason deferred |
|---|---|
| `tradingagents/operator_gateway/service.py` split (95 methods) | Not on trading critical path |
| `tradingagents/default_config.py` domain split | S-030 adds new config keys now; wrong time. Defer until config stabilizes |
| `tradingagents/dealflow/pipeline.py` split | Not on go-live critical path |
| Frontend API module splits (primus-web, operator_ui) | Not on trading critical path |
| Phase 3 top-level normalization (backend/, runtime_artifacts/, operator_ui rename) | Post-launch cosmetics |
| `tradingagents/operator_gateway/service.py` method extraction | Post-launch |

---

## Execution Order

```
R-005  Haptic duplicate          Haiku    30 min   No dependencies
R-001  CLI audit + completion    Haiku    1-2h     Check worktree state first
R-003  Phase 1 structural        Haiku    2-3h     After R-001 (test paths change)
R-004  OpenBB relocation         Sonnet   1h       After R-003 (plan_guard paths)
R-002  paper_execution split     Sonnet   3-4h     Independent; highest value
```

R-002 and R-003/R-004 are independent and can run in parallel sessions.

---

## Shim Policy (Explicit)

| Scenario | Policy |
|---|---|
| Script file moves | No shims. Update callers in same PR. |
| Test file moves | No shims. Pytest discovers new paths automatically. |
| `paper_execution.py` split | One-PR shim only. Update test monkeypatches in same PR. Delete shim before merge. |
| `cli/main.py` (already thin) | No shims needed — it's already a delegating entrypoint. |
| `default_config.py` | Deferred. When done: compatibility facade with one-PR lifespan. |

**No "one release cycle" shims.** Pre-live codebase, no external consumers.

---

## Verification Gates (Required Before Each Merge)

```bash
# Backend
python -m pytest tests/ -q                    # no new failures vs baseline (66 pre-existing)
python -m cli.main --help                     # all commands listed
python -m cli.main score AAPL --format table  # end-to-end smoke test

# Paths
grep -rn "scripts/smoke_operator_gateway\|scripts/build_house_ptr_feed\|tradingagents\.graph\.paper_execution" \
  package.json .github tradingagents cli tests \
  | grep -v "vendor/" | grep -v ".pyc"        # should be empty after callers updated

# Frontend (R-005 only)
cd operator_ui && npx tsc --noEmit 2>&1 | head -20
```
