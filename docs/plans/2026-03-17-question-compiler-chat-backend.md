# Question Compiler Chat Backend Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a manual-only Python backend for chat-style investigation queries that compiles a user question into a structured investigation, diagnoses stage-level misses, and returns frontend-ready findings without automatic external retrieval.

**Architecture:** Add a `Question Compiler v1` on top of the existing scenario sidecar and dealflow artifacts. The implementation should stay Python-first and deterministic: parse the question, load internal artifacts, run stage checkers, detect missing evidence, and return a structured response. LLM usage should be optional and bounded to question parsing or final synthesis only.

**Tech Stack:** Python 3, Typer CLI, existing Aeternus dealflow artifacts, pytest

---

### Task 1: Add Question Compiler contracts

**Files:**
- Create: `tradingagents/dealflow/question_compiler.py`
- Create: `tests/test_question_compiler.py`
- Reference: `tradingagents/dealflow/scenario_contracts.py`

**Step 1: Write the failing tests**

Add tests for:
- reverse forensic question classification
- forward scenario question classification
- ticker extraction from questions like `MU went up 10% today`
- move extraction for `%` moves
- date fallback to provided run date

**Step 2: Run tests to verify they fail**

Run:

```bash
python3 -m pytest tests/test_question_compiler.py -q
```

Expected: FAIL because the module and functions do not exist yet.

**Step 3: Write minimal implementation**

Implement:
- `compile_question(...)`
- rules-first parsing for:
  - `reverse_forensic`
  - `forward_scenario`
- extracted fields:
  - `query_type`
  - `intent`
  - `raw_question`
  - `target_entities`
  - `observation`
  - `required_stages`
  - `required_dimensions`
  - `manual_only`

**Step 4: Run tests to verify they pass**

Run:

```bash
python3 -m pytest tests/test_question_compiler.py -q
```

Expected: PASS

**Step 5: Commit**

```bash
git add tests/test_question_compiler.py tradingagents/dealflow/question_compiler.py
git commit -m "feat: add question compiler contracts"
```

### Task 2: Build stage diagnosis helpers

**Files:**
- Create: `tradingagents/dealflow/investigation_runner.py`
- Create: `tests/test_investigation_runner.py`
- Reference: `tradingagents/dealflow/scenario_retriever.py`
- Reference: `tradingagents/dealflow/why_missed.py`

**Step 1: Write the failing tests**

Add tests for:
- loading internal artifacts for a date
- stage diagnosis when ticker appears in Event Cards but not shortlist
- stage diagnosis when ticker never appears in any discovery-side artifact
- first miss point ordering

**Step 2: Run tests to verify they fail**

Run:

```bash
python3 -m pytest tests/test_investigation_runner.py -q
```

Expected: FAIL because the runner is missing.

**Step 3: Write minimal implementation**

Implement:
- artifact loader helpers
- stage checkers for:
  - scouts
  - event cards
  - universe filter
  - collect/scored set
  - shortlist
  - research queue / deep selection
- first-miss-point selection

**Step 4: Run tests to verify they pass**

Run:

```bash
python3 -m pytest tests/test_investigation_runner.py -q
```

Expected: PASS

**Step 5: Commit**

```bash
git add tests/test_investigation_runner.py tradingagents/dealflow/investigation_runner.py
git commit -m "feat: add investigation runner stage diagnosis"
```

### Task 3: Add gap detection and response shaping

**Files:**
- Create: `tradingagents/dealflow/investigation_response.py`
- Create: `tests/test_investigation_response.py`
- Reference: `tradingagents/dealflow/scenario_retriever.py`

**Step 1: Write the failing tests**

Add tests for:
- `COMPLETE` coverage response
- `PARTIAL` coverage response with missing inputs
- `MISSING` coverage response with manual gap-fill requests
- response payload shape for frontend use

**Step 2: Run tests to verify they fail**

Run:

```bash
python3 -m pytest tests/test_investigation_response.py -q
```

Expected: FAIL because the response builder is missing.

**Step 3: Write minimal implementation**

Implement:
- response builder
- coverage status derivation
- missing evidence mapping
- manual gap-fill recommendations
- structured response fields:
  - `summary`
  - `coverage_status`
  - `stage_diagnosis`
  - `evidence_found`
  - `evidence_missing`
  - `recommended_changes`
  - `manual_gap_fill_requests`
  - `confidence`

**Step 4: Run tests to verify they pass**

Run:

```bash
python3 -m pytest tests/test_investigation_response.py -q
```

Expected: PASS

**Step 5: Commit**

```bash
git add tests/test_investigation_response.py tradingagents/dealflow/investigation_response.py
git commit -m "feat: add investigation response shaping"
```

