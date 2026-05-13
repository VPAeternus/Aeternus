# High-Conviction Top-10 Observed-Data Backtest

## Bottom line

The committed bundle is valid for a better observed-data Top-10 backtest analysis. It is not a full live AKG+macro production v2 validation because AKG theme acceleration and macro fields are blank/missing in the PIT panel.

Core counts reconciled from the committed artifacts:

- PIT panel rows: `22,304`
- Eligible backtest rows: `21,182`
- Selected rows: `519`
- Variants: `3`
- Picks per variant: `{'entry_score_top10': 173, 'high_conviction_top10_v1': 173, 'high_conviction_top10_v2_final': 173}`
- Observed quarters: `2021Q4` through `2026Q2`

## QA / leakage verification

QA status: `PASS`.

- Outcome labels are diagnostic only: `forbidden_selection_overlap=[]` and `outcome_labels_in_selection_features=[]`.
- Monitoring/final-rank/current-return fields are excluded from selection: `monitoring_final_rank_fields_in_selection_features=[]`; forbidden set `['active_monitoring_score_0_100', 'current_return_pct', 'final_rank_score_0_100', 'monitoring_score_0_100', 'rank_score_0_100', 'return_since_purchase_pct', 'return_since_signal_pct']`.
- Winner/loser labels reconcile to `return_90d_pct`: winner mismatches `0`, loser mismatches `0`.
- Duplicate ticker-quarter rows: `0`.
- Manifest hash failures: `0`.
- `selected_names_by_quarter.csv` duplicate headers: `[]`.
- `2026Q1` is partial/shortfall: `{'rows': 1255, 'eligible_rows': 134, 'selected_pick_counts': {'entry_score_top10': 3, 'high_conviction_top10_v1': 3, 'high_conviction_top10_v2_final': 3}, 'shortfall_by_variant': {'entry_score_top10': 'True', 'high_conviction_top10_v1': 'True', 'high_conviction_top10_v2_final': 'True'}}`.
- `2026Q2` is present in the source but not eligible for 90d backtest selection: `{'rows': 1, 'eligible_rows': 0, 'selected_pick_counts': {}}`.

Missing AKG/macro field availability:

| field | available | used_in_selection | interpretation |
| --- | --- | --- | --- |
| theme_acceleration_score | 0 | allowlisted_but_unavailable | Source-missing PIT field; retained blank/unavailable, not valid positive or negative evidence in this bundle. |
| theme_acceleration_research_visibility | 0 | allowlisted_but_unavailable | Source-missing PIT field; retained blank/unavailable, not valid positive or negative evidence in this bundle. |
| theme_acceleration_rescan_flag | 0 | allowlisted_but_unavailable | Source-missing PIT field; retained blank/unavailable, not valid positive or negative evidence in this bundle. |
| akg_universe_tier | 0 | allowlisted_but_unavailable | Source-missing PIT field; retained blank/unavailable, not valid positive or negative evidence in this bundle. |
| macro_mode | 0 | allowlisted_but_unavailable | Source-missing PIT field; retained blank/unavailable, not valid positive or negative evidence in this bundle. |
| macro_spy | 0 | allowlisted_but_unavailable | Source-missing PIT field; retained blank/unavailable, not valid positive or negative evidence in this bundle. |
| macro_entry_action | 0 | allowlisted_but_unavailable | Source-missing PIT field; retained blank/unavailable, not valid positive or negative evidence in this bundle. |
| macro_position_size_multiplier | 0 | allowlisted_but_unavailable | Source-missing PIT field; retained blank/unavailable, not valid positive or negative evidence in this bundle. |

## Variant interpretation matrix

| variant | tests | does_not_test |
| --- | --- | --- |
| entry_score_top10 | Raw entry-score Top-10 among eligible rows with entry_score_0_100 >= 70. | HP override, RM override, AKG theme acceleration override, T5_RESCAN override, and macro blocking. |
| high_conviction_top10_v1 | Entry-score baseline plus HP production+LLM override and HP/risk-penalty high-conviction score adjustments. | RM override, AKG theme acceleration/T5_RESCAN override, and macro blocking. |
| high_conviction_top10_v2_final | Observed v2 columns: v1 plus RM/repricing priority and market repricing boosts, post-LLM demote penalty, and macro-block logic if populated. | Full live AKG+macro production v2, because theme acceleration, AKG tier, and macro fields are blank/missing in this PIT panel. |

