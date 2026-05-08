# Fundamental Backtest Analyst Handoff

## Source CSV

`tradingagents/research/fundamental/Growth/earnings_8k_sec_parser/combined_all_tiers_hp_extensions_llm_rank_scores_2021Q4_2026Q1_partial.csv`

SHA256: `d4e372fc03381721028e8c3bc98c3e12958c9110874736f434a70cc9f2b9975b`

Provenance caveat: filename says `2021Q4_2026Q1_partial`, but observed data spans `2021Q4` through `2026Q2`; all observed rows were included.

## Output files

- `outputs/fundamental_backtest/pit_fundamental_panel.csv`
- `outputs/fundamental_backtest/feature_schema.json`
- `outputs/fundamental_backtest/label_schema.json`
- `outputs/fundamental_backtest/run_manifest.json`
- `outputs/fundamental_backtest/README_ANALYSIS.md`
- `outputs/fundamental_backtest/HANDOFF_MANIFEST.json`
- `outputs/fundamental_backtest/ANALYST_README.md`
- `outputs/fundamental_backtest/high_conviction_top10/selected_names_by_quarter.csv`
- `outputs/fundamental_backtest/high_conviction_top10/strategy_by_quarter.csv`
- `outputs/fundamental_backtest/high_conviction_top10/strategy_summary.csv`
- `outputs/fundamental_backtest/high_conviction_top10/variant_summary.csv`
- `outputs/fundamental_backtest/high_conviction_top10/misses_analysis.csv`
- `outputs/fundamental_backtest/high_conviction_top10/theme_bucket_summary.csv`
- `outputs/fundamental_backtest/high_conviction_top10/rm_hp_tier_contribution.csv`
- `outputs/fundamental_backtest/high_conviction_top10/run_manifest.json`
- `outputs/fundamental_backtest/high_conviction_top10/README_ANALYSIS.md`

## Counts

- Source rows: 22,304
- Tickers: 1,279
- Quarters: 19
- Non-empty `return_90d_pct`: 21,182
- PIT panel rows: 22,304
- PIT eligible rows: 21,182
- Top-10 selected rows: 519

## Variant descriptions

- `entry_score_top10`: top 10 by PIT `entry_score_0_100`, minimum score 70.
- `high_conviction_top10_v1`: high-conviction formula v1 over PIT allowlisted features.
- `high_conviction_top10_v2_final`: final high-conviction formula v2 over PIT allowlisted features.

Variant pick counts:

- `entry_score_top10`: 173
- `high_conviction_top10_v1`: 173
- `high_conviction_top10_v2_final`: 173

## Missing PIT fields retained blank

Selection/PIT fields missing from source and retained blank:

- `theme_acceleration_score`
- `theme_acceleration_research_visibility`
- `theme_acceleration_rescan_flag`
- `akg_universe_tier`
- `macro_mode`
- `macro_spy`
- `macro_entry_action`
- `macro_position_size_multiplier`

Other missing source fields retained blank/diagnostic:

- Label: `is_partial_live_quarter`
- Metadata: `scoring_formula_version`, `tier_rule_version`, `hp_rule_version`, `rm_rule_version`, `theme_rule_version`, `macro_rule_version`

## No leakage warning

Return labels, monitoring scores, final score, and rank score are not used for selection. Outcome labels are diagnostic only and excluded from selection.
