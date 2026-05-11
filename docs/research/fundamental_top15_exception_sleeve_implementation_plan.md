# Implementation Plan: High-Conviction Top-15 With Right-Tail Exception Sleeve

**Status:** implementation request  
**Intended GitHub path:** `docs/research/fundamental_top15_exception_sleeve_implementation_plan.md`  
**Scope label:** High-Conviction Top-15 observed-data extension / exception-sleeve test  
**Do not claim:** full live AKG+macro production-v2 validation until AKG/theme acceleration and macro fields are PIT-populated or forward-validated.

---

## 0. Why this is being added

The current High-Conviction Top-10 observed-data backtest is valid and useful, but the miss analysis shows that several major right-tail winners were mechanically excluded because final eligibility still relied too heavily on `entry_score_0_100 >= 70` or a narrow HP override.

Observed missed examples:

| Ticker | Quarter | 90d return | Mechanical miss | Entry score | RM bucket | HP bucket | Key issue |
|---|---:|---:|---|---:|---:|---:|---|
| CRNC | 2024Q4 | +431.1% | not eligible | 29 | 2+ | 0 | RM flagged, entry score too low |
| CVNA | 2023Q2 | +416.4% | not eligible | 27 | 1 | 0 | RM flagged, entry score too low |
| SNDK | 2025Q3 | +325.0% | not eligible | 22 | 1 | 2+ | RM + HP signal, no entry/HP override |
| AAOI | 2023Q2 | +311.9% | not eligible | 20 | 1 | 0 | RM flagged; theme existed, score too low |
| BE | 2025Q3 | +290.5% | not eligible | 33 | 1 | 2+ | RM + HP signal, score too low |
| AXTI | 2026Q1 | +196.8% | not eligible | 37 | 2+ | 0 | RM detected, but not enough routing authority |
| AEHR | 2026Q1 | +188.1% | not eligible | 13 | 1 | 0 | RM flagged, very low score |
| ICHR | 2026Q1 | +144.9% | not eligible | 3 | 1 | 1 | theme/supplier move, score almost zero |
| CRDO | 2024Q3 | +152.5% | not eligible | 68 | 1 | 2+ | near-threshold HP/RM name missed |

Important design lesson:

```text
RM worked as a detection layer,
but the final Top-10 eligibility gate did not give RM / theme-wave / hidden-supplier candidates enough routing authority.
```

Do **not** solve this by lowering the core entry-score threshold globally. That would add too much noise.

Solve it with a constrained exception sleeve:

```text
Top-15 fundamental review list =
    10 core high-conviction names
    + up to 5 right-tail exception names
```

This is a research/underwriting queue, **not** an instruction to buy all 15 equally.

---

## 1. Design principles

1. Preserve existing `high_conviction_top10_v2_final` behavior.
2. Add a new variant; do not silently change current Top-10 semantics.
3. Treat the Top-15 as a **fundamental review list**, not a 15-stock equal-weight portfolio.
4. Separate selected rows by sleeve:
   - `core`
   - `right_tail_exception`
5. Exception names should be starter/research-priority candidates until underwriting confirms:
   - LLM/fundamental thesis
   - theme or catalyst evidence
   - valuation/upside
   - macro permission
   - risk/liquidity/sizing
6. Never use forward-looking labels for selection:
   - `return_10d_pct`
   - `return_20d_pct`
   - `return_30d_pct`
   - `return_60d_pct`
   - `return_90d_pct`
   - winner/loser labels
   - monitoring/final-rank/current-return columns
7. Missing AKG/macro fields must be treated as unavailable, not as positive or negative evidence.
8. Do not create buy signals directly from exception-sleeve routing.

---

## 2. New variant

Implement:

```text
high_conviction_top15_v3_exception_sleeve
```

Definition:

```text
Top-15 =
    10 core high-conviction names
    + up to 5 right-tail exception names
```

### 2.1 Core sleeve

Core sleeve uses current `high_conviction_top10_v2_final` logic.

```text
core_sleeve:
    rank current v2 candidates by current v2 high-conviction score
    select top 10
```

The existing selected rows should remain unchanged when exception mode is off.

### 2.2 Exception sleeve

Exception candidates are selected from remaining rows not already in the core sleeve.

Eligibility:

```text
right_tail_exception_candidate =
    eligible/live candidate = true
    AND hard_reject_reason is blank
    AND post_llm_demote_flag != 1
    AND entry_score_0_100 >= 20
    AND (
        single_rm_signal_bucket = true
        OR rm_buy_review_flag = true
        OR repricing_momentum_priority = true
        OR market_repricing_score >= 10
        OR hp_LLM_best = true
        OR hp_signal_count > 0
        OR theme_tailwind_score > 0
        OR primary_theme is not blank
        OR theme_acceleration_research_visibility = true
        OR akg_universe_tier = "T5_RESCAN"
    )
```