## Main strategy result

| variant | picks | avg_90d | +30_hit | -30_loser |
| --- | --- | --- | --- | --- |
| entry_score_top10 | 173 | 15.26% | 25.19% | 6.11% |
| high_conviction_top10_v1 | 173 | 15.49% | 26.85% | 7.22% |
| high_conviction_top10_v2_final | 173 | 15.50% | 26.85% | 7.22% |

Read-through: high-conviction v1/v2 improve the +30% hit rate versus raw entry-score Top-10, but with a higher -30% loser rate. v2 does not materially beat v1 in this bundle because the fields that make v2 uniquely AKG/macro-aware are unavailable.

## Quarter-by-quarter read

Strong v2 quarters:

| quarter | avg_90d | +30_hit |
| --- | --- | --- |
| 2025Q3 | 50.32% | 40.00% |
| 2023Q4 | 35.15% | 50.00% |
| 2022Q4 | 23.95% | 30.00% |
| 2024Q3 | 23.21% | 40.00% |

Weak v2 quarters:

| quarter | avg_90d | -30_loser |
| --- | --- | --- |
| 2025Q1 | -15.93% | 20.00% |
| 2024Q2 | -3.36% | 0.00% |
| 2022Q1 | -3.06% | 10.00% |

The 2025Q1 drawdown remains the clearest case for macro permission / risk-on filtering. This bundle cannot measure that protection because macro fields are blank.

## RM contribution

| rm_signal_bucket | picks | avg_90d | +30_hit | -30_loser |
| --- | --- | --- | --- | --- |
| 0 | 81 | 6.40% | 18.52% | 7.41% |
| 1 | 36 | 45.69% | 58.33% | 2.78% |
| 2+ | 56 | 8.87% | 17.86% | 10.71% |

Observed result: the strongest bucket is the single-RM-signal bucket, labeled `rm_signal_bucket=1`. This is not necessarily the literal `rm1_low_price_dislocation_momentum` rule; it means exactly one RM-related signal was active. The `rm_signal_bucket=2+` multi-RM-signal bucket is weaker and has higher left-tail risk than the single-signal bucket. Treat this as a routing/manual-underwriting signal, not proof that one causal mechanism explains returns.

## HP contribution

| hp_bucket | picks | avg_90d | +30_hit | -30_loser |
| --- | --- | --- | --- | --- |
| 0 | 121 | 15.18% | 24.79% | 5.79% |
| 2+ | 52 | 15.84% | 30.77% | 11.54% |

HP improves +30% capture in v2, but also increases the -30% loser rate. HP candidates need valuation/current-price and risk discipline.

## Theme caveat

For `high_conviction_top10_v2_final`, `UNKNOWN` accounts for `158` of `173` picks. Named-theme rows are small-sample and directional only:

| theme | picks | avg_90d |
| --- | --- | --- |
| Flexible power infrastructure for HPC and bitcoin mining | 1 | 337.70% |
| datacenter optical network transition | 1 | 103.34% |
| hyperscale 400G optical ramp | 1 | 99.28% |
| AI memory and storage acceleration | 1 | 79.99% |
| 800G and CATV demand ramp | 1 | 63.35% |

The real theme acceleration module still needs PIT-populated fields before production claims are justified.

## Missed right-tail mechanical exclusions

These rows are mechanical exclusions, not proof of why the stock moved or proof the framework should have bought them.

| right_tail_bucket | mechanical_exclusion_category | count |
| --- | --- | --- |
| 2x_to_5x | eligible_but_ranked_below_top10 | 9 |
| 2x_to_5x | not_variant_eligible | 74 |
| 5x_to_10x | not_variant_eligible | 2 |

See `tradingagents/research/fundamental/runs/backtests/analysis/missed_right_tail_mechanical_exclusions.csv` for ticker-level rows.

## Live-use recommendation from observed data

For live use today: use `high_conviction_top10_v2_final` as the operating setting, but treat it as observed-data v2, not fully validated AKG+macro v2.

