# Fundamental Top-15 Exception Sleeve Observed Backtest Analysis

## Bottom line

The Top-15 exception sleeve improves observed average 90d return and +30% hit rate versus Top-10 v2 while keeping -30% loser rate roughly flat. It should be treated as a research/starter-underwriting queue, not 15 equal-weight buys.

Use remains disciplined:

- Top-10 core = primary buy-underwriting queue.
- Exception sleeve = right-tail research / starter-underwriting candidates.
- No claim of full AKG+macro production-v2 historical validation.

## Main comparison

| variant | picks | avg_90d | +30_hit | -30_loser | 2025Q1 |
| --- | --- | --- | --- | --- | --- |
| high_conviction_top10_v2_final | 173 | 15.50% | 26.85% | 7.22% | -15.93% |
| high_conviction_top15_v3_exception_sleeve | 191 | 17.28% | 28.89% | 7.22% | -16.89% |
| top15_conservative_10_core_3_exception | 182 | 16.29% | 27.83% | 6.97% | -16.89% |
| top15_rm1_priority_max2_rm2plus | 191 | 17.28% | 28.89% | 7.22% | -16.89% |

Main Top-15 v3 vs Top-10 v2:

- Avg 90d: `15.50%` -> `17.28%`
- +30% hit rate: `26.85%` -> `28.89%`
- -30% loser rate: `7.22%` -> `7.22%`
- 2025Q1 avg 90d: `-15.93%` -> `-16.89%`

## Core vs exception sleeve

For `high_conviction_top15_v3_exception_sleeve`, exception sleeve rows:

- Picks: `18`
- Avg 90d: `35.39%`
- +30% hit rate: `50.00%`
- -30% loser rate: `5.56%`

The exception sleeve is positive in this observed backtest, but sample size is small. It supports adding research slots, not auto-buying all exceptions.

## Adoption criteria check

| variant | criterion | value | passed |
| --- | --- | --- | --- |
| high_conviction_top15_v3_exception_sleeve | avg_90d_not_worse | 17.278760 | True |
| high_conviction_top15_v3_exception_sleeve | winner_rate_close_or_better | 0.288902 | True |
| high_conviction_top15_v3_exception_sleeve | loser_rate_delta_lte_2pp | -1.8999999999991246e-05 | True |
| high_conviction_top15_v3_exception_sleeve | 2025Q1_drawdown_not_materially_worse | -0.9571149999999999 | True |
| high_conviction_top15_v3_exception_sleeve | exception_sleeve_positive_avg_90d | 35.387233 | True |
| top15_conservative_10_core_3_exception | avg_90d_not_worse | 16.290022 | True |
| top15_conservative_10_core_3_exception | winner_rate_close_or_better | 0.278283 | True |
| top15_conservative_10_core_3_exception | loser_rate_delta_lte_2pp | -0.0025249999999999995 | True |
| top15_conservative_10_core_3_exception | 2025Q1_drawdown_not_materially_worse | -0.9571149999999999 | True |
| top15_conservative_10_core_3_exception | exception_sleeve_positive_avg_90d | 28.548956 | True |
| top15_rm1_priority_max2_rm2plus | avg_90d_not_worse | 17.278760 | True |
| top15_rm1_priority_max2_rm2plus | winner_rate_close_or_better | 0.288902 | True |
| top15_rm1_priority_max2_rm2plus | loser_rate_delta_lte_2pp | -1.8999999999991246e-05 | True |
| top15_rm1_priority_max2_rm2plus | 2025Q1_drawdown_not_materially_worse | -0.9571149999999999 | True |
| top15_rm1_priority_max2_rm2plus | exception_sleeve_positive_avg_90d | 35.387233 | True |

Interpretation: main Top-15 v3 clears the quantitative research-queue tests, but because most target right-tail misses remain missed and AKG/macro PIT fields are still incomplete, live use should be Top-10 core plus exception research sleeve.

## Target right-tail capture

| ticker | present | status | best_90d | selected_quarters |
| --- | --- | --- | --- | --- |
| CRNC | True | missed | 431.05% |  |
| CVNA | True | missed | 416.35% |  |
| SNDK | True | missed | 324.98% |  |
| AAOI | True | selected | 311.88% | 2023Q4 |
| BE | True | missed | 290.50% |  |
| AXTI | True | missed | 196.78% |  |
| AEHR | True | missed | 188.12% |  |
| ICHR | True | missed | 144.92% |  |
| CRDO | True | selected | 152.51% | 2024Q3 |

The sleeve captured `AAOI`, `CRDO` from the named target set but still missed most low-score RM/theme-wave examples. That means the exception sleeve helps, but it does not fully solve messy right-tail discovery.

## No-leakage and caveats

- Selector receives selection-time fields only; returns are attached after selection is frozen.
- Forbidden labels/return columns are excluded per `run_manifest.json`.
- Missing AKG/macro fields remain neutral/unavailable.
- This is observed-data analysis, not full production v2 validation.

## Companion outputs

- `outputs/fundamental_backtest/analysis_top15_exception/variant_comparison.csv`
- `outputs/fundamental_backtest/analysis_top15_exception/adoption_criteria_check.csv`
- `outputs/fundamental_backtest/analysis_top15_exception/target_right_tail_capture.csv`
- `outputs/fundamental_backtest/analysis_top15_exception/exception_sleeve_drivers.csv`
- `outputs/fundamental_backtest/analysis_top15_exception/core_vs_exception_summary.csv`
- `outputs/fundamental_backtest/analysis_top15_exception/left_tail_penalty_comparison.csv`
- `outputs/fundamental_backtest/analysis_top15_exception/missed_right_tail_after_top15.csv`
- `outputs/fundamental_backtest/analysis_top15_exception/analysis_manifest.json`
