# Autonomous Fundamental Signal Roadmap Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Turn the current SEC/XBRL fundamental autoresearch harness into a production-ready autonomous signal factory that can generate, test, gate, and shadow-promote live fundamental signals within 1-2 days.

**Architecture:** Reuse the existing point-in-time SEC harness as the truth engine. Add a promotion gate, replay arena, and local-model residual layer around it instead of replacing the live fundamental pillar directly. The deterministic formula remains the core alpha engine; local MLX/Qwen augments it only where structured data is weak or contradictory.

**Tech Stack:** Python 3, SEC EDGAR APIs/XBRL JSON, pandas/numpy, pytest, existing Aeternus CLI, local MLX/Qwen, current `fundamental_autoresearch` package.

---

## Delivery Standard

This roadmap assumes:
- the deterministic SEC harness already exists and is the source of truth
- the current canonical winner is:
  - `health_0p5__inv_growth_0p1__inv_quality_0p4`
- the current objective is **not** to replace the live pillar immediately
- the objective is to make the harness useful enough to:
  - produce nightly/continuous signal research
  - gate promotion scientifically
  - expose a clean shadow signal family
  - support later local-model residual research

## Day 1 Outcome

By the end of Day 1, the system should be able to:
- run deterministic fundamental autoresearch on the historical `2009+` filing dataset
- save a ranked strategy leaderboard
- compare candidates against a fixed live/shadow promotion contract
- generate a replay artifact showing whether the new signal would have improved capital allocation

## Day 2 Outcome

By the end of Day 2, the system should be able to:
- run a local-model residual filing layer on only the highest-value edge cases
- record residual features beside the deterministic score
- let a local-model research copilot propose bounded new transforms without entering the live signal path

---

### Task 1: Formalize the Fundamental Signal Registry

**Files:**
- Create: `tradingagents/research/fundamental_autoresearch/registry.py`
- Test: `tests/test_fundamental_autoresearch_registry.py`

**Step 1: Write the failing test**

Cover:
- registering a candidate strategy result
- tracking canonical winner
- marking strategy metadata:
  - strategy name
  - horizons
  - primary metric
  - coverage
  - robustness summary
  - status (`candidate`, `shadow`, `promoted`, `rejected`)

**Step 2: Run test to verify it fails**

Run:
```bash
python3 -m pytest tests/test_fundamental_autoresearch_registry.py -v
```

Expected:
- import/module failure

**Step 3: Write minimal implementation**

Implement:
- registry row contract
- deterministic load/save helpers
- canonical-winner selector

**Step 4: Run test to verify it passes**

Run:
```bash
python3 -m pytest tests/test_fundamental_autoresearch_registry.py -v
```

**Step 5: Commit**

```bash
git add tradingagents/research/fundamental_autoresearch/registry.py tests/test_fundamental_autoresearch_registry.py
git commit -m "feat: add fundamental signal registry"
```

### Task 2: Build the Promotion Gate

**Files:**
- Create: `tradingagents/research/fundamental_autoresearch/promotion_gate.py`
- Modify: `tradingagents/research/fundamental_autoresearch/artifacts.py`
- Test: `tests/test_fundamental_autoresearch_promotion_gate.py`

**Step 1: Write the failing test**

Cover:
- candidate passes gate when all thresholds are met
- candidate fails on low coverage
- candidate fails on weak robustness
- candidate remains `shadow` instead of `promoted` by default

**Step 2: Run test to verify it fails**

Run:
```bash
python3 -m pytest tests/test_fundamental_autoresearch_promotion_gate.py -v
```

**Step 3: Write minimal implementation**

Implement gate fields such as:
- minimum `60d` sector-neutral IC
- minimum coverage
- positive `20d/60d/120d`
- sector breadth
- era breadth
- optional t-stat threshold when available

**Step 4: Run test to verify it passes**

Run:
```bash
python3 -m pytest tests/test_fundamental_autoresearch_promotion_gate.py -v
```

**Step 5: Commit**

```bash
git add tradingagents/research/fundamental_autoresearch/promotion_gate.py tradingagents/research/fundamental_autoresearch/artifacts.py tests/test_fundamental_autoresearch_promotion_gate.py
git commit -m "feat: add fundamental signal promotion gate"
```

### Task 3: Add the Replay Arena

**Files:**
- Create: `tradingagents/research/fundamental_autoresearch/replay_arena.py`
- Modify: `cli/commands/fundamental_research.py`
- Test: `tests/test_fundamental_autoresearch_replay_arena.py`

