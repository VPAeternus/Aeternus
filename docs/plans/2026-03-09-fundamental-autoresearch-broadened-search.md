# Fundamental Autoresearch Broadened Search Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a carefully broadened constrained search space that includes a small positive valuation sleeve alongside the current health-led anti-crowding family, then rerun the real experiment and judge it against the current winner.

**Architecture:** Extend the constrained search generator and orchestration layer to support valuation-augmented candidates while keeping the dataset, evaluator, and artifact contracts unchanged.

**Tech Stack:** Python 3, pytest, existing fundamental autoresearch harness

---

### Task 1: Add failing tests for valuation-augmented constrained search

**Files:**
- Modify: `tests/test_fundamental_autoresearch_search.py`
- Modify: `tests/test_fundamental_autoresearch_autoresearch.py`

**Step 1: Write the failing test**

Add tests that require:
- at least some generated weight configs include positive `valuation`
- candidate weights still sum to `1.0` in absolute value
- `health` remains positive and dominant

**Step 2: Run test to verify it fails**

Run:
`python3 -m pytest tests/test_fundamental_autoresearch_search.py tests/test_fundamental_autoresearch_autoresearch.py -k 'valuation or autoresearch' -v`

Expected:
- search space/assertion mismatch

**Step 3: Write minimal implementation**

Extend the constrained generator just enough to satisfy the new tests.

**Step 4: Run test to verify it passes**

Run the same pytest command and verify pass.

### Task 2: Update constrained search/orchestration

**Files:**
- Modify: `tradingagents/research/fundamental_autoresearch/search.py`
- Modify if needed: `tradingagents/research/fundamental_autoresearch/autoresearch.py`
- Modify if needed: `tradingagents/research/fundamental_autoresearch/robustness.py`

**Step 1: Support valuation in the generated strategy names and weights**

Keep the naming deterministic and machine-readable.

**Step 2: Ensure robustness can re-score broadened strategies**

If robustness currently assumes only health/growth/quality, update it minimally.

**Step 3: Run focused tests**

Run:
`python3 -m pytest tests/test_fundamental_autoresearch_search.py tests/test_fundamental_autoresearch_autoresearch.py tests/test_fundamental_autoresearch_robustness.py -v`

Expected:
- broadened search and robustness stay green

### Task 3: Run the real broadened search

**Files:**
- Output artifacts only

**Step 1: Run broadened constrained autoresearch**

Run:
`python3 -m cli.main fundamental-research-autoresearch --prepared-json eval_results/fundamental_autoresearch/sec_cache/prepared/large_cap_v1-2009plus-with-returns.json --results-root eval_results/fundamental_autoresearch --run-date 2026-03-09 --experiment-name large-cap-v1-2009plus-broadened-autoresearch --top-n 10 --robustness-top-n 3 --format json`

**Step 2: Compare against current winner**

Check whether the new best strategy beats:
- `health_0p5__inv_growth_0p1__inv_quality_0p4`
- `+0.087029` `60d` sector-neutral rank IC

**Step 3: Inspect robustness**

If the new winner changes, inspect whether it remains positive across horizons/eras/sectors.

### Task 4: Run focused regression and update memory

**Files:**
- Modify: `memory/WORKING.md`
- Modify: `memory/2026-03-09.md` if it exists, otherwise today’s active log
- Modify: `memory/MEMORY.md` if the result is durable

**Step 1: Run focused regression**

Run:
`python3 -m pytest tests/test_fundamental_autoresearch_search.py tests/test_fundamental_autoresearch_robustness.py tests/test_fundamental_autoresearch_autoresearch.py tests/test_cli_fundamental_research.py -v`

**Step 2: Update memory**

Record:
- whether valuation improved the winner
- whether the broadened search was justified
- recommended next move

**Step 3: Decide**

If valuation does not help:
- stop broadening in this direction

If valuation helps:
- treat valuation as the first justified moderator and consider capital discipline next
