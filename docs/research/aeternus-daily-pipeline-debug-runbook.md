# Aeternus Daily Pipeline Debug Runbook

Use this at the **start of every run** and when debugging the pipeline intraday.

The goal is simple:

- understand the flow in the same order every time
- know which stage is discovery vs collection vs filtering vs research
- know which artifact proves a stage worked
- know which gate blocked or degraded the run

## Golden Rule

Do not treat the pipeline as one black box.

Treat it as a sequence of distinct stages:

1. `X-feed manual readiness`
2. `Other scouts / discovery`
3. `Scout audit gate`
4. `First universe filter`
5. `Collectors`
6. `Collector audit gate`
7. `Second universe filter`
8. `Deep research selection`
9. `Research execution`
10. `Portfolio plan`
11. `Execution / sync`
12. `Hindsight / performance review`

If something looks wrong downstream, debug upstream first.

## Actual Flow

```mermaid
flowchart TD
    A["Manual X-Feed Readiness"] --> B["Discovery Scouts"]
    B --> C["Discovery Delta / Scout Audit Gate"]
    C --> D["First Universe Filter (Tiers + FVG/FMA + Manual)"]
    D --> E["Collectors / Evidence Gathering"]
    E --> F["Evidence Integrity / Collector Audit Gate"]
    F --> G["Second Universe Filter (ACTIVE vs LOW_DATA + ranking inputs)"]
    G --> H["Shortlist / Rank Cut"]
    H --> I["Deep Selection"]
    I --> J["Analyze-Batch / Research Execution"]
    J --> K["Research Conversion Integrity"]
    K --> L["Portfolio Plan"]
    L --> M["Execution / Sync"]
    M --> N["Hindsight / Performance Review / Stage Diagnosis"]
```

## Stage 0: Preflight

Before touching the pipeline, lock in the run context:

- date
- mode: `manual`, `daily`, `event`, or `auto`
- whether manual X-feed is required
- whether this is a dry/debug run or a capital-bearing run

Useful commands:

```bash
python3 -m cli.main x-feed --status --date YYYY-MM-DD
python3 -m cli.main discover --date YYYY-MM-DD --format json
python3 -m cli.main collect --date YYYY-MM-DD --top-k 20 --format json
python3 -m cli.main workflow-run --mode manual --date YYYY-MM-DD --skip-execution --skip-sync --format json
```

## Stage 1: Manual X-Feed Readiness

### What this stage is

This is a **workflow preflight**, not just another signal source.

For `workflow-run --mode manual`, X-feed must be complete before the run should proceed.

### Command

```bash
python3 -m cli.main x-feed --status --date YYYY-MM-DD
```

### Pass condition

- status is `READY`
- `15/15` required passes are present
- merged symbol count is non-zero

### Artifact

- `eval_results/x_feed/YYYY-MM-DD/raw/pass_*.json`
- `eval_results/x_feed/YYYY-MM-DD/merged.json`

### Failure mode

- If this is incomplete, **stop here**
- Do not continue manual-mode workflow runs until this stage is green

## Stage 2: Discovery Scouts

### What this stage is

This is the **new-information discovery layer**.

These are the things that should find or activate names from fresh state change:

- breakout discovery
- IV scanner
- insider sweep
- manual X-feed merge
- `FVG_RECALL`
- `FMA_RECALL`
- background scouts like commodity shock / DoD where applicable

This stage happens in `discover()`, before the universe is finalized.

Relevant code:

- [tradingagents/dealflow/pipeline.py](/Users/aeternusholdings/Documents/AeternusAgents-opus46/tradingagents/dealflow/pipeline.py)
- [tradingagents/dealflow/akg_universe.py](/Users/aeternusholdings/Documents/AeternusAgents-opus46/tradingagents/dealflow/akg_universe.py)

### Command

```bash
python3 -m cli.main discover --date YYYY-MM-DD --format json
```

### Pass condition

- `discover()` completes
- universe size is non-zero
- discovery artifacts are written
- no critical scout failed silently

### Artifacts

- `eval_results/deal_flow/YYYY-MM-DD/scout_audit.json`
- `eval_results/deal_flow/YYYY-MM-DD/fvg_recall.json`
- `eval_results/deal_flow/YYYY-MM-DD/fma_recall.json`
- `eval_results/deal_flow/YYYY-MM-DD/discovery_delta.json`

