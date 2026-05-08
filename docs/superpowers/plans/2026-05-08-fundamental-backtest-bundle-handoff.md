# Fundamental Backtest Bundle Handoff Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a clean point-in-time fundamental panel and high-conviction Top-10 backtest bundle that the analyst model can evaluate directly.

**Architecture:** Use the existing live scoring implementation and the transferred historical rank-score CSV as the source data. Keep selection features, outcome labels, and metadata separated; implement the requested A/B/C Top-10 variants as explicit deterministic formulas over the PIT panel. Do not add a new discovery stack, Pipeline 0, or Parquet architecture.

**Tech Stack:** Python stdlib CSV/JSON, existing `tradingagents.research.fundamental.backtests.pit_panel`, existing fundamental scoring modules, pytest.

---

## Current State / Source Data

Historical labeled data now exists and should be used as the primary source:

- Primary source CSV:
  - `tradingagents/research/fundamental/Growth/earnings_8k_sec_parser/combined_all_tiers_hp_extensions_llm_rank_scores_2021Q4_2026Q1_partial.csv`
- Observed shape from local audit:
  - `22,304` rows
  - `1,279` tickers
  - `19` quarters
  - observed quarter range: `2021Q4` through `2026Q2`
  - `21,182` non-empty `return_90d_pct` rows
  - no duplicate `(quarter, ticker)` rows
- Provenance caveat:
  - Source filename says `2021Q4_2026Q1_partial`, but the transferred file currently contains `2026Q2` rows.
  - Execution must audit and record the actual quarter distribution in `HANDOFF_MANIFEST.json` before handoff.
  - Default behavior: include all observed rows unless the user explicitly requests excluding `2026Q2`.
- Existing legacy output for reference only:
  - `tradingagents/research/fundamental/Growth/earnings_8k_sec_parser/backtests/high_conviction_top10/high_conviction_top10_selections.csv`
  - `.../high_conviction_top10_quarter_summary.csv`
  - `.../high_conviction_top10_aggregate.csv`

Known source caveat:

- The transferred historical CSV does not contain these PIT fields:
  - `theme_acceleration_score`
  - `theme_acceleration_research_visibility`
  - `theme_acceleration_rescan_flag`
  - `akg_universe_tier`
  - `macro_mode`
  - `macro_spy`
  - `macro_entry_action`
  - `macro_position_size_multiplier`
- Keep those columns present but blank in the panel unless a point-in-time timestamped source is proven. Do not merge current AKG state into historical rows without PIT proof.
- Still implement and test v2 theme/T5/macro behavior using synthetic test rows so the rules work when PIT-safe fields are present.

---

## Required PIT Contract

Selection-time columns, exactly present in `pit_fundamental_panel.csv`:

```text
ticker
quarter
tradable_date
entry_open
entry_qoq_pct
prior_entry_qoq_pct
score_change
pre_llm_fundamental_score
pre_llm_fundamental_bucket
revenue_bucket
tier_0_bucket
tier_1_bucket
tier_2_bucket
tier_3_bucket
tier_4_bucket
hp0_high_price_broad
hp1_quality_pullback
hp2_dislocation_momentum_priority
hp2_dislocation_momentum_watch
hp3_large_quality_theme_exception
hp4_score_reacceleration_watch
hp_production_extension
hp_research_extension
hp_LLM_best
rm1_low_price_dislocation_momentum
rm2_weak_acceleration
rm3_mid_price_dislocation_momentum
rm4_persistent_repricing_wave
repricing_momentum_extension
repricing_momentum_priority
market_repricing_score
rm_buy_review_flag
post_llm_candidate_flag
post_llm_high_priority_flag
post_llm_demote_flag
causal_change
negative_revision_risk
narrative_delta_bucket
operating_leverage_quality
durability
score_addition
primary_theme
secondary_themes
theme_role
theme_confidence
theme_driver_type
theme_momentum
theme_acceleration_score
theme_tailwind_score
theme_acceleration_research_visibility
theme_acceleration_rescan_flag
akg_universe_tier
macro_mode
macro_spy
macro_entry_action
macro_position_size_multiplier
tier_structure_score
hp_structure_score
total_structure_score
llm_business_improvement_score
fundamental_rerating_score
risk_penalty_score
entry_raw_score
entry_score_0_100
```

