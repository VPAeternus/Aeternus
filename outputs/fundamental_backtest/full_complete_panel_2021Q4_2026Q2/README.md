# Fundamental Complete Panel 2021Q4-2026Q2

Refreshed `2026-05-16` from the latest validated `2026-05-15` daily run.

Main CSV: `outputs/fundamental_backtest/full_complete_panel_2021Q4_2026Q2/fundamental_complete_prellm_to_top15_2021Q4_2026Q2.csv`
Manifest: `outputs/fundamental_backtest/full_complete_panel_2021Q4_2026Q2/fundamental_complete_prellm_to_top15_2021Q4_2026Q2_manifest.json`
Columns: `outputs/fundamental_backtest/full_complete_panel_2021Q4_2026Q2/fundamental_complete_prellm_to_top15_2021Q4_2026Q2_columns.json`
Validation: `outputs/fundamental_backtest/full_complete_panel_2021Q4_2026Q2/fundamental_complete_prellm_to_top15_2021Q4_2026Q2_validation.json`

Rows: `23619`. Columns: `330`.

Build notes:
- Historical rows use the canonical `2021Q4` through `2026Q1` prior panel from `fundamental-history-complete-panel`.
- Current `2026Q2` rows come from `daily_postfile_prior_context_fix_v1/fundamental_final_scores_2026-05-15.csv`: `1316`.
- Validation passed: duplicate ticker-quarter rows `0`, full-panel Top15 selected `206`, full-panel shadow selected `272`. Current 2026Q2 selected counts remain `15` and `15`.
- The range-named file is a compatibility copy of the canonical `fundamental_complete_prellm_to_top15_2026Q2.csv` output.

## Fill V2

Generated `2026-05-13T10:55:43-04:00`.

Filled source-defensible blanks in the main CSV:
- `symbol`, `cik`, `company_title`
- `revenue_value`, `net_income_value`, `assets_value`
- `operating_cash_flow_value`, `investing_cash_flow_value`, `financing_cash_flow_value`
- historical `entry_open_date` and `entry_open_source`

Fill audit: `outputs/fundamental_backtest/full_complete_panel_2021Q4_2026Q2/fundamental_complete_prellm_to_top15_2021Q4_2026Q2_fill_audit.csv`
Fill summary: `outputs/fundamental_backtest/full_complete_panel_2021Q4_2026Q2/fundamental_complete_prellm_to_top15_2021Q4_2026Q2_fill_summary.json`

Remaining financial-value rows with any missing field after fill: `148`.
Output SHA256 after fill: `b40d5d33ae3d6222fc43eb7ee495be589ae8404dc6b6c3517be5339ca479068f`.

## Financial Value Fill V3

Applied extended cached-companyfacts fill on 2026-05-13 for partial raw financial blanks that remained after XBRL attachment. Strict as-of facts were used first; relaxed-filed-date facts are explicitly marked in `financial_values_source` when the only available SEC fact was filed later as a restated/comparative fact. Remaining rows with any raw financial blank: `7`. Output SHA256: `64aabc63f9ec40aaf23104e81c6de11b29c7c5b15317c1077c8fbafbcbce831d`.

## 2026Q2 Post-LLM Subtier Fill

Filled legacy `post_llm_tier_*_flag` columns for `2026Q2` from canonical current-run fields (`tier_1_bucket` through `tier_4_bucket`, `post_llm_candidate_flag`, `post_llm_high_priority_flag`, `causal_change`, `negative_revision_risk`, `narrative_delta_bucket`, and prior-quarter `score_addition`). Historical rows were left unchanged. Q2 rows with any derived subtier flag: `110`. Output SHA256: `517e17bdc87e8cf4b3160ad964a210bad6b671d95c45e63a843a5b0ab55f5d8d`.
