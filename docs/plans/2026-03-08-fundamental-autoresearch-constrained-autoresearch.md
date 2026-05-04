# Fundamental Autoresearch Constrained Autoresearch Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a deterministic constrained autoresearch loop for the fundamental harness that searches only the validated `health + inverted growth + inverted quality` space and writes ranked experiment artifacts.

**Architecture:** Build a small orchestration layer on top of the existing scorer, evaluator, constrained-search generator, and robustness module. Keep the loop deterministic, artifact-driven, and read-only with respect to the live pillar.

**Tech Stack:** Python 3, Typer, pytest, existing fundamental autoresearch harness

---

### Task 1: Add failing tests for constrained autoresearch orchestration

**Files:**
- Create: `tests/test_fundamental_autoresearch_autoresearch.py`
- Modify: `tests/test_cli_fundamental_research.py`

**Step 1: Write the failing test**

Add tests that expect:
- a deterministic leaderboard sorted by primary metric
- a best-strategy summary payload
- optional robustness output for the top candidates
- CLI command output for the new autoresearch command

**Step 2: Run test to verify it fails**

Run:
`python3 -m pytest tests/test_fundamental_autoresearch_autoresearch.py tests/test_cli_fundamental_research.py -k 'autoresearch' -v`

Expected:
- import or command failure because the orchestration module/CLI does not exist yet

**Step 3: Write minimal implementation**

Create the smallest orchestration implementation to satisfy the new tests.

**Step 4: Run test to verify it passes**

Run the same pytest command and verify pass.

**Step 5: Commit**

Commit once the orchestration and CLI tests pass.

### Task 2: Implement deterministic autoresearch orchestration

**Files:**
- Create: `tradingagents/research/fundamental_autoresearch/autoresearch.py`
- Modify: `tradingagents/research/fundamental_autoresearch/artifacts.py`

**Step 1: Write the failing test**

Expand tests to require:
- configurable top-`N` truncation
- best-strategy extraction
- optional top-candidate robustness bundle

**Step 2: Run test to verify it fails**

Run:
`python3 -m pytest tests/test_fundamental_autoresearch_autoresearch.py -v`

Expected:
- missing fields or wrong artifact shape

**Step 3: Write minimal implementation**

Implement:
- experiment runner
- best-strategy selector
- leaderboard truncation
- artifact writers for:
  - `leaderboard.json`
  - `best_strategy.json`
  - `autoresearch_summary.json`
  - optional `top_robustness.json`

**Step 4: Run test to verify it passes**

Run the same pytest command and verify pass.

**Step 5: Commit**

Commit after orchestration behavior is stable.

### Task 3: Add CLI surface

**Files:**
- Modify: `cli/commands/fundamental_research.py`

**Step 1: Write the failing test**

Require a new command:
- `fundamental-research-autoresearch`

Inputs:
- `--prepared-json`
- `--results-root`
- `--run-date`
- `--experiment-name`
- `--top-n`
- `--robustness-top-n`
- `--format`

**Step 2: Run test to verify it fails**

Run:
`python3 -m pytest tests/test_cli_fundamental_research.py -k 'autoresearch' -v`

Expected:
- CLI command missing or output mismatch

**Step 3: Write minimal implementation**

Wire the command to the new orchestration module and render table/json output.

**Step 4: Run test to verify it passes**

Run the same pytest command and verify pass.

**Step 5: Commit**

Commit the CLI slice after tests pass.

### Task 4: Run focused harness verification

**Files:**
- No code changes required unless regressions appear

**Step 1: Run focused regression**

Run:
`python3 -m pytest tests/test_fundamental_autoresearch_contracts.py tests/test_fundamental_autoresearch_universe.py tests/test_fundamental_autoresearch_time_utils.py tests/test_fundamental_autoresearch_sec_ingest.py tests/test_fundamental_autoresearch_features.py tests/test_fundamental_autoresearch_score.py tests/test_fundamental_autoresearch_evaluate.py tests/test_fundamental_autoresearch_search.py tests/test_fundamental_autoresearch_robustness.py tests/test_fundamental_autoresearch_autoresearch.py tests/test_fundamental_autoresearch_artifacts.py tests/test_fundamental_autoresearch_sec_fetch.py tests/test_fundamental_autoresearch_prepare.py tests/test_fundamental_autoresearch_sector_map.py tests/test_fundamental_autoresearch_market_data.py tests/test_cli_fundamental_research.py -v`

Expected:
- full focused harness suite passes

**Step 2: Fix any regressions**

If failures appear, make the smallest surgical fix and rerun.

**Step 3: Commit**

Commit once focused verification is green.

### Task 5: Run the first real constrained autoresearch experiment

**Files:**
- Output artifacts only

**Step 1: Run the real command**

Run:
`python3 -m cli.main fundamental-research-autoresearch --prepared-json eval_results/fundamental_autoresearch/sec_cache/prepared/large_cap_v1-2009plus-with-returns.json --results-root eval_results/fundamental_autoresearch --run-date 2026-03-08 --experiment-name large-cap-v1-2009plus-constrained-autoresearch --top-n 10 --robustness-top-n 3 --format json`

Expected:
- ranked autoresearch output
- artifact directory written

**Step 2: Inspect artifacts**

Check:
- `leaderboard.json`
- `best_strategy.json`
- `autoresearch_summary.json`
- `top_robustness.json`

**Step 3: Summarize the result**

Capture:
- winning strategy
- whether it improves on the prior constrained-search winner
- whether the top candidates remain robust

### Task 6: Update memory

**Files:**
- Modify: `memory/WORKING.md`
- Modify: `memory/2026-03-08.md`
- Modify: `memory/MEMORY.md` if the result is architecturally durable

**Step 1: Update working memory**

Add:
- what was built
- tests run
- real experiment result
- next recommendation

**Step 2: Update daily log**

Append:
- autoresearch command
- artifact paths
- winning strategy/result

**Step 3: Update long-term memory if warranted**

If the autoresearch result materially strengthens the current thesis, add a durable note.