**Step 1: Write the failing test**

Cover:
- comparing multiple strategies on the same prepared dataset
- ranking by horizon
- outputting strategy-vs-baseline summaries

**Step 2: Run test to verify it fails**

Run:
```bash
python3 -m pytest tests/test_fundamental_autoresearch_replay_arena.py -v
```

**Step 3: Write minimal implementation**

Implement:
- arena runner for:
  - canonical winner
  - baseline_v1
  - health_only
  - best inverted baseline
- replay summary artifact
- CLI:
  - `python3 -m cli.main fundamental-research-replay-arena`

**Step 4: Run test to verify it passes**

Run:
```bash
python3 -m pytest tests/test_fundamental_autoresearch_replay_arena.py -v
```

**Step 5: Commit**

```bash
git add tradingagents/research/fundamental_autoresearch/replay_arena.py cli/commands/fundamental_research.py tests/test_fundamental_autoresearch_replay_arena.py
git commit -m "feat: add fundamental replay arena"
```

### Task 4: Expose a Shadow Fundamental Signal Family

**Files:**
- Create: `tradingagents/research/fundamental_autoresearch/shadow_signal.py`
- Modify: `tradingagents/graph/session_assembler.py`
- Modify: `tradingagents/graph/aeternus_scoring.py`
- Test: `tests/test_fundamental_autoresearch_shadow_signal.py`

**Step 1: Write the failing test**

Cover:
- shadow signal appears in assembled/scored output
- official live fundamental pillar remains unchanged
- shadow metadata includes:
  - strategy name
  - score
  - gate status
  - promotion recommendation

**Step 2: Run test to verify it fails**

Run:
```bash
python3 -m pytest tests/test_fundamental_autoresearch_shadow_signal.py -v
```

**Step 3: Write minimal implementation**

Implement:
- pure helper to score a row with the canonical winner
- attach shadow signal metadata beside current fundamental output
- no weighting into official score yet

**Step 4: Run test to verify it passes**

Run:
```bash
python3 -m pytest tests/test_fundamental_autoresearch_shadow_signal.py -v
```

**Step 5: Commit**

```bash
git add tradingagents/research/fundamental_autoresearch/shadow_signal.py tradingagents/graph/session_assembler.py tradingagents/graph/aeternus_scoring.py tests/test_fundamental_autoresearch_shadow_signal.py
git commit -m "feat: add shadow fundamental signal family"
```

### Task 5: Add the Residual Filing Intelligence Interface

**Files:**
- Create: `tradingagents/research/fundamental_autoresearch/residual_layer.py`
- Create: `tradingagents/research/fundamental_autoresearch/residual_prompts.py`
- Test: `tests/test_fundamental_autoresearch_residual_layer.py`

**Step 1: Write the failing test**

Cover:
- selecting only edge-case filings for residual review
- generating deterministic local-model tasks
- storing residual placeholders even when local model is unavailable

**Step 2: Run test to verify it fails**

Run:
```bash
python3 -m pytest tests/test_fundamental_autoresearch_residual_layer.py -v
```

**Step 3: Write minimal implementation**

Implement:
- edge-case selector based on:
  - low coverage
  - large score delta
  - contradictory factor signals
  - extreme market reaction
- prompt payload generator for local MLX/Qwen
- residual artifact contract

**Step 4: Run test to verify it passes**

Run:
```bash
python3 -m pytest tests/test_fundamental_autoresearch_residual_layer.py -v
```

**Step 5: Commit**

```bash
git add tradingagents/research/fundamental_autoresearch/residual_layer.py tradingagents/research/fundamental_autoresearch/residual_prompts.py tests/test_fundamental_autoresearch_residual_layer.py
git commit -m "feat: add residual filing intelligence interface"
```

### Task 6: Add the Local Research Copilot

**Files:**
- Create: `tradingagents/research/fundamental_autoresearch/research_copilot.py`
- Modify: `cli/commands/fundamental_research.py`
- Test: `tests/test_fundamental_autoresearch_research_copilot.py`

**Step 1: Write the failing test**

Cover:
- reading leaderboard + robustness + failures
- proposing bounded transform experiments
- rejecting out-of-scope factor proposals

**Step 2: Run test to verify it fails**

Run:
```bash
python3 -m pytest tests/test_fundamental_autoresearch_research_copilot.py -v
```

