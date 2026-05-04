# Capital Discipline Search and Shadow Overlay Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add capital-discipline-aware constrained search to the fundamental autoresearch harness and expose a read-only shadow fundamental overlay in the live scoring path.

**Architecture:** Keep both changes surgical. The research harness widens only one constrained family, and the live system gains only advisory overlay metadata. The official fundamental pillar score remains unchanged.

**Tech Stack:** Python, pytest

---

### Task 1: Add failing tests for capital-discipline search

**Files:**
- Modify: `tests/test_fundamental_autoresearch_search.py`
- Modify: `tests/test_fundamental_autoresearch_autoresearch.py`

**Step 1: Write the failing tests**

Add tests that require:
- at least one generated strategy with `capital_discipline > 0`
- strategy names include `capital_discipline_<weight>`
- any capital-discipline-bearing strategy keeps `health >= capital_discipline`

**Step 2: Run tests to verify they fail**

Run:
`python3 -m pytest tests/test_fundamental_autoresearch_search.py tests/test_fundamental_autoresearch_autoresearch.py -k 'capital_discipline' -v`

**Step 3: Write minimal implementation**

Update the constrained search generator and strategy naming in:
- `tradingagents/research/fundamental_autoresearch/search.py`

**Step 4: Run tests to verify they pass**

Run the same pytest command and confirm green.

### Task 2: Run the capital-discipline constrained search

**Files:**
- Modify: `tradingagents/research/fundamental_autoresearch/search.py`
- Modify: `tradingagents/research/fundamental_autoresearch/autoresearch.py` only if needed

**Step 1: Run the search and inspect the winner**

Run the existing constrained search / autoresearch CLI on the historical prepared dataset and compare against the standing winner.

**Step 2: Keep only if it beats the canonical winner**

If the new best does not beat `+0.087029`, keep the broader search support but preserve the prior winner as canonical in documentation and memory.

### Task 3: Add failing tests for the shadow overlay

**Files:**
- Modify: `tests/test_session_assembler.py`
- Modify: `tests/test_aeternus_scoring.py`

**Step 1: Write the failing tests**

Add tests that require:
- overlay fields exist when anchored fundamentals exist
- overlay uses the exact formula
- official `fundamental` score is unchanged
- missing/gated fundamentals produce `None` overlay fields safely

**Step 2: Run tests to verify they fail**

Run:
`python3 -m pytest tests/test_session_assembler.py tests/test_aeternus_scoring.py -k 'fundamental_overlay' -v`

**Step 3: Write minimal implementation**

Implement overlay helpers and output wiring in:
- `tradingagents/graph/session_assembler.py`
- `tradingagents/graph/aeternus_scoring.py`

**Step 4: Run tests to verify they pass**

Run the same pytest command and confirm green.

### Task 4: Focused regression

**Files:**
- None beyond prior tasks

**Step 1: Run the focused regression suite**

Run:
`python3 -m pytest tests/test_fundamental_autoresearch_search.py tests/test_fundamental_autoresearch_autoresearch.py tests/test_session_assembler.py tests/test_aeternus_scoring.py -k 'capital_discipline or fundamental_overlay' -v`

**Step 2: Run the broader focused suites touched by each track**

Run:
`python3 -m pytest tests/test_fundamental_autoresearch_search.py tests/test_fundamental_autoresearch_autoresearch.py tests/test_cli_fundamental_research.py tests/test_session_assembler.py tests/test_aeternus_scoring.py -v`

### Task 5: Update memory

**Files:**
- Modify: `memory/WORKING.md`
- Modify: `memory/2026-03-09.md`
- Modify: `memory/MEMORY.md` only if a durable architecture decision changed

**Step 1: Record outcome**

Write:
- whether capital discipline earned promotion
- that the shadow overlay is live and advisory only