Outcome-label columns, exactly present but excluded from selection:

```text
return_10d_pct
return_20d_pct
return_30d_pct
return_60d_pct
return_90d_pct
winner_90d_30pct
loser_90d_minus30pct
```

Audit columns, exactly present:

```text
is_partial_live_quarter
is_future_date_anomaly
eligible_for_backtest
pipeline_run_id
scoring_formula_version
tier_rule_version
hp_rule_version
rm_rule_version
theme_rule_version
macro_rule_version
source_file_hash
```

---

## File Structure

Modify:

- `tradingagents/research/fundamental/backtests/high_conviction_top10.py`
  - Replace current selector-config variants with exact requested A/B/C formulas.
  - Preserve strict PIT feature allowlist and post-selection label attachment.
  - Write all required output CSVs and manifest.

- `tests/test_fundamental_high_conviction_top10_backtest.py`
  - Add exact formula tests for A/B/C.
  - Add no-leakage tests for returns, monitoring score, and final rank score.
  - Add v2 theme/T5 and macro block tests.

Use existing, modify only if export correctness requires:

- `tradingagents/research/fundamental/backtests/pit_panel.py`
  - Already emits required columns, derives winner/loser labels, preserves missing-field manifests, and separates feature/label/metadata schemas.
  - Only patch if required columns or manifest behavior fail against the transferred historical CSV.

Read-only source-of-truth references:

- `tradingagents/research/fundamental/src/features/scoring.py`
- `tradingagents/research/fundamental/src/features/tiers.py`
- `tradingagents/research/fundamental/src/features/hp_subtiers.py`
- `tradingagents/research/fundamental/src/features/repricing_momentum.py`
- `tradingagents/research/fundamental/src/features/themes.py`
- `tradingagents/research/fundamental/src/pipeline/run_on_new_filing.py`
- `tradingagents/research/fundamental/src/pipeline/run_quarter.py`

Live-scoring parity requirements to preserve and verify:

- `compute_entry_score()` uses `total_structure_score = max(tier_structure_score, hp_structure_score)`.
- `run_on_new_filing.build_signal_tables()` batch-applies `add_hp_subtiers()` and `add_repricing_momentum()` before scoring.
- `run_quarter._add_entry_qoq_pct()` persists `prior_entry_qoq_pct` so RM4 can use current and prior repricing waves.
- `ENTRY_SCORE_FORBIDDEN_COLUMNS` includes forward returns, `return_since_*`, and monitoring scores; these are stripped before entry scoring.
- Tests must keep proving HP live scoring, RM live scoring, and RM4 prior-entry behavior while the export/backtest work changes.

Generated artifacts, do not commit unless explicitly requested:

- `outputs/fundamental_backtest/pit_fundamental_panel.csv`
- `outputs/fundamental_backtest/feature_schema.json`
- `outputs/fundamental_backtest/label_schema.json`
- `outputs/fundamental_backtest/run_manifest.json`
- `outputs/fundamental_backtest/README_ANALYSIS.md`
- `outputs/fundamental_backtest/high_conviction_top10/selected_names_by_quarter.csv`
- `outputs/fundamental_backtest/high_conviction_top10/strategy_by_quarter.csv`
- `outputs/fundamental_backtest/high_conviction_top10/strategy_summary.csv`
- `outputs/fundamental_backtest/high_conviction_top10/variant_summary.csv`
- `outputs/fundamental_backtest/high_conviction_top10/misses_analysis.csv`
- `outputs/fundamental_backtest/high_conviction_top10/theme_bucket_summary.csv`
- `outputs/fundamental_backtest/high_conviction_top10/rm_hp_tier_contribution.csv`
- `outputs/fundamental_backtest/high_conviction_top10/run_manifest.json`
- `outputs/fundamental_backtest/high_conviction_top10/README_ANALYSIS.md`

---

## Task 1: Align Top-10 variants to analyst formulas

**Files:**
- Modify: `tradingagents/research/fundamental/backtests/high_conviction_top10.py`
- Test: `tests/test_fundamental_high_conviction_top10_backtest.py`

- [ ] **Step 1: Write failing tests for exact Variant A**

Add tests proving:

- `entry_score_top10` excludes `entry_score_0_100 < 70`.
- Ranking is `entry_score_0_100 desc`, then `ticker asc` for ties.
- Return labels do not change selected tickers.