Special near-threshold exception:

```text
near_threshold_hp_rm_exception =
    entry_score_0_100 >= 65
    AND rm_buy_review_flag = true
    AND (
        hp_LLM_best = true
        OR hp_signal_count > 0
        OR market_repricing_score >= 10
    )
```

A row satisfying this should be eligible for the exception sleeve even if the other exception score rank is lower.

---

## 3. Exception scoring

Add a deterministic score:

```text
right_tail_exception_score =
    entry_score_0_100
    + 15 if single_rm_signal_bucket = true
    + 8  if rm_buy_review_flag = true
    + 8  if repricing_momentum_priority = true
    + 8  if market_repricing_score >= 10
    + 8  if hp_LLM_best = true
    + 6  if hp_signal_count > 0
    + 8  if primary_theme is not blank
    + 6  if theme_tailwind_score > 0
    + 10 if theme_acceleration_research_visibility = true
    + 8  if akg_universe_tier = "T5_RESCAN"
    - 10 if rm_signal_bucket = "2+" and no theme/LLM/HP support
    - 10 if risk_penalty_score >= 10
    - 15 if post_llm_demote_flag = 1
```

Sort exception candidates by:

```text
right_tail_exception_score desc
entry_score_0_100 desc
market_repricing_score desc
ticker asc
```

---

## 4. Exception slot constraints

Exception sleeve max:

```text
exception_slots = 5
```

Add slot controls:

```text
max_exception_slots = 5
min_single_rm_slots = 2, if available
max_rm2plus_slots = 2, unless theme/LLM/HP confirms
max_no_theme_no_llm_exceptions = 2
max_same_theme = 2
max_same_sector = 3
```

Interpretation:

- Prefer single-RM-signal bucket candidates.
- Do not let all exception slots become RM 2+ distressed candidates.
- RM 2+ requires stronger confirmation:
  - `hp_signal_count > 0`
  - `hp_LLM_best = true`
  - `primary_theme` populated
  - `theme_tailwind_score > 0`
  - `theme_acceleration_research_visibility = true`
  - `akg_universe_tier = T5_RESCAN`
- If slot constraints cannot be met, select fewer than 5 exceptions and emit a warning.

---

## 5. Outputs and labels

Every selected row must include:

```text
selected_sleeve:
    core
    right_tail_exception

selected_sleeve_rank:
    integer rank inside sleeve

portfolio_treatment:
    core_buy_underwriting
    exception_research_or_starter_underwriting

right_tail_exception_score
right_tail_exception_reason_codes
right_tail_exception_warning_codes

rm_signal_bucket
rm_active_fields
hp_signal_bucket
hp_active_fields
```

Daily recommendation wording:

```text
Core 10 are primary buy-underwriting candidates.
Exception 5 are right-tail research / starter-underwriting candidates.
Do not equal-weight all 15 automatically.
```

---

## 6. Files to modify

### 6.1 Selection engine

Modify:

```text
tradingagents/research/fundamental/src/selection/high_conviction_top10.py
```

Add:

```python
@dataclass(frozen=True)
class RightTailExceptionConfig:
    enabled: bool = False
    core_n: int = 10
    exception_slots: int = 5
    min_exception_entry_score: float = 20.0
    near_threshold_entry_score: float = 65.0
    max_rm2plus_slots: int = 2
    max_no_theme_no_llm_exceptions: int = 2
    max_same_theme: int = 2
    max_same_sector: int = 3
```

Add helpers:

```python
def _signal_count(row, fields) -> int
def _single_rm_signal_bucket(row) -> bool
def _rm_signal_bucket(row) -> str
def _hp_signal_bucket(row) -> str
def _has_theme_or_akg_confirmation(row) -> bool
def _has_llm_or_hp_confirmation(row) -> bool
def _is_right_tail_exception_candidate(row, cfg) -> tuple[bool, list[str]]
def _right_tail_exception_score(row) -> tuple[float, dict[str, float]]
def _select_exception_sleeve(core_rows, all_rows, cfg) -> tuple[list[dict], list[str]]
```

Add public selector:

```python
def select_high_conviction_top15_exception_sleeve(
    rows: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any] | None,
    coverage_rows: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    ...
```

Or integrate via `select_high_conviction_top10()` when config contains:

```python
exception_sleeve_enabled = True
core_n = 10
exception_slots = 5
top_n = 15
```

