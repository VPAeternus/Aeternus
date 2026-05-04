# Discovery Delta Cohort Scorecards Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add `scout_only`, `technical_only`, and `multi_channel` scorecards to the standard review artifacts so the Discovery Delta layer becomes measurable against peers and the Step 1 baseline.

**Architecture:** Add a shared Delta cohort rollup helper, embed its output into `hindsight.json` and `performance_review.json`, and keep the entire feature read-only with no Step 1 selection changes.

**Tech Stack:** Python 3, pytest, existing hindsight/performance review surfaces

---

### Task 1: Add failing tests for Delta cohort scorecards

**Files:**
- Modify: `/Users/aeternusholdings/Documents/AeternusAgents-opus46/tests/test_hindsight.py`
- Modify: `/Users/aeternusholdings/Documents/AeternusAgents-opus46/tests/test_performance_tracker.py`
- Create or modify: `/Users/aeternusholdings/Documents/AeternusAgents-opus46/tests/test_discovery_delta.py`

**Step 1: Write the failing tests**

- Add a pure rollup test for:
  - `scout_only`
  - `technical_only`
  - `multi_channel`
  - peer comparison
  - Step 1 baseline comparison
- Add one hindsight-level test:
  - result includes `discovery_delta_cohorts`
- Add one performance-review-level test:
  - result includes richer horizon cohort metrics

**Step 2: Run tests to verify they fail**

Run:

```bash
python3 -m pytest tests/test_discovery_delta.py tests/test_hindsight.py tests/test_performance_tracker.py -k 'discovery_delta_cohorts' -v
```

Expected:
- failures because the scorecard helper and embedded review output do not exist yet

### Task 2: Add the shared cohort scorecard helper

**Files:**
- Modify: `/Users/aeternusholdings/Documents/AeternusAgents-opus46/tradingagents/dealflow/discovery_delta.py`

**Step 1: Write the minimal implementation**

- load and interpret Delta cohorts
- compute raw cohort metrics
- compute peer comparisons
- compute Step 1 baseline comparisons
- compute shortlist / deep-selection conversion

**Step 2: Run pure tests**

Run:

```bash
python3 -m pytest tests/test_discovery_delta.py -k 'discovery_delta_cohorts' -v
```

Expected:
- pure Delta cohort tests pass

### Task 3: Embed cohort scorecards in `hindsight`

**Files:**
- Modify: `/Users/aeternusholdings/Documents/AeternusAgents-opus46/tradingagents/dealflow/hindsight.py`

**Step 1: Write the minimal implementation**

- load `discovery_delta.json` if present
- compute `5d` cohort scorecards
- embed them in the returned/persisted hindsight payload as `discovery_delta_cohorts`

**Step 2: Run targeted tests**

Run:

```bash
python3 -m pytest tests/test_hindsight.py -k 'discovery_delta_cohorts' -v
```

Expected:
- hindsight Delta cohort tests pass

### Task 4: Embed cohort scorecards in `performance_review`

**Files:**
- Modify: `/Users/aeternusholdings/Documents/AeternusAgents-opus46/tradingagents/dealflow/performance_tracker.py`

**Step 1: Write the minimal implementation**

- load `discovery_delta.json` if present
- compute `5d`, `20d`, and `3m` cohort scorecards
- embed them in the returned/persisted performance payload as `discovery_delta_cohorts`

**Step 2: Run targeted tests**

Run:

```bash
python3 -m pytest tests/test_performance_tracker.py -k 'discovery_delta_cohorts' -v
```

Expected:
- performance-review Delta cohort tests pass

### Task 5: Run focused regression on touched review surfaces

**Files:**
- No new files unless regressions fail

Run:

```bash
python3 -m pytest tests/test_discovery_delta.py tests/test_hindsight.py tests/test_performance_tracker.py -k 'discovery_delta or LedgerEnrichment' -v
```

Expected:
- Delta cohort rollups and existing review enrichment stay green together

### Task 6: Update memory

**Files:**
- Modify: `/Users/aeternusholdings/Documents/AeternusAgents-opus46/memory/WORKING.md`
- Modify: `/Users/aeternusholdings/Documents/AeternusAgents-opus46/memory/2026-03-07.md`
- Modify: `/Users/aeternusholdings/Documents/AeternusAgents-opus46/memory/MEMORY.md`

**Step 1: Capture the new measurement layer**

- note that Delta cohorts are now measured in the standard review artifacts
- note the three cohorts
- note that the comparisons include both peer cohorts and the Step 1 baseline
