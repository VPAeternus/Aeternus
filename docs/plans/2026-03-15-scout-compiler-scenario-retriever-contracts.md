# Scout Compiler and Scenario Retriever Contracts Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a shadow-sidecar daily scenario layer that compiles scout outputs into Event Cards and coverage artifacts, plus a manual/on-demand Scenario Retriever that searches internal state and reports gaps without triggering external fetches.

**Architecture:** Keep the existing deal-flow pipeline behavior unchanged. Add a deterministic `Scout Compiler` at the end of `discover()` that writes sidecar artifacts only, then add a manual `Scenario Retriever` that reads those artifacts plus AKG, universe, and cached research state to answer explicit questions with `COMPLETE / PARTIAL / MISSING` coverage statuses.

**Tech Stack:** Python 3, Typer CLI, pytest, JSON artifacts, existing deal-flow pipeline, AKG JSON store

---

### Task 1: Add contract tests for Event Card compilation

**Files:**
- Create: `tests/test_scout_compiler.py`
- Create: `tradingagents/dealflow/scenario_contracts.py`

**Step 1: Write the failing test**

Add tests that validate:
- one merged multi-source event becomes one Event Card
- direct entities and second-order entities are separated
- required Event Card keys are always present
- empty or weak source inputs produce zero cards cleanly

**Step 2: Run test to verify it fails**

Run:
```bash
python3 -m pytest tests/test_scout_compiler.py -k 'event_card_contract' -q
```

Expected:
- fail because the contracts/module do not exist yet

**Step 3: Write minimal implementation**

Create contract helpers/dataclasses or schema validators in:
- `tradingagents/dealflow/scenario_contracts.py`

Include:
- Event Card required fields
- allowed coverage statuses
- helper validation functions

**Step 4: Run test to verify it passes**

Run:
```bash
python3 -m pytest tests/test_scout_compiler.py -k 'event_card_contract' -q
```

**Step 5: Commit**

```bash
git add tests/test_scout_compiler.py tradingagents/dealflow/scenario_contracts.py
git commit -m "test: add scout compiler contract coverage"
```

### Task 2: Implement deterministic Scout Compiler core

**Files:**
- Create: `tradingagents/dealflow/scout_compiler.py`
- Modify: `tradingagents/dealflow/scenario_contracts.py`
- Test: `tests/test_scout_compiler.py`

**Step 1: Write the failing test**

Add tests that:
- compile scout inputs into `event_cards`
- normalize simple entity references
- collapse overlapping narratives into one card
- produce `source_bundle`, `channels`, and `expected_direction`

**Step 2: Run test to verify it fails**

Run:
```bash
python3 -m pytest tests/test_scout_compiler.py -k 'compile_scout_inputs' -q
```

Expected:
- fail because compiler implementation does not exist yet

**Step 3: Write minimal implementation**

Implement:
- `compile_scout_events(...)`
- deterministic event grouping
- simple event-type assignment
- direct vs second-order entity separation

Do not:
- call external services
- mutate AKG
- depend on LLMs

**Step 4: Run test to verify it passes**

Run:
```bash
python3 -m pytest tests/test_scout_compiler.py -k 'compile_scout_inputs' -q
```

**Step 5: Commit**

```bash
git add tradingagents/dealflow/scout_compiler.py tests/test_scout_compiler.py tradingagents/dealflow/scenario_contracts.py
git commit -m "feat: add deterministic scout compiler core"
```

### Task 3: Add Coverage Precheck generation

**Files:**
- Modify: `tradingagents/dealflow/scout_compiler.py`
- Test: `tests/test_scout_compiler.py`

**Step 1: Write the failing test**

Add tests that:
- every Event Card gets a coverage row
- `COMPLETE`, `PARTIAL`, and `MISSING` are assigned deterministically
- missing dimensions are surfaced
- `ready_for_retrieval` is computed

**Step 2: Run test to verify it fails**

Run:
```bash
python3 -m pytest tests/test_scout_compiler.py -k 'coverage_precheck' -q
```

Expected:
- fail because precheck generation is not implemented yet

**Step 3: Write minimal implementation**

Add:
- `build_coverage_precheck(...)`
- deterministic scoring helpers:
  - entity resolution
  - source diversity
  - channel confirmation
  - portfolio relevance
  - freshness

**Step 4: Run test to verify it passes**

Run:
```bash
python3 -m pytest tests/test_scout_compiler.py -k 'coverage_precheck' -q
```

**Step 5: Commit**