### Task 4: Expose CLI entrypoint for manual investigation

**Files:**
- Modify: `cli/commands/dealflow.py`
- Create: `tests/test_cli_question_investigate.py`
- Reference: `tradingagents/dealflow/question_compiler.py`
- Reference: `tradingagents/dealflow/investigation_runner.py`

**Step 1: Write the failing tests**

Add CLI tests for a new command such as:
- `question-investigate --date 2026-03-17 --question "MU went up 10% today, why did we miss it?" --format json`

Assert:
- valid JSON result
- no external retrieval side effects
- missing-input behavior when evidence is incomplete

**Step 2: Run tests to verify they fail**

Run:

```bash
python3 -m pytest tests/test_cli_question_investigate.py -q
```

Expected: FAIL because the command does not exist.

**Step 3: Write minimal implementation**

Add a manual-only CLI command that:
- compiles the question
- runs the investigation
- prints JSON or a compact table summary

**Step 4: Run tests to verify they pass**

Run:

```bash
python3 -m pytest tests/test_cli_question_investigate.py -q
```

Expected: PASS

**Step 5: Commit**

```bash
git add tests/test_cli_question_investigate.py cli/commands/dealflow.py
git commit -m "feat: add manual question investigation command"
```

### Task 5: Add regression tests against current artifacts

**Files:**
- Modify: `tests/test_question_compiler.py`
- Modify: `tests/test_investigation_runner.py`
- Modify: `tests/test_cli_question_investigate.py`

**Step 1: Write regression tests**

Add tests for:
- reverse forensic diagnosis against fixture-like dealflow directories
- forward scenario question using Event Cards only
- `wait_for_user` behavior when evidence is incomplete
- stable stage ordering and first-miss logic

**Step 2: Run the focused test suite**

Run:

```bash
python3 -m pytest tests/test_question_compiler.py tests/test_investigation_runner.py tests/test_investigation_response.py tests/test_cli_question_investigate.py -q
```

Expected: PASS

**Step 3: Tighten minimal implementation if needed**

Only add code required to satisfy the new regression cases. Avoid speculative abstractions.

**Step 4: Re-run the focused test suite**

Run:

```bash
python3 -m pytest tests/test_question_compiler.py tests/test_investigation_runner.py tests/test_investigation_response.py tests/test_cli_question_investigate.py -q
```

Expected: PASS

**Step 5: Commit**

```bash
git add tests/test_question_compiler.py tests/test_investigation_runner.py tests/test_investigation_response.py tests/test_cli_question_investigate.py
git commit -m "test: harden question investigation regressions"
```

### Task 6: Document operator usage and frontend contract

**Files:**
- Create: `docs/plans/2026-03-17-question-compiler-chat-backend-frontend-contract.md`
- Modify: `memory/WORKING.md`
- Modify: `memory/MEMORY.md`
- Modify: `memory/2026-03-17.md`

**Step 1: Write the frontend/backend contract note**

Document:
- request payload
- response payload
- progress phases the frontend should render
- manual gap-fill stop behavior

**Step 2: Update project memory**

Record:
- approved architecture decision
- Python-first, no required Zep integration
- LLM-budget policy

**Step 3: Sanity-check doc presence**

Run:

```bash
ls docs/plans/2026-03-17-question-compiler-chat-backend-frontend-contract.md memory/2026-03-17.md
```

Expected: both files exist

**Step 4: Commit**

```bash
git add docs/plans/2026-03-17-question-compiler-chat-backend-frontend-contract.md memory/WORKING.md memory/MEMORY.md memory/2026-03-17.md
git commit -m "docs: record question compiler frontend contract"
```

### Task 7: Final verification

**Files:**
- Verify all files touched above

**Step 1: Run focused test suite**

Run:

```bash
python3 -m pytest tests/test_question_compiler.py tests/test_investigation_runner.py tests/test_investigation_response.py tests/test_cli_question_investigate.py -q
```

Expected: PASS

**Step 2: Run one smoke CLI command**

Run:

```bash
python3 -m cli.main question-investigate --date 2026-03-11 --question "What are today's most important scenarios?" --format json
```

Expected: valid JSON payload with `coverage_status`

**Step 3: Commit final polish**

```bash
git add tradingagents/dealflow/question_compiler.py tradingagents/dealflow/investigation_runner.py tradingagents/dealflow/investigation_response.py cli/commands/dealflow.py tests/test_question_compiler.py tests/test_investigation_runner.py tests/test_investigation_response.py tests/test_cli_question_investigate.py
git commit -m "feat: add question compiler chat backend v1"
```