## Stage 3: Scout Audit Gate

### What this stage is

This is the **read-only measurement layer** for discovery quality.

It answers:

- did scouts fire?
- which names are `scout_only`, `technical_only`, or `multi_channel`?
- did discovery look broad and healthy, or thin and suspicious?

### Same-day checks

Inspect:

- `discovery_delta.json`
- `scout_audit.json`

Look for:

- non-zero `top_delta_symbols`
- non-empty `multi_channel` cohort
- sensible `coverage_summary`

### Later review checks

Use:

```bash
python3 -m cli.main hindsight --source-date YYYY-MM-DD
python3 -m cli.main performance-review --source-date YYYY-MM-DD
python3 -m cli.main stage-diagnosis --last 30
```

## Stage 4: First Universe Filter

### What this stage is

This is the first stock-selection boundary after discovery.

The universe builder currently unions:

- `T1_ANCHOR`
- `T2_NEIGHBOR`
- `T3_SCOUT`
- `T3B_FVG_RECALL`
- `T3C_FMA_RECALL`
- `T4_DARK`
- `T5_RESCAN`
- `T6_PORTFOLIO`
- `MANUAL`

### Important distinction

This stage is not “all scouts only looked at N names.”

This stage is:

- scouts and recall channels fired first
- then the universe builder assembled the bounded set that later collectors will evaluate

### Pass condition

- the filtered universe exists
- tier mix looks sane
- no single tier is accidentally dominating

### Artifacts / diagnostics

- universe ledger rows written into the stage ledger
- workflow console output for tier counts
- later `stage-diagnosis` should reveal whether `universe_gate_edge` or `universe_gate_haystack` is the leak

## Stage 5: Collectors

### What this stage is

This is the **bounded evidence collection layer**, not pure discovery.

Collectors run on the filtered universe, not the full haystack.

Current collectors include:

- social/news
- price momentum
- macro
- smart money
- sector rotation
- insider cluster

Relevant code:

- [tradingagents/dealflow/pipeline.py](/Users/aeternusholdings/Documents/AeternusAgents-opus46/tradingagents/dealflow/pipeline.py)

### Command

```bash
python3 -m cli.main collect --date YYYY-MM-DD --top-k 20 --format json
```

### Pass condition

- connectors execute
- connector health is written
- normalized signals and candidates are produced

### Artifacts

- `eval_results/deal_flow/YYYY-MM-DD/signals_raw.json`
- `eval_results/deal_flow/YYYY-MM-DD/connector_health.json`
- `eval_results/deal_flow/YYYY-MM-DD/all_scored_candidates.json`

## Stage 6: Collector Audit Gate

### What this stage is

This is where you decide whether Step 2 failed because:

- the names were weak
- or the data was weak

The Evidence Integrity classes are:

- `CONFIRMED`
- `SPARSE_BUT_INTERESTING`
- `DATA_DEGRADED`
- `LOW_SIGNAL`

### Pass condition

- `connector_health.json` does not show broad connector failure
- `evidence_integrity.json` is written
- `SPARSE_BUT_INTERESTING` and `DATA_DEGRADED` cohorts are inspectable

### Artifacts

- `eval_results/deal_flow/YYYY-MM-DD/evidence_integrity.json`

### Debug question

If a name was dropped here, ask:

- was it actually weak?
- or did a connector degrade and masquerade as weakness?

## Stage 7: Second Universe Filter

### What this stage is

This is the transition from “all collected candidates” to:

- `ACTIVE`
- `LOW_DATA`
- ranked shortlist inputs

This is also where score-based lane assignment happens for the live system.

Current live execution lanes are:

- `CORE`
- `MOMENTUM`

But candidate records also carry forward-looking lane metadata:

- `upside_3m_score`
- `emergence_proxy_score`
- `lane_candidates`

So when new lanes are added later, debug them here first.

### Pass condition

- `ACTIVE` names are non-zero
- `LOW_DATA` names are explainable
- lane mix is sensible

### Artifacts

- `all_scored_candidates.json`
- evidence gate rows in the stage ledger

## Stage 8: Shortlist / Rank Cut

### What this stage is

This is the first explicit opportunity-cost cut.

It decides:

- which names make the top-k shortlist
- which near-misses get dropped

### Artifacts