```bash
git add tradingagents/dealflow/scout_compiler.py tests/test_scout_compiler.py
git commit -m "feat: add coverage precheck for event cards"
```

### Task 4: Add AKG writeback candidate preview generation

**Files:**
- Modify: `tradingagents/dealflow/scout_compiler.py`
- Test: `tests/test_scout_compiler.py`

**Step 1: Write the failing test**

Add tests that:
- compiler emits non-executing writeback candidates
- candidate types are limited to the approved set
- preview candidates never mutate AKG
- low-confidence speculative candidates are labeled `temporary_only`

**Step 2: Run test to verify it fails**

Run:
```bash
python3 -m pytest tests/test_scout_compiler.py -k 'writeback_candidates' -q
```

Expected:
- fail because preview generation is missing

**Step 3: Write minimal implementation**

Add:
- `build_akg_writeback_candidates(...)`
- candidate labeling:
  - `safe_later`
  - `needs_review`
  - `temporary_only`

Keep output artifact-only.

**Step 4: Run test to verify it passes**

Run:
```bash
python3 -m pytest tests/test_scout_compiler.py -k 'writeback_candidates' -q
```

**Step 5: Commit**

```bash
git add tradingagents/dealflow/scout_compiler.py tests/test_scout_compiler.py
git commit -m "feat: add akg writeback preview candidates"
```

### Task 5: Wire Scout Compiler into `discover()` as a sidecar

**Files:**
- Modify: `tradingagents/dealflow/pipeline.py`
- Test: `tests/test_dealflow_pipeline.py`

**Step 1: Write the failing test**

Add tests that:
- `discover()` writes:
  - `event_cards.json`
  - `coverage_precheck.json`
  - `scout_compiler_debug.json`
  - `akg_writeback_candidates.json`
- the normal discovery summary remains unchanged
- no universe size or candidate_list logic is affected by sidecar compilation

**Step 2: Run test to verify it fails**

Run:
```bash
python3 -m pytest tests/test_dealflow_pipeline.py -k 'scout_compiler_sidecar' -q
```

Expected:
- fail because the sidecar is not wired into `discover()`

**Step 3: Write minimal implementation**

At the end of `discover()`:
- build compiler input packet from existing scout/discovery artifacts
- run Scout Compiler
- persist sidecar artifacts
- attach a small summary to the discovery return payload

Do not:
- change universe build inputs
- change collector inputs
- change AKG state

**Step 4: Run test to verify it passes**

Run:
```bash
python3 -m pytest tests/test_dealflow_pipeline.py -k 'scout_compiler_sidecar' -q
```

**Step 5: Commit**

```bash
git add tradingagents/dealflow/pipeline.py tests/test_dealflow_pipeline.py
git commit -m "feat: wire scout compiler as discover sidecar"
```

### Task 6: Add manual Scenario Retriever module

**Files:**
- Create: `tradingagents/dealflow/scenario_retriever.py`
- Modify: `tradingagents/dealflow/scenario_contracts.py`
- Create: `tests/test_scenario_retriever.py`

**Step 1: Write the failing test**

Add tests that:
- a question can match Event Cards and internal entities
- retriever searches artifacts in the approved order
- retriever returns `COMPLETE`, `PARTIAL`, or `MISSING`
- retriever reports `missing_inputs`
- retriever never triggers external fetches

**Step 2: Run test to verify it fails**

Run:
```bash
python3 -m pytest tests/test_scenario_retriever.py -q
```

Expected:
- fail because the retriever module does not exist yet

**Step 3: Write minimal implementation**

Implement:
- `retrieve_scenario_context(...)`
- question/entity matching against:
  - `event_cards.json`
  - `coverage_precheck.json`
  - AKG
  - universe
  - portfolio/queue/candidate_list
- gap reporting with `wait_for_user = true`

**Step 4: Run test to verify it passes**

Run:
```bash
python3 -m pytest tests/test_scenario_retriever.py -q
```

**Step 5: Commit**

```bash
git add tradingagents/dealflow/scenario_retriever.py tradingagents/dealflow/scenario_contracts.py tests/test_scenario_retriever.py
git commit -m "feat: add manual scenario retriever"
```

### Task 7: Add CLI surface for Scenario Retriever

**Files:**
- Modify: `cli/commands/dealflow.py`
- Possibly modify: `cli/main.py`
- Test: `tests/test_cli_dealflow.py`

**Step 1: Write the failing test**

Add tests for a command like:
- `scenario-retrieve --date 2026-03-15 --question "..." --format json`

Validate that:
- result includes coverage status
- result includes missing inputs when partial/missing
- command does not attempt external fetches