Run:

```bash
PYTHONPATH=. /Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m pytest tests/test_fundamental_high_conviction_top10_backtest.py -q
```

Expected: fails before implementation if A does not enforce score >= 70.

- [ ] **Step 2: Implement exact Variant A**

In `high_conviction_top10.py`, implement:

```text
eligible = eligible_for_backtest == True AND entry_score_0_100 >= 70
rank = entry_score_0_100 desc, ticker asc
take top 10 per quarter
```

Output `hc_score` for A equal to `entry_score_0_100`.

- [ ] **Step 3: Write failing tests for exact Variant B**

Test eligibility:

```text
entry_score_0_100 >= 70
OR (hp_production_extension = true AND hp_LLM_best = true AND entry_score_0_100 >= 60)
```

Test rank score:

```text
hc_score = entry_score_0_100
         + 8 if hp_LLM_best
         + 8 if hp_production_extension and hp_LLM_best
         - 5 if risk_penalty_score >= 15
```

Use synthetic rows where a 60-score HP+LLM row enters, and a 59-score HP+LLM row does not.

- [ ] **Step 4: Implement exact Variant B**

Add a deterministic `_variant_b_score(row)` and `_variant_b_eligible(row)` helper. Sort by:

```text
hc_score desc, entry_score_0_100 desc, ticker asc
```

- [ ] **Step 5: Write failing tests for exact Variant C**

Test eligibility paths:

```text
entry_score_0_100 >= 70
OR HP production + HP LLM best + score >= 60
OR repricing_momentum_priority AND (market_repricing_score >= 14 OR rm_buy_review_flag)
OR theme_acceleration_research_visibility OR akg_universe_tier == T5_RESCAN
```

Test macro restriction:

```text
macro_entry_action in ["no_new_buy", "watchlist_only"] blocks v2 eligibility when present
```

Test rank score:

```text
hc_score = entry_score_0_100
         + 8  if hp_LLM_best
         + 8  if hp_production_extension and hp_LLM_best
         + 8  if repricing_momentum_priority
         + 6  if market_repricing_score >= 14
         + 6  if theme_acceleration_research_visibility
         + 4  if akg_universe_tier == "T5_RESCAN"
         - 5  if risk_penalty_score >= 15
         - 10 if post_llm_demote_flag = 1
```

- [ ] **Step 6: Implement exact Variant C**

Add `_variant_c_score(row)` and `_variant_c_eligible(row)`. Macro restriction scope is global for Variant C: compute the normal v2 eligibility paths first, then exclude the row from v2 if a present `macro_entry_action` is `no_new_buy` or `watchlist_only`, regardless of which eligibility path admitted it. Preserve blank macro behavior:

- If `macro_entry_action` is blank/missing: do not block.
- If `macro_entry_action` is `no_new_buy` or `watchlist_only`: block all v2 eligibility paths.

- [ ] **Step 7: Enforce strict selection feature allowlist**

Ensure selection code only uses `SELECTION_FEATURE_COLUMNS` from `pit_panel.py` and local formula fields drawn from that allowlist. Never pass or read these for selection:

```text
return_10d_pct
return_20d_pct
return_30d_pct
return_60d_pct
return_90d_pct
winner_90d_30pct
loser_90d_minus30pct
monitoring_score_0_100
active_monitoring_score_0_100
final_rank_score_0_100
rank_score_0_100
current_return_pct
return_since_signal_pct
return_since_purchase_pct
```

Add a manifest field:

```json
"selection_forbidden_columns": [...]
```

and a guardrail assertion that the used selection columns do not overlap forbidden columns.

- [ ] **Step 8: Run tests and commit**

Run:

```bash
PYTHONPATH=. /Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m pytest tests/test_fundamental_high_conviction_top10_backtest.py -q
```

Expected: all Task 1 tests pass.

Commit:

```bash
git add tradingagents/research/fundamental/backtests/high_conviction_top10.py tests/test_fundamental_high_conviction_top10_backtest.py
git commit -m "fix: align fundamental top10 backtest formulas"
```

---

## Task 2: Validate PIT panel exporter against transferred historical CSV

**Files:**
- Modify only if needed: `tradingagents/research/fundamental/backtests/pit_panel.py`
- Test: `tests/test_fundamental_pit_panel.py`

