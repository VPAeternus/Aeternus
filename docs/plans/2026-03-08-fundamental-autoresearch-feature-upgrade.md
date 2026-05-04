# Fundamental Autoresearch Feature Upgrade Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Improve the deterministic fundamental feature definitions so the health-led, anti-crowding model is operating on more truthful inputs before any broader search-space expansion.

**Architecture:** Extend the existing prepared-row feature builder with a small set of additive growth-acceleration, quality-expectation, and health-stress features while keeping the scoring and evaluation contracts stable.

**Tech Stack:** Python 3, pytest, existing fundamental autoresearch harness

---

### Task 1: Add failing tests for upgraded derived features

**Files:**
- Modify: `tests/test_fundamental_autoresearch_features.py`

**Step 1: Write the failing test**

Add tests for:
- `revenue_growth_acceleration_pct`
- `fcf_growth_acceleration_pct`
- `margin_change_pct`
- `quality_valuation_tension`
- `liquidity_stress_score`
- `leverage_stress_score`

Use synthetic filing snapshots with enough point-in-time inputs to derive these fields.

**Step 2: Run test to verify it fails**

Run:
`python3 -m pytest tests/test_fundamental_autoresearch_features.py -k 'acceleration or tension or stress' -v`

Expected:
- missing keys or wrong values

**Step 3: Write minimal implementation**

Implement only the feature derivations needed for the tests.

**Step 4: Run test to verify it passes**

Run the same pytest command and verify pass.

### Task 2: Extend the deterministic feature builder

**Files:**
- Modify: `tradingagents/research/fundamental_autoresearch/features.py`

**Step 1: Add the new derived fields**

Implement additive feature fields while preserving current output keys.

**Step 2: Keep missingness honest**

If a feature cannot be derived from current inputs, return `None` or a neutral-safe representation rather than making it up.

**Step 3: Run focused tests**

Run:
`python3 -m pytest tests/test_fundamental_autoresearch_features.py -v`

Expected:
- full feature-builder suite passes

### Task 3: Decide whether score family definitions should consume new fields

**Files:**
- Modify if needed: `tradingagents/research/fundamental_autoresearch/score.py`

**Step 1: Add failing tests only if score behavior changes**

If the new features should influence the sub-score definitions, add targeted score tests first.

**Step 2: Implement minimal score adjustments**

Only touch the specific family definitions that should consume the refined features.

**Step 3: Run focused score tests**

Run:
`python3 -m pytest tests/test_fundamental_autoresearch_score.py -v`

Expected:
- score suite passes

### Task 4: Run the scientific comparison sequence again

**Files:**
- No code changes required unless regressions appear

**Step 1: Rerun baseline comparison**

Run:
`python3 -m cli.main fundamental-research-compare-baselines --prepared-json eval_results/fundamental_autoresearch/sec_cache/prepared/large_cap_v1-2009plus-with-returns.json --results-root eval_results/fundamental_autoresearch --run-date 2026-03-08 --experiment-name large-cap-v1-2009plus-baseline-comparison-v2 --format json`

**Step 2: Rerun constrained autoresearch**

Run:
`python3 -m cli.main fundamental-research-autoresearch --prepared-json eval_results/fundamental_autoresearch/sec_cache/prepared/large_cap_v1-2009plus-with-returns.json --results-root eval_results/fundamental_autoresearch --run-date 2026-03-08 --experiment-name large-cap-v1-2009plus-constrained-autoresearch-v2 --top-n 10 --robustness-top-n 3 --format json`

**Step 3: Inspect whether the winner improved**

Compare the new best strategy against:
- prior winner `health_0p5__inv_growth_0p1__inv_quality_0p4`
- prior `60d` rank IC `+0.087029`

### Task 5: Run focused regression and update memory

**Files:**
- Modify: `memory/WORKING.md`
- Modify: `memory/2026-03-08.md`
- Modify: `memory/MEMORY.md` if the new result is durable

**Step 1: Run focused harness regression**

Run:
`python3 -m pytest tests/test_fundamental_autoresearch_features.py tests/test_fundamental_autoresearch_score.py tests/test_fundamental_autoresearch_evaluate.py tests/test_fundamental_autoresearch_search.py tests/test_fundamental_autoresearch_robustness.py tests/test_fundamental_autoresearch_autoresearch.py tests/test_cli_fundamental_research.py -v`

**Step 2: Update memory**

Record:
- what changed in the feature set
- whether the winner changed
- whether signal quality improved

**Step 3: Decide the next move**

If the winner improves:
- consider a carefully broadened constrained search space

If it does not:
- keep the old winner and avoid unnecessary feature complexity