- `eval_results/deal_flow/YYYY-MM-DD/shortlist_top20.json`
- `eval_results/deal_flow/YYYY-MM-DD/shortlist_integrity.json`
- `eval_results/deal_flow/YYYY-MM-DD/family_contributions.json`

### Debug question

Are the near-miss names better than the selected shortlist?

If yes, Step 3 is leaking alpha.

## Stage 9: Deep Research Selection

### What this stage is

This allocates scarce research budget.

It decides:

- `selected_for_deep`
- near-miss queue names
- injected names like manual, IV force-queue, or portfolio-preservation names

### Artifact

- `eval_results/deal_flow/YYYY-MM-DD/research_queue.json`
- `eval_results/deal_flow/YYYY-MM-DD/deep_selection_integrity.json`

### Debug question

Did the selected-for-deep names actually deserve the research budget more than the near-misses?

## Fundamental Top-10 daily handoff

Run this after the dealflow framework has finalized the day's ticker handoff and the fundamental framework has produced final scores.

Inputs:

- `eval_results/deal_flow/YYYY-MM-DD/final_dealflow_tickers.json`
- `eval_results/fundamental/YYYY-MM-DD/fundamental_final_scores_YYYY-MM-DD.csv` or the run-specific final-scores CSV

Command:

```bash
python3 -m cli.main fundamental-top10 \
  --scores-csv eval_results/fundamental/YYYY-MM-DD/fundamental_final_scores_YYYY-MM-DD.csv \
  --output-root eval_results/fundamental/YYYY-MM-DD \
  --date YYYY-MM-DD \
  --top-n 10
```

Outputs:

- `eval_results/fundamental/YYYY-MM-DD/high_conviction_top10.csv`
- `eval_results/fundamental/YYYY-MM-DD/high_conviction_top10.json`
- `eval_results/fundamental/YYYY-MM-DD/high_conviction_top10_daily_recommendation.md`

Operating rule: use `high_conviction_top10_v2_final` as observed-data v2, not fully validated AKG+macro v2. Prioritize `rm_signal_bucket=1` as the single-RM-signal bucket; be cautious with `rm_signal_bucket=2+` and HP names unless LLM/theme/valuation evidence is strong. Apply macro permission manually until PIT macro history is validated. Continue forward-validating AKG theme acceleration / T5_RESCAN because historical PIT fields are blank.

## Fundamental Top-15 + right-tail visibility daily handoff

Run Top-15 after Top-10 when the PM wants the core plus right-tail exception/starter-underwriting sleeve:

```bash
python3 -m cli.main fundamental-top15 \
  --scores-csv eval_results/fundamental/YYYY-MM-DD/fundamental_final_scores_YYYY-MM-DD.csv \
  --output-root eval_results/fundamental/YYYY-MM-DD \
  --date YYYY-MM-DD
```

Then run visibility queues:

```bash
python3 -m cli.main fundamental-right-tail-queues \
  --scores-csv eval_results/fundamental/YYYY-MM-DD/fundamental_final_scores_YYYY-MM-DD.csv \
  --top15-selected-csv eval_results/fundamental/YYYY-MM-DD/high_conviction_top15.csv \
  --output-root eval_results/fundamental/YYYY-MM-DD \
  --date YYYY-MM-DD
```

Default outputs:

- `top15_exception_candidate_queue.csv`
- `right_tail_scout_queue.csv`
- `demote_review_queue.csv` full audit queue
- `demote_review_priority_1.csv` daily PM demote-review view
- `demote_review_priority_2.csv`
- `demote_review_low_priority.csv`
- `thin_signal_watchlist_queue.csv` full audit queue
- `thin_signal_watchlist_top100.csv` daily PM thin-signal view; use Top 25 / Top 50 / Top 100 cuts
- `right_tail_evidence_score_diagnostics.csv`
- `right_tail_queues.json`

Daily review order:

1. Top-15 core / exception names
2. `right_tail_scout_queue.csv`
3. `demote_review_priority_1.csv`
4. top-ranked names from `thin_signal_watchlist_top100.csv`

Do not treat scout, demote-review, or thin-signal queues as buy lists. Approved live use is visibility/research only after Top-15.

Optional historical/debug target audit:

