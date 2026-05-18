# PIT Reconciliation Independent Audit Plan

Purpose: give another model a clean, evidence-first plan to independently verify why the uploaded historical combined CSV and generated PIT master CSV do not match.

Do not fix code during this audit. First prove root cause.

Current generated PIT master status:

- Invalid for historical validation.
- Reason: financial values are not PIT-safe.
- Machine-readable status: `/Users/aeternusholdings/Documents/Aeternus/outputs/fundamental_backtest/pit_master/reconciliation_status.json`
- Plain notice: `/Users/aeternusholdings/Documents/Aeternus/tradingagents/research/fundamental/docs/current_pit_master_invalid_notice.md`

## Audit Question

For the same `quarter + ticker`, should generated values match the uploaded historical combined file?

Answer to verify:

- If the rule and inputs are the same, yes.
- If rule/input changed, mismatch is allowed only when the change is clearly documented.
- If future data leaked into old quarters, generated historical rows are wrong.

## Primary Files

Uploaded historical reference:

- `/Users/aeternusholdings/Downloads/combined_all_tiers_hp_extensions_llm_rank_scores_2021Q4_2026Q1_partial.csv`

Generated PIT outputs:

- `/Users/aeternusholdings/Documents/Aeternus/outputs/fundamental_backtest/pit_master/fundamental_pit_master.csv`
- `/Users/aeternusholdings/Documents/Aeternus/outputs/fundamental_backtest/pit_master/fundamental_pit_master_clean.csv`

Generated audit files:

- `/Users/aeternusholdings/Documents/Aeternus/outputs/fundamental_backtest/pit_master/reconciliation_audit/quarter_reconciliation_summary.csv`
- `/Users/aeternusholdings/Documents/Aeternus/outputs/fundamental_backtest/pit_master/reconciliation_audit/quarter_reconciliation_grouped.csv`
- `/Users/aeternusholdings/Documents/Aeternus/outputs/fundamental_backtest/pit_master/reconciliation_audit/quarter_reconciliation_examples.csv`
- `/Users/aeternusholdings/Documents/Aeternus/outputs/fundamental_backtest/pit_master/reconciliation_audit/quarter_reconciliation_key_diffs.csv`
- `/Users/aeternusholdings/Documents/Aeternus/outputs/fundamental_backtest/pit_master/reconciliation_audit/column_presence_blank_diagnostic.csv`
- `/Users/aeternusholdings/Documents/Aeternus/outputs/fundamental_backtest/pit_master/attached_vs_generated_compare_summary.csv`

Historical repo files that may be useful:

- `/Users/aeternusholdings/Documents/Aeternus/tradingagents/research/fundamental/Growth/earnings_8k_sec_parser/pre_llm_fundamental_score_2021Q4_2026Q1_partial.csv`
- `/Users/aeternusholdings/Documents/Aeternus/tradingagents/research/fundamental/Growth/earnings_8k_sec_parser/pre_llm_fundamental_score_2022Q1.csv`
- `/Users/aeternusholdings/Documents/Aeternus/tradingagents/research/fundamental/Growth/earnings_8k_sec_parser/combined_all_tiers_hp_extensions_llm_rank_scores_2021Q4_2026Q1_partial.csv`

Example generated run:

- `/Users/aeternusholdings/Documents/Aeternus/tradingagents/research/fundamental/runs/2022-03-31/2022Q1/walkforward_clean_v1/fundamental_final_scores_2022-03-31.csv`
- `/Users/aeternusholdings/Documents/Aeternus/tradingagents/research/fundamental/runs/2022-03-31/2022Q1/walkforward_clean_v1/complete_panel/fundamental_complete_prellm_to_top15_2022Q1.csv`

SEC fact example:

- `/Users/aeternusholdings/Documents/GitHub/AeternusHoldings/cache/sec/facts_A.json`

## Code Paths To Audit

SEC facts selection:

- `/Users/aeternusholdings/Documents/Aeternus/tradingagents/research/fundamental/src/ingest/xbrl.py:16`
- `/Users/aeternusholdings/Documents/Aeternus/tradingagents/research/fundamental/src/ingest/xbrl.py:32`
- `/Users/aeternusholdings/Documents/Aeternus/tradingagents/research/fundamental/src/daily_run/scoring_inputs.py:87`
- `/Users/aeternusholdings/Documents/Aeternus/tradingagents/research/fundamental/src/daily_run/scoring_inputs.py:111`

Decision date and entry price:

- `/Users/aeternusholdings/Documents/Aeternus/tradingagents/research/fundamental/src/daily_run/scoring_inputs.py:46`
- `/Users/aeternusholdings/Documents/Aeternus/tradingagents/research/fundamental/src/daily_run/scoring_inputs.py:152`
- `/Users/aeternusholdings/Documents/Aeternus/tradingagents/research/fundamental/Growth/build_pre_llm_fundamental_score.py:206`

QoQ context:

- `/Users/aeternusholdings/Documents/Aeternus/tradingagents/research/fundamental/src/daily_run/finalize.py:64`