**Step 2: Run test to verify it fails**

Run:
```bash
python3 -m pytest tests/test_cli_dealflow.py -k 'scenario_retrieve' -q
```

Expected:
- fail because CLI command does not exist yet

**Step 3: Write minimal implementation**

Expose a CLI command that:
- loads the retriever
- reads the day’s artifacts
- prints retrieval results

**Step 4: Run test to verify it passes**

Run:
```bash
python3 -m pytest tests/test_cli_dealflow.py -k 'scenario_retrieve' -q
```

**Step 5: Commit**

```bash
git add cli/commands/dealflow.py cli/main.py tests/test_cli_dealflow.py
git commit -m "feat: add scenario retriever cli"
```

### Task 8: Persist compiler summary in discovery output

**Files:**
- Modify: `tradingagents/dealflow/pipeline.py`
- Test: `tests/test_dealflow_pipeline.py`
- Test: `tests/test_cli_dealflow.py`

**Step 1: Write the failing test**

Add tests that:
- `discover()` summary includes small sidecar metadata:
  - event card count
  - complete/partial/missing counts
  - writeback candidate count
- output remains informational only

**Step 2: Run test to verify it fails**

Run:
```bash
python3 -m pytest tests/test_dealflow_pipeline.py tests/test_cli_dealflow.py -k 'scout_compiler_summary' -q
```

Expected:
- fail because summary metadata is not returned yet

**Step 3: Write minimal implementation**

Add sidecar summary fields to `discover()` return payload and CLI rendering.

Do not let any decision stage consume them yet.

**Step 4: Run test to verify it passes**

Run:
```bash
python3 -m pytest tests/test_dealflow_pipeline.py tests/test_cli_dealflow.py -k 'scout_compiler_summary' -q
```

**Step 5: Commit**

```bash
git add tradingagents/dealflow/pipeline.py cli/commands/dealflow.py tests/test_dealflow_pipeline.py tests/test_cli_dealflow.py
git commit -m "feat: expose scout compiler sidecar summary"
```

### Task 9: Add initial scout-quality artifact from existing attribution

**Files:**
- Create: `tradingagents/dealflow/scout_quality.py`
- Modify: `tradingagents/dealflow/learning_loop.py`
- Create: `tests/test_scout_quality.py`

**Step 1: Write the failing test**

Add tests that:
- produce `scout_quality_daily.json`
- join:
  - `scout_audit.json`
  - `discovery_delta.json`
  - `source_attribution.json`
  - `coverage_precheck.json`
- summarize per-scout:
  - detection count
  - event card contribution count
  - complete/partial/missing counts

**Step 2: Run test to verify it fails**

Run:
```bash
python3 -m pytest tests/test_scout_quality.py -q
```

Expected:
- fail because scout-quality artifact does not exist yet

**Step 3: Write minimal implementation**

Create:
- `build_scout_quality_daily(...)`

Persist:
- `eval_results/deal_flow/<date>/scout_quality_daily.json`

Keep the first slice narrow and purely artifact-based.

**Step 4: Run test to verify it passes**

Run:
```bash
python3 -m pytest tests/test_scout_quality.py -q
```

**Step 5: Commit**

```bash
git add tradingagents/dealflow/scout_quality.py tradingagents/dealflow/learning_loop.py tests/test_scout_quality.py
git commit -m "feat: add scout quality daily artifact"
```

### Task 10: Run focused verification and live smoke

**Files:**
- No code changes expected

**Step 1: Run focused test suite**

Run:
```bash
python3 -m pytest \
  tests/test_scout_compiler.py \
  tests/test_scenario_retriever.py \
  tests/test_scout_quality.py \
  tests/test_dealflow_pipeline.py \
  tests/test_cli_dealflow.py \
  -k 'scout_compiler or scenario_retrieve or scout_quality' -q
```

Expected:
- focused contract/sidecar tests pass

**Step 2: Run live discover smoke**

Run:
```bash
python3 -m cli.main discover --date 2026-03-15 --format json
```

Expected:
- existing discover behavior completes
- sidecar artifacts are written

**Step 3: Run manual retriever smoke**

Run:
```bash
python3 -m cli.main scenario-retrieve --date 2026-03-15 --question "What are today's most important daily scenarios?" --format json
```

Expected:
- returns internal-only scenario retrieval output
- never performs external fetches

**Step 4: Commit verification-safe final state**

```bash
git add .
git commit -m "feat: add scout compiler and scenario retriever sidecar"
```