```bash
python3 -m cli.main fundamental-right-tail-queues \
  --scores-csv eval_results/fundamental/YYYY-MM-DD/fundamental_final_scores_YYYY-MM-DD.csv \
  --top15-selected-csv eval_results/fundamental/YYYY-MM-DD/high_conviction_top15.csv \
  --target-events-csv docs/research/right_tail_target_events.csv \
  --output-root eval_results/fundamental/YYYY-MM-DD \
  --date YYYY-MM-DD
```

Without `--target-events-csv`, no `target_miss_rescue_audit.csv` is written in daily live mode. These queues are visibility/research queues, not buy lists.

## Stage 10: Research Execution

### What this stage is

This is where deep-selection turns into actual analysis output.

Relevant command:

```bash
python3 -m cli.main analyze-batch --queue-date YYYY-MM-DD --include-unselected --quick-unselected
```

### Pass condition

- analysis summary exists
- success/failure/cached split is visible
- deep path and quick path are distinguishable

### Artifacts

- batch summary under `eval_results/deal_flow/YYYY-MM-DD/`
- `eval_results/deal_flow/YYYY-MM-DD/research_conversion_integrity.json`

### Debug question

Did deep-selected names actually become usable analyses, or did the run degrade into cached fallbacks and failures?

## Stage 11: Portfolio Plan

### What this stage is

This is where research turns into capital allocation.

Relevant command:

```bash
python3 -m cli.main portfolio-plan --queue-date YYYY-MM-DD --capital-usd 100000 --max-positions 8
```

### Pass condition

- plan exists
- benchmark hurdle metadata is present
- portfolio inclusion is explainable

### Debug question

Which names were blocked by:

- score/confidence
- V3 benchmark hurdle
- long-only / position limits

## Stage 12: Execution / Sync

### What this stage is

This is downstream portfolio/execution state management.

For debug runs, it is often correct to stop before this stage:

```bash
python3 -m cli.main workflow-run --mode manual --date YYYY-MM-DD --skip-execution --skip-sync --format json
```

Use live execution only when the earlier gates are green.

## Stage 13: Hindsight / Performance / Diagnosis

### What this stage is

This is the learning loop.

Use:

```bash
python3 -m cli.main hindsight --source-date YYYY-MM-DD
python3 -m cli.main performance-review --source-date YYYY-MM-DD
python3 -m cli.main stage-diagnosis --last 30
```

### What to look at

- `discovery_delta_cohorts`
- `evidence_integrity_cohorts`
- hypothesis stage summaries
- false-negative cost
- future winner recall

If you are not running these, you are not closing the loop.

## Daily Operator Checklist

Use this exact order:

1. Check manual X-feed readiness.
2. Run `discover`.
3. Inspect `scout_audit.json`, `fvg_recall.json`, `fma_recall.json`, `discovery_delta.json`.
4. Confirm the first universe filter looks sane.
5. Run `collect`.
6. Inspect `connector_health.json`, `evidence_integrity.json`, `all_scored_candidates.json`.
7. Inspect `shortlist_top20.json`, `shortlist_integrity.json`, `research_queue.json`, `deep_selection_integrity.json`.
8. Run the fundamental framework on the finalized ticker handoff when the daily fundamental Top-10 is needed.
9. Run `fundamental-top10` and inspect `high_conviction_top10_daily_recommendation.md`.
10. Run `analyze-batch`.
11. Inspect `research_conversion_integrity.json`.
12. Run `portfolio-plan` only after the above looks sane.
13. Run execution/sync only if this is a capital-bearing run.
14. Run hindsight/performance/stage-diagnosis after enough forward time has passed.

## What To Debug First

If today’s run looks wrong:

- wrong names missing entirely:
  - debug `X-feed`, discovery scouts, `FVG_RECALL`, `FMA_RECALL`, and the first universe filter

- names present but killed too early:
  - debug Evidence Integrity and the evidence gate

- good names sitting just below the cut:
  - debug Shortlist Integrity

- research budget spent on the wrong names:
  - debug Deep Selection Integrity

- research output weak or too cached:
  - debug Research Conversion Integrity

- plan weaker than expected:
  - debug portfolio hurdle / inclusion logic

## Current Architectural Truth

The pipeline is now instrumented well enough that the next gains should come from:

- real forward-testing evidence
- stage-by-stage diagnosis
- changing the specific stage that is leaking alpha

Not from treating the whole system as one opaque model.