Final score calculation:

- `/Users/aeternusholdings/Documents/Aeternus/tradingagents/research/fundamental/src/features/scoring.py:209`
- `/Users/aeternusholdings/Documents/Aeternus/tradingagents/research/fundamental/src/pipeline/run_on_new_filing.py:145`
- `/Users/aeternusholdings/Documents/Aeternus/tradingagents/research/fundamental/Growth/build_rank_scores.py:411`

LLM status and fields:

- `/Users/aeternusholdings/Documents/Aeternus/tradingagents/research/fundamental/src/features/post_llm_scores.py:8`
- `/Users/aeternusholdings/Documents/Aeternus/tradingagents/research/fundamental/src/features/post_llm_scores.py:42`

Panel schema / blank columns:

- `/Users/aeternusholdings/Documents/Aeternus/tradingagents/research/fundamental/src/panel/schema.py:253`
- `/Users/aeternusholdings/Documents/Aeternus/tradingagents/research/fundamental/src/panel/schema.py:262`

## Known Evidence From First Pass

File shape:

- Uploaded file: `21,994` rows, `117` columns, quarters `2021Q4` through `2026Q1`.
- Generated clean file: `22,025` rows, `271` columns, quarters `2022Q1` through `2026Q2`.
- Shared `quarter + ticker` rows: `20,176`.
- Old-only rows: `1,818`.
- New-only rows: `1,849`.

Major mismatch counts:

- `tradable_date`: mismatches in most shared rows.
- `pre_llm_fundamental_score`: `16,344` mismatches.
- `entry_score_0_100`: `14,067` mismatches.
- `score_change`: `12,927` mismatches.
- `entry_open`: `11,175` mismatches.
- Generated `return_10d_pct`, `return_20d_pct`, `return_30d_pct`, `return_60d_pct`, `return_90d_pct`: blank for all rows.
- Generated `base_entry_raw_score`, `base_entry_score_0_100`, `monitoring_score_0_100`, `final_rank_score_0_100`, `rank_score_label`: blank for all rows.

Example `2022Q1 A`:

- Uploaded: `tradable_date=2/23/22`, `entry_open=129.880005`, `pre_llm_fundamental_score=5`, `entry_score_0_100=6`, `revenue_bucket=$2B-$10B`.
- Generated: `tradable_date=2022-03-04`, `entry_open=135.85000610351562`, `pre_llm_fundamental_score=7`, `entry_score_0_100=3`, `revenue_bucket=$1B-$2B`.
- Generated source row has earnings 8-K date `2022-02-22` and 10-Q date `2022-03-03`.
- Generated tradable date is first trading day after the later 10-Q date.

Example `2022Q1 ARLO`:

- Uploaded: `tradable_date=3/2/22`, `entry_open=9.99`, `pre_llm_fundamental_score=-2`, `entry_score_0_100=85`.
- Generated: `tradable_date=2022-03-03`, `entry_open=11.050000190734863`, `pre_llm_fundamental_score=7`, `entry_score_0_100=72`.

Example `2026Q1 NVDA`:

- Uploaded: `has_post_llm=1`, `sample_id=HP002273`, `causal_change=2`, `negative_revision_risk=1`, `post_llm_fundamental_score=11`.
- Generated: `has_post_llm=1`, `sample_id=NVDA_2026Q1`, `causal_change=3.0`, `negative_revision_risk=1.0`, `post_llm_fundamental_score` blank.

## Hypotheses To Verify

### Hypothesis 1: Generated historical financial values are not truly PIT

Plain claim:

- Generated file may use later SEC CompanyFacts values when scoring old quarters.

Evidence to verify:

- `latest_fact_value()` chooses the newest fact unless an `end` cutoff is passed.
- `build_pre_llm_from_companyfacts_cache()` calls `companyfacts_to_pre_llm_input()` without passing quarter end.
- For old quarters, the SEC facts file contains many years of facts.

Audit steps:

- Pick `2022Q1 A`, `2022Q1 AAP`, `2022Q1 ARLO`, and 10 random mismatched tickers per quarter.
- For each generated financial value, locate the exact SEC fact item used.
- Record `start`, `end`, `fy`, `fp`, `form`, `filed`, and `val`.
- Compare fact `end` and `filed` against the intended quarter and decision date.
- If a generated `2022Q1` row uses a fact ending after `2022Q1`, fail PIT.

Pass condition:

- Every financial value used for a quarter is from an allowed period and was available by that row’s decision date.

Fail condition:

- Any old-quarter generated row uses a later-period fact.

### Hypothesis 2: Decision date rule changed

Plain claim:

- Uploaded historical file appears to use first trading day after earnings 8-K / press release.
- Generated PIT file uses first trading day after both earnings 8-K and 10-Q/K are available.

Code evidence:

- `derive_tradable_date_from_coverage()` takes the max of earnings 8-K date and periodic filing date, then next weekday.
- Historical builder `return_fields()` takes a filing/event date and uses first available trading day after that.