Operationally:

1. Run broad discovery / source Top-30.
2. Deep-analyze selected names.
3. Use portfolio max positions = 10.
4. Prioritize single-RM-signal bucket candidates.
5. Be more cautious with RM 2+ unless LLM/theme/valuation evidence is very strong.
6. Treat HP names as useful but higher-left-tail-risk.
7. Apply macro permission manually/live until PIT macro fields are historically validated.
8. Continue forward-validating AKG theme acceleration / T5_RESCAN because historical PIT fields are blank.

The package gives enough support to make this recommendation, while correctly avoiding the unsupported claim that full AKG+macro production v2 is historically validated. `rm_signal_bucket=1` means exactly one RM-related signal was active; it is not necessarily the literal RM1 rule.

## Daily framework output

After the dealflow framework has finalized the day's ticker handoff and the fundamental framework has produced final scores, run:

```bash
python3 -m cli.main fundamental-top10 \
  --scores-csv tradingagents/research/fundamental/runs/YYYY-MM-DD/selection/fundamental_final_scores_YYYY-MM-DD.csv \
  --output-root tradingagents/research/fundamental/runs/YYYY-MM-DD/selection \
  --date YYYY-MM-DD \
  --top-n 10
```

Daily outputs:

- `tradingagents/research/fundamental/runs/YYYY-MM-DD/selection/high_conviction_top10.csv`
- `tradingagents/research/fundamental/runs/YYYY-MM-DD/selection/high_conviction_top10.json`
- `tradingagents/research/fundamental/runs/YYYY-MM-DD/selection/high_conviction_top10_daily_recommendation.md`

The daily recommendation artifact carries the observed-data v2 label, portfolio max positions = 10, single-RM-signal priority, RM 2+/HP caution flags, manual macro permission caveat, and AKG/T5 forward-validation caveat.

## Next test: Top-15 exception sleeve

The next observed-data extension is the Top-15 right-tail exception sleeve: 10 core high-conviction names plus up to 5 right-tail exception research/starter-underwriting names. Top-10 remains the core buy-underwriting sleeve. Exception names are not automatic equal-weight buys.

Implementation/analysis artifacts:

- `tradingagents/research/fundamental/docs/top15_exception_sleeve_implementation_plan.md`
- `tradingagents/research/fundamental/docs/top15_exception_sleeve_observed_backtest_analysis.md`
- `tradingagents/research/fundamental/runs/backtests/high_conviction_top15_exception_sleeve/`
- `tradingagents/research/fundamental/runs/backtests/analysis_top15_exception/`

## Future validation required before claiming full v2

Before claiming full live AKG+macro production v2 validation, populate or forward-test these PIT fields: `theme_acceleration_score`, `theme_acceleration_research_visibility`, `theme_acceleration_rescan_flag`, `akg_universe_tier`, `macro_mode`, `macro_spy`, `macro_entry_action`, and `macro_position_size_multiplier`.

## Companion outputs

- `tradingagents/research/fundamental/runs/backtests/analysis/field_availability_audit.csv`
- `tradingagents/research/fundamental/runs/backtests/analysis/variant_interpretation_matrix.csv`
- `tradingagents/research/fundamental/runs/backtests/analysis/rm1_vs_rm2plus_drivers.csv` (legacy filename; rows use `rm_signal_bucket`, where `1` means one RM-related signal active, not necessarily the literal RM1 rule)
- `tradingagents/research/fundamental/runs/backtests/analysis/hp_bucket_tail_risk_analysis.csv`
- `tradingagents/research/fundamental/runs/backtests/analysis/variant_overlap_delta_by_quarter.csv`
- `tradingagents/research/fundamental/runs/backtests/analysis/top_winners_losers_repeat_ticker_contribution.csv`
- `tradingagents/research/fundamental/runs/backtests/analysis/2025Q1_drawdown_attribution.csv`
- `tradingagents/research/fundamental/runs/backtests/analysis/missed_right_tail_mechanical_exclusions.csv`
- `tradingagents/research/fundamental/runs/backtests/analysis/qa_leakage_verification.json`
- `tradingagents/research/fundamental/runs/backtests/analysis/analysis_manifest.json`
