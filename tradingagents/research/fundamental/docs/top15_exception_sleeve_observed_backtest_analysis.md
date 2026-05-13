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

| ticker | target_quarter | present | status | target_90d | selected_quarters |
| --- | --- | --- | --- | --- | --- |
| CRNC | 2024Q4 | True | missed | 431.05% |  |
| CVNA | 2023Q2 | True | missed | 416.35% |  |
| SNDK | 2025Q3 | True | missed | 324.98% |  |
| AAOI | 2023Q2 | True | missed | 311.88% |  |
| BE | 2025Q3 | True | missed | 290.50% |  |
| AXTI | 2026Q1 | True | missed | 196.78% |  |
| AEHR | 2026Q1 | True | missed | 188.12% |  |
| ICHR | 2026Q1 | True | missed | 144.92% |  |
| CRDO | 2024Q3 | True | selected | 152.51% | 2024Q3 |

The sleeve captured `CRDO` from the named target set but still missed most low-score RM/theme-wave examples. That means the exception sleeve helps, but it does not fully solve messy right-tail discovery.

## Right-Tail Scout + Demote Review

These queues are visibility/research outputs, not buy lists. A target can be visibility-routed without being selected into Top-15. `blocked_hard_demote` counts as visibility only, not actionable research or buy underwriting; non-hard `demote_review` is human research review and counts as actionable only when positive right-tail evidence is present.

| queue | row_count | avg_right_tail_evidence_score |
| --- | --- | --- |
| top15_exception_candidate | 0 |  |
| right_tail_scout | 18 | 31.444444444444443 |
| core_deterioration_review | 77 |  |
| demote_review_full_audit | 332 | 4.9397590361445785 |
| demote_review_priority_1_daily | 99 | 11.858585858585858 |
| demote_review_priority_2 | 233 | 2.0 |
| demote_review_low_priority | 0 |  |
| thin_signal_watchlist_full_audit | 1213 | 12.530915086562242 |
| thin_signal_watchlist_top25_daily | 25 | 31.84 |
| thin_signal_watchlist_top50_daily | 50 | 26.92 |
| thin_signal_watchlist_top100_daily | 100 | 24.46 |
| diagnostics | 21182 | 0.05381928052119724 |

Target visibility metrics:

| metric | value |
| --- | --- |
| target_visibility_routed_count | 9 |
| target_actionable_research_routed_count | 6 |
| target_scout_or_top15_routed_count | 2 |
| target_demote_review_routed_count | 4 |
| target_buy_underwriting_routed_count | 1 |
| target_event_count | 9 |

Final behavior:

1. Top-10 Core: clean buy-underwriting queue.
2. Top-15 Exception Sleeve: selected right-tail exception/starter-underwriting rows; output unchanged.
3. Top-15 Exception Candidate Queue: visibility/staging only.
4. Core Deterioration Review: selected core rows that require manual review before buy-underwriting; strict rows move to scout/review unless PM overrides.
5. Demote Review: full file is audit-only; daily PM consumption uses `demote_review_priority_1.csv`.
6. Thin-Signal Watchlist: weak RM/HP/repricing evidence with insufficient proof; full file is audit-only; daily PM consumption uses Top 25 / Top 50 / Top 100 cuts from `thin_signal_watchlist_top100.csv`.
7. Right-Tail Scout + Demote Review: messy theme-wave / turnaround / hidden-supplier candidates too important to ignore but not automatically buys.

## Core Deterioration Refill Shadow Review

Plain English: this is a safe what-if version of the Top-15 list. It does not change the official Top-15.

What it does:

- Finds core names that look risky because their fundamentals deteriorated.
- Temporarily removes those names in a shadow list.
- Replaces them with the next-best eligible names.
- Shows what the Top-15 would have looked like with those swaps.
- Blocks the removed risky names from sneaking back in through the exception sleeve.
- Produces a comparison table showing each removed name, its replacement, and how that swap performed historically.

Why it matters:

- Gives PM a review tool before acting on weak core names.
- Helps identify avoidable blowups.
- Keeps the official process unchanged until the shadow process earns trust.

Why it is called "shadow refill":

- "Refill" means a risky core name is removed from the what-if list and the open slot is filled with the next eligible name.
- "Shadow" means the swap is review-only. It runs beside the official Top-15 and does not change the official recommendation.
- This lets us learn whether the rule keeps working before promoting it into the official process.

This shadow-only review is not the official Top-15 list. It preserves Top-15 capacity by testing whether demoted/refill-ineligible core deterioration tickers can be replaced without changing the frozen official selection output.

Use `core_deterioration_refill_shadow_replacements.csv` to compare demoted core names against next eligible ex-ante replacements. Return labels and replacement deltas are diagnostic only and are attached after selection is frozen.

Daily workflow:

