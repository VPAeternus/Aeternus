# Discovery Delta CLI Surface Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Surface the new read-only Discovery Delta ranking in the existing operator-facing deal-flow CLI without changing Step 1 behavior.

**Architecture:** Add a shared renderer in `cli/common.py`, extend `DealFlowPipeline.discover()` to return the full delta payload, and render it from `dealflow discover` and `dealflow source`.

**Tech Stack:** Python 3, Rich tables, pytest

---

### Task 1: Add failing CLI tests for Discovery Delta rendering

**Files:**
- Modify: `/Users/aeternusholdings/Documents/AeternusAgents-opus46/tests/test_cli_dealflow.py`

**Step 1: Write the failing tests**

- Add one test for `dealflow discover`:
  - when `discover()` returns `discovery_delta`, the CLI output includes `Discovery Delta`
- Add one test for `dealflow source`:
  - when the pipeline returns a shortlist/research queue and a delta payload, the CLI output includes Delta cohort or top-symbol information

**Step 2: Run tests to verify they fail**

Run:

```bash
python3 -m pytest tests/test_cli_dealflow.py -k 'discovery_delta' -v
```

Expected:
- failures because there is no shared Delta renderer wired into those commands

### Task 2: Add the shared Delta renderer

**Files:**
- Modify: `/Users/aeternusholdings/Documents/AeternusAgents-opus46/cli/common.py`

**Step 1: Write the minimal implementation**

- add `_render_discovery_delta_summary(...)`
- render:
  - top delta symbols
  - delta score
  - independent channels
  - source list
  - cohort counts

**Step 2: Keep the renderer silent on empty input**

- if there is no usable delta payload, return without printing

### Task 3: Thread Delta payload through `discover()` and render it in the deal-flow commands

**Files:**
- Modify: `/Users/aeternusholdings/Documents/AeternusAgents-opus46/tradingagents/dealflow/pipeline.py`
- Modify: `/Users/aeternusholdings/Documents/AeternusAgents-opus46/cli/commands/dealflow.py`

**Step 1: Write the minimal implementation**

- extend `discover()` to return:
  - `discovery_delta`
  - alongside `discovery_delta_summary`
- in `dealflow discover`, call `_render_discovery_delta_summary(...)`
- in `dealflow source`, call `_render_discovery_delta_summary(...)` using the discovery payload available from `pipeline.run(...)`

**Step 2: Run targeted tests**

Run:

```bash
python3 -m pytest tests/test_cli_dealflow.py -k 'discovery_delta' -v
```

Expected:
- new CLI tests pass

### Task 4: Run focused regression on touched discovery and CLI surfaces

**Files:**
- No new files unless regressions fail

Run:

```bash
python3 -m pytest tests/test_cli_dealflow.py tests/test_dealflow_pipeline.py tests/test_discovery_delta.py -k 'discovery_delta or discover or source' -v
```

Expected:
- Delta renderer works
- discover-path artifact tests still pass
- no regression in discovery output flow

### Task 5: Update memory

**Files:**
- Modify: `/Users/aeternusholdings/Documents/AeternusAgents-opus46/memory/WORKING.md`
- Modify: `/Users/aeternusholdings/Documents/AeternusAgents-opus46/memory/2026-03-07.md`
- Modify: `/Users/aeternusholdings/Documents/AeternusAgents-opus46/memory/MEMORY.md` only if the CLI surface is durable enough to remember

**Step 1: Capture the new operator visibility**

- note that Discovery Delta is now visible in the CLI
- note which commands render it
- note that it remains read-only