Audit steps:

- For each quarter, compare uploaded `tradable_date` to:
  - first trading day after earnings 8-K / press release
  - first trading day after 10-Q/K
  - first trading day after later of both
- Count which rule matches uploaded and which rule matches generated.

Important:

- This may be an intended rule change, not necessarily a bug.
- If official framework requires both filings before final scoring, generated date rule may be right.
- If historical backtest should match old combined file, uploaded date rule must be reproduced or explicitly marked as a rule change.

### Hypothesis 3: Generated file omitted return checkpoints

Plain claim:

- Uploaded file has future return columns.
- Generated PIT clean file leaves them blank.

Audit steps:

- Confirm generated `return_10d_pct`, `return_20d_pct`, `return_30d_pct`, `return_60d_pct`, `return_90d_pct` are blank.
- Trace whether daily run intentionally avoids returns for live safety.
- Decide whether master historical CSV should include returns only for backtest rows and blank for live rows.

Pass condition:

- Historical rows have backtest returns populated from raw Yahoo price cache.
- Live incomplete quarter rows are clearly blank or flagged as partial.

### Hypothesis 4: Generated file omitted legacy score aliases

Plain claim:

- Generated file has real score fields, but leaves old alias fields blank.

Fields:

- `base_entry_raw_score`
- `base_entry_score_0_100`
- `monitoring_score_0_100`
- `final_rank_score_0_100`
- `rank_score_label`
- `hp_adjusted_raw_score`
- `hp_adjusted_entry_score`

Evidence:

- Legacy builder writes these fields in `build_rank_scores.py`.
- Current scoring path writes `entry_raw_score`, `entry_score_0_100`, `dashboard_score_0_100`, but not all legacy aliases.

Audit steps:

- Decide whether these aliases are required output columns.
- If yes, verify formula mapping:
  - `base_entry_raw_score` should equal old base score, not blindly equal current `entry_raw_score`.
  - `final_rank_score_0_100` should reflect monitoring-adjusted score if returns are present.
  - `monitoring_score_0_100` cannot be trusted unless returns are present.

### Hypothesis 5: LLM values are not preserved consistently

Plain claim:

- Some old LLM-derived values differ from generated values.

Evidence:

- `NVDA 2026Q1` changed `causal_change` from `2` to `3.0`.
- `post_llm_fundamental_score` exists in uploaded file but is blank in generated file.

Audit steps:

- Compare old and generated LLM cache source for all rows where both have `has_post_llm=1`.
- Check whether generated is using a new extraction, old extraction, or derived normalized fields.
- For each mismatch, classify:
  - true re-extraction difference
  - old field no longer carried forward
  - blank because current schema dropped field
  - expected rule change

Pass condition:

- Same packet and same model output should produce same LLM fields.
- If field was intentionally dropped, output contract must say so.

### Hypothesis 6: Universe changed

Plain claim:

- Uploaded and generated files do not contain the same tickers per quarter.

Evidence:

- Key diffs exist every quarter.
- Example `2022Q1`: old-only `27`, new-only `39`.
- Full samples in `quarter_reconciliation_key_diffs.csv`.

Audit steps:

- For each old-only ticker, identify whether generated excluded it because:
  - no SEC filer
  - no required filings
  - no price data
  - universe start list changed
  - ticker mapping changed
  - bug
- For each new-only ticker, identify whether uploaded omitted it because:
  - old universe was incomplete
  - added dealflow name
  - new universe rule
  - bug

Pass condition:

- Every key difference has a clear reason.

## Quarter-By-Quarter Audit Procedure

Do this in order:

1. Start with `2022Q1`, because it has full mismatch and clear examples.
2. Reconcile `2022Q1 A`, `AAP`, and `ARLO` manually from source files.
3. Confirm whether the same root cause explains at least 20 random `2022Q1` mismatches.
4. Move quarter by quarter through `2026Q1`.
5. For each quarter, classify mismatch share into:
   - financial value mismatch
   - tradable date / entry price mismatch
   - QoQ context mismatch
   - LLM mismatch
   - score alias blank
   - return blank
   - universe difference
6. Do not accept generated PIT master until every quarter has an explanation.

## Required Outputs From Independent Auditor

The independent auditor should produce:

- One summary stating which file is correct for historical score matching.
- One root-cause list with proof.
- One quarter-by-quarter mismatch summary.
- One sample evidence sheet with at least 5 tickers per quarter.
- One recommended fix plan.
- One list of assumptions that need user approval.

## Acceptance Criteria

Generated historical PIT master can be trusted only if:

- No old quarter uses future financial facts.
- Decision-date rule is explicitly chosen and consistently applied.
- Price and return fields are either populated or intentionally blank with clear flags.
- Score aliases are populated or removed from required output.
- Same LLM packet/source produces same LLM fields, or differences are documented.
- Universe adds/removes are explained per ticker.
- Reconciliation report is generated every time the master PIT CSV is built.