- [ ] **Step 1: Add/update PIT fixture test for required columns**

Test that the generated panel includes every required selection, label, and audit column listed in the analyst requirements.

- [ ] **Step 2: Add/update missing-field manifest test**

Use fixture input missing the theme/macro fields and assert:

- Panel still contains blank columns.
- `run_manifest.json` records those fields under missing selection fields.
- README says missing PIT-unproven theme/macro columns are blank/diagnostic.

- [ ] **Step 3: Add/update label separation test**

Assert:

- `feature_schema.json` excludes return labels.
- `label_schema.json` includes return labels.
- `winner_90d_30pct` and `loser_90d_minus30pct` derive only from `return_90d_pct`.

- [ ] **Step 4: Run tests and commit if code changed**

Run:

```bash
PYTHONPATH=. /Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m pytest tests/test_fundamental_pit_panel.py -q
```

If only tests changed:

```bash
git add tests/test_fundamental_pit_panel.py
git commit -m "test: lock fundamental PIT panel contract"
```

If code changed, include `pit_panel.py` in the commit.

---

## Task 3: Run full generation from historical source

**Files generated only:**
- `outputs/fundamental_backtest/*`

- [ ] **Step 1: Audit transferred source before generation**

Run a preflight audit over the source CSV and write results into the handoff notes/manifest:

```text
row_count
ticker_count
quarter_count
observed_quarter_min
observed_quarter_max
non_empty_return_90d_pct_count
duplicate_quarter_ticker_count
missing_required_source_columns
```

Execution may proceed only if:

```text
row_count == 22304
ticker_count == 1279
quarter_count == 19
non_empty_return_90d_pct_count == 21182
duplicate_quarter_ticker_count == 0
```

If observed quarter max is still `2026Q2`, record the filename mismatch (`2021Q4_2026Q1_partial`) as a provenance caveat and include all observed rows.

- [ ] **Step 2: Remove stale generated outputs**

```bash
rm -rf outputs/fundamental_backtest
```

- [ ] **Step 3: Generate PIT panel**

```bash
PYTHONPATH=. /Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m tradingagents.research.fundamental.backtests.pit_panel \
  tradingagents/research/fundamental/Growth/earnings_8k_sec_parser/combined_all_tiers_hp_extensions_llm_rank_scores_2021Q4_2026Q1_partial.csv \
  --output-dir outputs/fundamental_backtest \
  --as-of-date 2026-05-11 \
  --pipeline-run-id historical-combined-observed-2021Q4-2026Q2
```

Expected minimum checks:

```text
row_count = 22304
eligible_for_backtest True > 20000
non-empty return_90d_pct > 21000
quarter_count = 19 total, 18+ eligible quarters
```

- [ ] **Step 4: Generate Top-10 backtest outputs**

```bash
PYTHONPATH=. /Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m tradingagents.research.fundamental.backtests.high_conviction_top10 \
  outputs/fundamental_backtest/pit_fundamental_panel.csv \
  --output-dir outputs/fundamental_backtest/high_conviction_top10 \
  --run-id high-conviction-top10-observed-2021Q4-2026Q2
```

Expected minimum checks:

```text
selected_names_by_quarter.csv exists
strategy_by_quarter.csv exists
strategy_summary.csv exists
variant_summary.csv exists
misses_analysis.csv exists
theme_bucket_summary.csv exists
rm_hp_tier_contribution.csv exists
pick_count > 0
variant names exactly:
  entry_score_top10
  high_conviction_top10_v1
  high_conviction_top10_v2_final
```

- [ ] **Step 5: Create handoff manifest and optional zip**

Create:

- `outputs/fundamental_backtest/HANDOFF_MANIFEST.json`
- `outputs/fundamental_backtest/ANALYST_README.md`
- optional: `outputs/fundamental_backtest/aeternus_fundamental_backtest_bundle_observed_2021Q4_2026Q2.zip` if the preflight confirms the current source still contains `2026Q2`; otherwise use the audited observed range.

Manifest must include:

- source input path and SHA256
- output file paths and SHA256
- row counts
- eligible row counts
- variant pick counts
- missing PIT fields
- explicit warning: outcome labels are diagnostic only and excluded from selection

---

## Task 4: Run validation suite and data QA