**Step 3: Write minimal implementation**

Implement:
- local prompt assembler for MLX/Qwen
- bounded proposal schema:
  - invert sign
  - add interaction
  - add acceleration
  - clip / winsorize
  - sector-normalize
- CLI:
  - `python3 -m cli.main fundamental-research-copilot`

**Step 4: Run test to verify it passes**

Run:
```bash
python3 -m pytest tests/test_fundamental_autoresearch_research_copilot.py -v
```

**Step 5: Commit**

```bash
git add tradingagents/research/fundamental_autoresearch/research_copilot.py cli/commands/fundamental_research.py tests/test_fundamental_autoresearch_research_copilot.py
git commit -m "feat: add local fundamental research copilot"
```

### Task 7: Add a Canonical Autoresearch Runner

**Files:**
- Modify: `tradingagents/research/fundamental_autoresearch/autoresearch.py`
- Modify: `cli/commands/fundamental_research.py`
- Test: `tests/test_fundamental_autoresearch_autoresearch.py`

**Step 1: Write the failing test**

Cover:
- end-to-end run produces:
  - leaderboard
  - best strategy
  - gate result
  - registry update

**Step 2: Run test to verify it fails**

Run:
```bash
python3 -m pytest tests/test_fundamental_autoresearch_autoresearch.py -v
```

**Step 3: Write minimal implementation**

Implement:
- orchestration command that runs:
  - constrained search
  - robustness
  - promotion gate
  - registry persistence

**Step 4: Run test to verify it passes**

Run:
```bash
python3 -m pytest tests/test_fundamental_autoresearch_autoresearch.py -v
```

**Step 5: Commit**

```bash
git add tradingagents/research/fundamental_autoresearch/autoresearch.py cli/commands/fundamental_research.py tests/test_fundamental_autoresearch_autoresearch.py
git commit -m "feat: wire canonical fundamental autoresearch runner"
```

### Task 8: Run the 48-Hour Production Research Loop

**Files:**
- Modify: `memory/WORKING.md`
- Modify: `memory/YYYY-MM-DD.md`
- Create: `eval_results/fundamental_autoresearch/<date>/<experiment>/...`

**Step 1: Prime the current dataset**

Run:
```bash
python3 -m cli.main fundamental-research-prepare --symbols large_cap_v1 --cache-root eval_results/fundamental_autoresearch/sec_cache --run-name large_cap_v1-2009plus --all-filings --start-year 2009
python3 -m cli.main fundamental-research-attach-returns --prepared-json eval_results/fundamental_autoresearch/sec_cache/prepared/large_cap_v1-2009plus.json --output-json eval_results/fundamental_autoresearch/sec_cache/prepared/large_cap_v1-2009plus-with-returns.json
```

**Step 2: Run the canonical research loop**

Run:
```bash
python3 -m cli.main fundamental-research-autoresearch --prepared-json eval_results/fundamental_autoresearch/sec_cache/prepared/large_cap_v1-2009plus-with-returns.json --experiment-name large-cap-v1-canonical
```

**Step 3: Run replay arena**

Run:
```bash
python3 -m cli.main fundamental-research-replay-arena --prepared-json eval_results/fundamental_autoresearch/sec_cache/prepared/large_cap_v1-2009plus-with-returns.json --experiment-name large-cap-v1-arena
```

**Step 4: Record results**

Update `memory/WORKING.md` with:
- canonical winner
- gate result
- whether the shadow family should remain advisory only
- whether residual layer is justified next

**Step 5: Commit**

```bash
git add memory/WORKING.md memory/$(date +%F).md eval_results/fundamental_autoresearch
git commit -m "docs: record autonomous fundamental signal loop results"
```

---

## 48-Hour Execution Order

### Day 1
- Task 1
- Task 2
- Task 3
- Task 4

### Day 2
- Task 5
- Task 6
- Task 7
- Task 8

## What Not To Do In This Window

- Do not replace the live fundamental pillar directly.
- Do not widen the universe before the registry, gate, and arena are working.
- Do not put local Qwen into the core scoring loop.
- Do not treat residual LLM outputs as production alpha without deterministic comparison.

## Definition of Success

At the end of this roadmap we should have:
- a repeatable autonomous fundamental signal factory
- a registry of candidate signals
- a hard promotion gate
- a replay arena proving whether the signal helps capital allocation
- a shadow live signal family
- a local residual intelligence interface
- a bounded local-model copilot for proposing new factor transforms