Preserve old behavior if exception sleeve is disabled.

### 6.2 CLI

Modify:

```text
cli/commands/fundamental.py
```

Keep existing `fundamental-top10` working unchanged.

Add either:

Option A — new command:

```bash
aeternus fundamental-top15 \
  --scores-csv ... \
  --output-root ... \
  --date YYYY-MM-DD \
  --core-n 10 \
  --exception-slots 5 \
  --format table
```

Option B — add flags to existing command:

```bash
aeternus fundamental-top10 \
  --scores-csv ... \
  --output-root ... \
  --date YYYY-MM-DD \
  --top-n 15 \
  --core-n 10 \
  --exception-slots 5 \
  --enable-exception-sleeve
```

Preferred: implement both a convenience command `fundamental-top15` and underlying config support.

Daily output names for Top-15:

```text
high_conviction_top15.csv
high_conviction_top15.json
high_conviction_top15_daily_recommendation.md
```

Do not overwrite existing Top-10 output names unless user explicitly uses `fundamental-top10`.

### 6.3 Backtest script

Add:

```text
tradingagents/research/fundamental/backtests/high_conviction_top15_exception_sleeve.py
```

Inputs:

```text
outputs/fundamental_backtest/pit_fundamental_panel.csv
```

Outputs:

```text
outputs/fundamental_backtest/high_conviction_top15_exception_sleeve/
    selected_names_by_quarter_top15.csv
    strategy_summary_top15.csv
    strategy_by_quarter_top15.csv
    core_vs_exception_contribution.csv
    exception_slot_diagnostics.csv
    right_tail_capture_comparison.csv
    left_tail_penalty_comparison.csv
    missed_right_tail_after_top15.csv
    run_manifest.json
    README_ANALYSIS.md
```

Compare variants:

```text
high_conviction_top10_v2_final
high_conviction_top15_v3_exception_sleeve
top15_conservative_10_core_3_exception
top15_rm1_priority_max2_rm2plus
```

### 6.4 Analysis script

Either extend or add:

```text
scripts/analyze_fundamental_top15_exception_sleeve.py
```

Outputs:

```text
docs/research/fundamental_top15_exception_sleeve_observed_backtest_analysis.md
outputs/fundamental_backtest/analysis_top15_exception/
```

---

## 7. Backtest metrics

Compute for each variant:

```text
quarter_count
total_picks
avg_picks_per_quarter
avg_return_10d_pct
avg_return_20d_pct
avg_return_30d_pct
avg_return_60d_pct
avg_return_90d_pct
winner_90d_30pct_rate
loser_90d_minus30pct_rate
worst_quarter_avg_90d
best_quarter_avg_90d
2025Q1_avg_90d
2025Q1_loser_rate
```

Core-vs-exception:

```text
sleeve
pick_count
avg_return_90d_pct
winner_90d_30pct_rate
loser_90d_minus30pct_rate
contribution_to_strategy_avg
top_winners
top_losers
```

Right-tail capture:

```text
ticker
quarter
return_90d_pct
old_v2_status
top15_status
selected_sleeve
selected_sleeve_rank
right_tail_exception_score
mechanical_exclusion_before
mechanical_status_after
```

Must specifically report whether these were captured:

```text
CRNC
CVNA
SNDK
AAOI
BE
AXTI
AEHR
ICHR
CRDO
```

---

## 8. Acceptance criteria

Implementation acceptance:

```text
1. Existing Top-10 tests still pass.
2. Existing fundamental-top10 output unchanged when exception sleeve disabled.
3. New Top-15 selector produces up to 15 rows:
   - up to 10 core
   - up to 5 right_tail_exception
4. No duplicate ticker-quarter rows in selected output.
5. No selected row uses forbidden forward-looking labels in selection.
6. Missing AKG/macro fields remain neutral/unavailable.
7. Outputs include selected_sleeve and exception reason/warning codes.
8. Daily recommendation labels exception names as research/starter-underwriting, not equal-weight buys.
```

Backtest adoption criteria:

```text
Only recommend live Top-15 if:
1. Avg 90d return improves or is not materially worse than Top-10 v2.
2. +30% hit rate improves or stays close to Top-10 v2.
3. -30% loser rate does not rise by more than 2 percentage points.
4. 2025Q1 drawdown does not materially worsen.
5. Exception sleeve has positive average 90d return.
6. Exception sleeve captures at least some previously missed right-tail names.
```

If these fail:

```text
Use Top-10 v2 as buy-underwriting queue.
Use Top-15 exception sleeve as watchlist/fundamental review list only.
```

---

## 9. Tests to add