1. Run the normal `fundamental-top15` process first. This remains the official Top-15.
2. Run the optional `fundamental-top15-refill-shadow` check after final scores are ready.
3. Open `core_deterioration_refill_shadow_replacements.csv`.
4. Review each proposed swap: removed ticker, replacement ticker, deterioration reason, RM/HP evidence, and score context.
5. Treat the file as a PM review queue, not an automatic trade instruction.
6. If the PM agrees with a swap, document the override decision manually; otherwise keep the official Top-15 unchanged.

Daily command:

```bash
python3 -m cli.main fundamental-top15-refill-shadow \
  --scores-csv tradingagents/research/fundamental/runs/YYYY-MM-DD/selection/fundamental_final_scores_YYYY-MM-DD.csv \
  --output-root tradingagents/research/fundamental/runs/YYYY-MM-DD/selection \
  --date YYYY-MM-DD \
  --mode strict
```

Daily outputs:

- `high_conviction_top15_core_deterioration_refill_shadow.csv` — the what-if Top-15 review list.
- `core_deterioration_refill_shadow_replacements.csv` — the comparison table to review proposed removals and replacements.
- `high_conviction_top15_core_deterioration_refill_shadow.json` — machine-readable detail for audit/debugging.

Operating cadence:

- The official Top-15 can change daily when the pipeline is rerun.
- The shadow refill list can also change daily when the pipeline is rerun.
- The 90-day performance comparison updates only after enough time has passed to know the forward returns.
- Historical proof therefore updates on a delayed 90-day / quarterly cadence, but daily review output can update every day.

What can realistically change daily:

- New 8-Ks, press releases, earnings updates, or newly cached SEC documents.
- Price and repricing momentum.
- Macro/regime permission.
- New theme, AKG, or dealflow evidence.
- New names entering the universe.
- More complete document extraction after a rerun.

Important practical point: the core fundamental score is mostly filing-driven. For many names, it should stay stable between quarterly filings unless new evidence arrives. Most major deterioration/refill movement should cluster around earnings and filing cycles. If the shadow refill list changes sharply day-to-day without new evidence, treat that as a scoring-stability issue to investigate.

Current interpretation:

- The historical shadow refill results look better than the official Top-15 v3 baseline, with higher average 90-day return and lower observed loser rate.
- That supports using it as a PM review tool now.
- It does not yet make it an automatic official replacement rule; forward validation is still required.

## No-leakage and caveats

- Selector receives selection-time fields only; returns are attached after selection is frozen.
- Forbidden labels/return columns are excluded per `run_manifest.json`.
- Missing AKG/macro fields remain neutral/unavailable.
- This is observed-data analysis, not full production v2 validation.

## Companion outputs

- `tradingagents/research/fundamental/runs/backtests/analysis_top15_exception/variant_comparison.csv`
- `tradingagents/research/fundamental/runs/backtests/analysis_top15_exception/adoption_criteria_check.csv`
- `tradingagents/research/fundamental/runs/backtests/analysis_top15_exception/target_right_tail_capture.csv`
- `tradingagents/research/fundamental/runs/backtests/analysis_top15_exception/exception_sleeve_drivers.csv`
- `tradingagents/research/fundamental/runs/backtests/analysis_top15_exception/core_vs_exception_summary.csv`
- `tradingagents/research/fundamental/runs/backtests/analysis_top15_exception/left_tail_penalty_comparison.csv`
- `tradingagents/research/fundamental/runs/backtests/analysis_top15_exception/missed_right_tail_after_top15.csv`
- `tradingagents/research/fundamental/runs/backtests/analysis_top15_exception/core_deterioration_review_queue.csv`
- `tradingagents/research/fundamental/runs/backtests/analysis_top15_exception/right_tail_queue_summary.csv`
- `tradingagents/research/fundamental/runs/backtests/analysis_top15_exception/target_visibility_metrics.csv`
- `tradingagents/research/fundamental/runs/backtests/analysis_top15_exception/target_miss_rescue_audit.csv`
- `tradingagents/research/fundamental/runs/backtests/analysis_top15_exception/v4_rescue_variant_summary.csv`
- `tradingagents/research/fundamental/runs/backtests/analysis_top15_exception/core_deterioration_refill_shadow_selected.csv`
- `tradingagents/research/fundamental/runs/backtests/analysis_top15_exception/core_deterioration_refill_shadow_replacements.csv`
- `tradingagents/research/fundamental/runs/backtests/analysis_top15_exception/core_deterioration_refill_shadow_summary.csv`
- `tradingagents/research/fundamental/runs/backtests/analysis_top15_exception/demote_review_priority_1.csv`
- `tradingagents/research/fundamental/runs/backtests/analysis_top15_exception/thin_signal_watchlist_queue.csv`
- `tradingagents/research/fundamental/runs/backtests/analysis_top15_exception/thin_signal_watchlist_top100.csv`
- `tradingagents/research/fundamental/runs/backtests/analysis_top15_exception/analysis_manifest.json`