**Files:**
- No source changes unless QA fails.

- [ ] **Step 1: Verify required live-scoring parity tests exist and pass**

Before artifact handoff, confirm these exact behaviors are covered by tests:

```text
HP candidates receive hp_structure_score and total_structure_score in live entry scoring.
RM candidates receive market_repricing_score before live entry scoring.
RM4 uses prior_entry_qoq_pct plus current entry_qoq_pct.
ENTRY_SCORE_FORBIDDEN_COLUMNS strips return labels, return_since_* fields, and monitoring scores.
```

Expected tests/files:

```text
tests/test_fundamental_live_scoring_parity.py
tests/test_rm_live_feature_flow.py
```

- [ ] **Step 2: Run focused tests**

```bash
PYTHONPATH=tradingagents/research/fundamental:. /Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m pytest \
  tests/test_fundamental_live_scoring_parity.py \
  tests/test_rm_live_feature_flow.py \
  tests/test_fundamental_pit_panel.py \
  tests/test_fundamental_high_conviction_top10_backtest.py \
  tests/test_fundamental_high_conviction_top10.py \
  tests/test_cli_fundamental_top10.py \
  tradingagents/research/fundamental/tests/test_tier_rules.py \
  -q
```

Expected: pass.

- [ ] **Step 3: Run generated-artifact QA script**

Use a small one-off Python check or add a reusable test that asserts:

```text
pit_fundamental_panel.csv row_count == 22304
ticker_count == 1279
quarter_count == 19
non_empty_return_90d_pct_count == 21182
observed_quarter_min == 2021Q4
observed_quarter_max is recorded from the data and reconciled with the source filename caveat
required PIT columns all present
no duplicate quarter/ticker rows
return labels present
winner/loser labels match return_90d_pct
selection feature schema has no return columns
selection feature schema has no monitoring_score_0_100/final_rank_score_0_100
all requested Top-10 CSVs exist
all three variants present
selected_names_by_quarter has pick_count > 0
v2 output has pick_count > 0
```

- [ ] **Step 4: Inspect variant summaries**

Record in final response:

```text
PIT rows
eligible rows
quarters covered
selected rows per variant
missing PIT fields
paths to requested files
```

---

## Task 5: Analyst handoff

**Required file paths to return to analyst model:**

```text
outputs/fundamental_backtest/pit_fundamental_panel.csv
outputs/fundamental_backtest/high_conviction_top10/strategy_summary.csv
outputs/fundamental_backtest/high_conviction_top10/variant_summary.csv
outputs/fundamental_backtest/high_conviction_top10/strategy_by_quarter.csv
outputs/fundamental_backtest/high_conviction_top10/selected_names_by_quarter.csv
outputs/fundamental_backtest/high_conviction_top10/misses_analysis.csv
outputs/fundamental_backtest/high_conviction_top10/rm_hp_tier_contribution.csv
outputs/fundamental_backtest/high_conviction_top10/theme_bucket_summary.csv
```

Also include these supporting files because they prevent analyst ambiguity:

```text
outputs/fundamental_backtest/feature_schema.json
outputs/fundamental_backtest/label_schema.json
outputs/fundamental_backtest/run_manifest.json
outputs/fundamental_backtest/README_ANALYSIS.md
outputs/fundamental_backtest/HANDOFF_MANIFEST.json
outputs/fundamental_backtest/ANALYST_README.md
outputs/fundamental_backtest/high_conviction_top10/run_manifest.json
outputs/fundamental_backtest/high_conviction_top10/README_ANALYSIS.md
```

Final response must state:

- exact source CSV used
- exact generated output root
- PIT row/eligible counts
- variant pick counts
- missing PIT fields retained blank
- test command and result
- that labels/monitoring/final-rank fields are excluded from selection

---

## Non-Negotiable Guardrails

- Do not change broad framework rules.
- Do not create a duplicate discovery/Pipeline 0 architecture.
- Do not use return labels, monitoring scores, or final rank scores in selection.
- Do not merge current AKG/theme/macro state into historical rows unless point-in-time proof exists.
- Do not commit large generated outputs unless explicitly requested.
- Keep implementation deterministic: no random ordering, no wall-clock-dependent ranking.
- Prefer blank diagnostic fields over forward-filled non-PIT theme/macro data.