### Unit tests

Add:

```text
tests/test_high_conviction_top15_exception_sleeve.py
```

Test cases:

```text
test_top15_preserves_top10_when_exception_disabled
test_top15_selects_10_core_plus_5_exceptions
test_exception_candidate_requires_rm_or_hp_or_theme_or_akg_signal
test_exception_candidate_allows_low_entry_score_with_rm_signal
test_exception_candidate_blocks_post_llm_demote
test_near_threshold_crdo_style_exception
test_rm2plus_penalty_applies_without_confirmation
test_single_rm_bucket_priority
test_exception_sleeve_no_duplicate_core_tickers
test_exception_sleeve_missing_akg_macro_fields_are_neutral
test_exception_sleeve_does_not_use_return_labels
test_daily_recommendation_labels_exceptions_as_starter_or_research
```

### Backtest tests

Add:

```text
tests/test_high_conviction_top15_backtest.py
```

Test cases:

```text
test_top15_backtest_outputs_exist
test_core_vs_exception_contribution_present
test_right_tail_capture_comparison_includes_target_miss_names
test_left_tail_penalty_comparison_present
test_selection_forbidden_columns_excluded
```

---

## 10. Documentation updates

Update or add:

```text
docs/research/fundamental_top15_exception_sleeve_implementation_plan.md
docs/research/fundamental_top15_exception_sleeve_observed_backtest_analysis.md
```

Update:

```text
docs/research/fundamental_top10_observed_backtest_analysis.md
```

Add a section:

```text
Next test: Top-15 exception sleeve
```

Clarify:

```text
Top-15 is a fundamental review list.
Top-10 remains the core buy-underwriting sleeve.
Exception names are not automatic equal-weight buys.
```

---

## 11. Commands Codex should support

Daily Top-15:

```bash
python3 -m cli.main fundamental-top15 \
  --scores-csv eval_results/fundamental/YYYY-MM-DD/fundamental_final_scores_YYYY-MM-DD.csv \
  --output-root eval_results/fundamental/YYYY-MM-DD \
  --date YYYY-MM-DD \
  --core-n 10 \
  --exception-slots 5 \
  --format table
```

Backtest:

```bash
python3 -m tradingagents.research.fundamental.backtests.high_conviction_top15_exception_sleeve \
  --pit-panel outputs/fundamental_backtest/pit_fundamental_panel.csv \
  --prior-selected outputs/fundamental_backtest/high_conviction_top10/selected_names_by_quarter.csv \
  --out-dir outputs/fundamental_backtest/high_conviction_top15_exception_sleeve
```

Analysis:

```bash
python3 scripts/analyze_fundamental_top15_exception_sleeve.py \
  --bundle-dir outputs/fundamental_backtest/high_conviction_top15_exception_sleeve \
  --prior-analysis-dir outputs/fundamental_backtest/analysis \
  --out-dir outputs/fundamental_backtest/analysis_top15_exception
```

---

## 12. Codex final handoff expected

After implementation, Codex should commit:

```text
implementation commit:
  feat: add fundamental top15 right-tail exception sleeve

analysis commit:
  analysis: add fundamental top15 exception sleeve observed review
```

Expected tracked outputs:

```text
docs/research/fundamental_top15_exception_sleeve_implementation_plan.md
docs/research/fundamental_top15_exception_sleeve_observed_backtest_analysis.md
outputs/fundamental_backtest/high_conviction_top15_exception_sleeve/
outputs/fundamental_backtest/analysis_top15_exception/
```

Run verification:

```bash
python -m pytest \
  tests/test_cli_fundamental_top10.py \
  tests/test_high_conviction_top15_exception_sleeve.py \
  tests/test_high_conviction_top15_backtest.py
```

Also run existing focused fundamental tests if available.

---

## 13. Non-goals

Do not:

```text
1. Lower entry_score >= 70 globally.
2. Auto-buy all RM flagged names.
3. Treat Top-15 as equal-weight portfolio.
4. Claim full AKG+macro production v2 validation.
5. Regenerate the core PIT/Top-10 bundle unless QA fails.
6. Use returns/monitoring/final-rank columns for selection.
7. Replace the current Top-10 command behavior.
```

---

## 14. Final intended behavior

The final framework should support:

```text
Top-10:
    clean high-conviction buy-underwriting queue

Top-15:
    10 clean high-conviction names
    + 5 right-tail exception research/starter-underwriting names
```

This should improve discovery of messy right-tail names such as CRNC, CVNA, SNDK, AAOI, BE, AXTI, AEHR, ICHR, and CRDO, while preserving disciplined core selection and explicit risk controls.
