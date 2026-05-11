# Top15 Core Deterioration Refill Spec

## Problem

Current `core_deterioration_review_queue.csv` flags suspicious Top-15 core names but does not test whether freeing those core slots allows better ex-ante candidates to enter. Historical analysis shows deterioration patterns underperform, but the official `high_conviction_top15_v3_exception_sleeve` must remain stable until a shadow variant is validated.

## Required behavior

1. Preserve current Top-15 v3 behavior and artifact names by default.
2. Add a separate shadow selector variant; do not replace `high_conviction_top15_v3_exception_sleeve`.
3. Shadow selector demotes flagged core rows from core buy-underwriting and refills freed core slots with next ex-ante eligible ranked candidates.
4. Shadow output must remain Top-15 capacity: `10` refilled core + `up to 5` exception rows. It must not become a larger buy list.
5. Demoted core rows and refill-ineligible deterioration rows must not re-enter the exception sleeve automatically in the same shadow run.
6. Emit diagnostics showing demoted ticker, replacement ticker, named flags, RM/HP counts, ex-ante ranks/scores, and return-label deltas only after selection is frozen.
7. Do not use forward-looking labels (`return_*`, winner/loser labels, targets, current returns, final ranks, monitoring scores) during selection, refill, or routing.
8. Daily/live mode remains separate, opt-in, and shadow-only.
9. Historical backtest must preserve `selected_names_by_quarter_top15.csv` contents/hash unless intentionally adding separate shadow files.
10. Rank 7/8 is diagnostic metadata only. It must not be required for strict/downgrade demotion.

## Core deterioration definitions

Use label-active RM/HP counts for descriptive strings.

```text
label_active(value) = str(value).strip().lower() not in {
    "", "0", "0.0", "false", "no", "n", "none", "null", "nan", "na", "n/a"
}

rm_count = count(label_active(row[field]) for field in RM_SIGNAL_FIELDS)
hp_count = count(label_active(row[field]) for field in HP_SIGNAL_FIELDS)
```

Named flags:

```text
high_score_deterioration_flag =
    entry_score_0_100 >= 80
    AND score_change <= -1
    AND negative_revision_risk >= 2

weak_no_theme_repricing_stack_flag =
    primary_theme is blank
    AND pre_llm_fundamental_bucket = "weak"
    AND (
        rm_count >= 3
        OR (hp_count > 0 AND market_repricing_score >= 6)
    )
    AND (
        score_change <= 0
        OR negative_revision_risk >= 2
    )

core_deterioration_review_flag =
    selected_sleeve = "core"
    AND (high_score_deterioration_flag OR weak_no_theme_repricing_stack_flag)

core_deterioration_downgrade_flag =
    core_deterioration_review_flag
    AND (
        weak_no_theme_repricing_stack_flag
        OR (primary_theme is blank AND pre_llm_fundamental_bucket = "weak")
    )

core_deterioration_strict_override_required =
    core_deterioration_review_flag
    AND high_score_deterioration_flag
    AND weak_no_theme_repricing_stack_flag
```

## Shadow modes

- `strict`: demote only `core_deterioration_strict_override_required=1`.
- `downgrade`: demote `core_deterioration_downgrade_flag=1`.
- `all_review`: diagnostic-only broader mode; not the daily default.
- `rank78_review`: not supported as an implementation mode. Rank context can be emitted as metadata only.

## Acceptance criteria

- Existing Top-15 v3 selected rows remain unchanged.
- New shadow files show full Top-15 shadow selected rows, replacement diagnostics, and summary metrics.
- Demoted/refill-ineligible deterioration tickers are blocked from exception sleeve auto-selection.
- Replacement candidates are selected only from the ex-ante ranked candidate pool.
- Tests prove rank 7/8 alone does not trigger demotion.
- Tests prove high-score/weak-stack bad feature combinations trigger outside ranks 7/8.
- Tests prove replacement selection ignores future return labels.
- Run manifest records shadow outputs and no-leakage caveats.
