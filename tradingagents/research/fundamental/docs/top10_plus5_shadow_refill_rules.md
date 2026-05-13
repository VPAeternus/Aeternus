# Top 10 + Plus 5 + Shadow Refill Rules

Last verified: 2026-05-13.

Source of truth: `tradingagents/research/fundamental/src/selection/high_conviction_top10.py`.

PM correction: intended shadow behavior blocks actual demoted core tickers from Plus 5 auto-selection in the same shadow run. It should not automatically block every ticker that merely has a deterioration flag outside the original core.

## Operator Meaning

- Top 10 core: primary buy-underwriting queue.
- Plus 5 exception: right-tail research / starter-underwriting queue, not equal-weight buys.
- Shadow refill: review-only what-if replacement list for deteriorating core names. It does not replace official Top 15 without PM decision, and demoted core names should not re-enter Plus 5 automatically.

## Top 10 Core Formula

Default config:

- `top_n = 10`
- `score_field = entry_score_0_100`
- `min_score = 70`
- `min_confidence = 3`
- `require_confidence = true`
- `allow_overrides = true`

Core composite:

```text
composite_score = entry_score_0_100 + (confidence_numeric * 2)
```

Confidence parsing:

```text
high = 4
medium = 3
low = 2
numeric values pass through as numeric confidence
```

Core rank order:

```text
1. highest composite_score
2. highest entry_score_0_100
3. highest confidence_numeric
4. ticker A-Z
```

Hard blocks:

- missing ticker
- missing or nonnumeric score
- bad CIK or bad CIK status
- hard reject reason present
- bad document status
- missing confidence when confidence required
- confidence below threshold
- SEC coverage needs fetch, if coverage gating enabled
- SEC coverage has zero cached-ready rows, if coverage gating enabled

Bad document statuses include:

```text
blocked, invalid, missing, missing_docs, no_docs, fetch_failed,
error, unavailable, not_found, failed, blocked_metadata_or_issuer_reality
```

Bad CIK statuses include:

```text
missing, unresolved, invalid, not_found, no_match, not_resolved,
error, failed, blocked_unresolved_cik
```

Overrides bypass only the score threshold. They do not bypass hard blocks.

Override triggers:

- `theme_acceleration_score >= 80`
- truthy `theme_acceleration_research_visibility`
- truthy `theme_acceleration_rescan_flag`
- truthy `repricing_momentum_priority`
- truthy `repricing_momentum_extension`
- allowed RM override field matching `rm[1-4]_(priority|high_priority|llm_supported|extension|rescan|candidate|signal|confirmed)`
- allowed HP override field matching `hp\d+_(priority|high_priority|llm_supported|extension|rescan|candidate|signal|confirmed)`
- allowed Tier override field matching `tier\d+_L\d+_(priority|high_priority|llm_supported|rescan|signal|confirmed)`
- `T5_RESCAN` or `rescan T5` in `source`, `thesis_tags`, or `risk_tags`

## Plus 5 Exception Formula

Default config:

- `enabled = true` in CLI path
- `core_n = 10`
- `exception_slots = 5`
- `min_exception_entry_score = 20`
- `near_threshold_entry_score = 65`
- `max_rm2plus_slots = 2`
- `max_no_theme_no_llm_exceptions = 2`
- `max_same_theme = 2`
- `max_same_sector = 3`

Exception candidate must:

- not already be in Top 10 core
- pass core hard gates with `min_score = 0` and `require_confidence = false`
- have no explicit `hard_reject_reason`
- have no truthy `post_llm_demote_flag`
- have `entry_score_0_100 >= 20`
- have at least one right-tail signal

Right-tail signal triggers:

- exactly one active RM signal field
- truthy `rm_buy_review_flag`
- truthy `repricing_momentum_priority`
- `market_repricing_score >= 10`
- truthy `hp_LLM_best`
- at least one active HP signal field
- `theme_tailwind_score > 0`
- nonblank `primary_theme`
- truthy `theme_acceleration_research_visibility`
- `akg_universe_tier = T5_RESCAN`
- near-threshold exception: `entry_score_0_100 >= 65` and `rm_buy_review_flag` and one of `hp_LLM_best`, any HP signal, or `market_repricing_score >= 10`

RM signal fields:

```text
rm1_low_price_dislocation_momentum
rm2_weak_acceleration
rm3_mid_price_dislocation_momentum
rm4_persistent_repricing_wave
rm_buy_review_flag
```

HP signal fields:

```text
hp0_high_price_broad
hp1_quality_pullback
hp2_dislocation_momentum_priority
hp2_dislocation_momentum_watch
hp3_large_quality_theme_exception
hp4_score_reacceleration_watch
hp_production_extension
hp_research_extension
hp_LLM_best
```

HP signal count nuance: `HP_SIGNAL_FIELDS` includes `hp_LLM_best`. In the Plus 5 formula, `hp_LLM_best` can therefore contribute the explicit `+8` adder and also satisfy the `+6` "any HP signal active" adder.

Exception score:

```text
right_tail_exception_score =
  entry_score_0_100
  + 15 if exactly one RM signal is active
  + 8  if rm_buy_review_flag
  + 8  if repricing_momentum_priority
  + 8  if market_repricing_score >= 10
  + 8  if hp_LLM_best
  + 6  if any HP signal active
  + 8  if primary_theme nonblank
  + 6  if theme_tailwind_score > 0
  + 10 if theme_acceleration_research_visibility
  + 8  if akg_universe_tier == T5_RESCAN
  - 10 if RM bucket is 2+ and no theme/AKG/LLM/HP confirmation
  - 10 if risk_penalty_score >= 10
  - 15 if post_llm_demote_flag
```

Exception rank order:

```text
1. highest right_tail_exception_score
2. highest entry_score_0_100
3. highest market_repricing_score
4. ticker A-Z
```

Fill logic:

1. Build all exception candidates and score them.
2. Try to fill up to `min(2, exception_slots, count(single_rm_candidates))` with single-RM candidates first.
3. Fill remaining slots by exception rank.
4. Apply caps during fill:
   - max 2 unconfirmed RM2+ rows
   - max 2 rows without theme/AKG/LLM/HP confirmation
   - max 2 per same primary theme
   - max 3 per same sector

## Shadow Refill Formula

Default CLI config:

- `core_deterioration_refill.enabled = true`
- `mode = strict`
- `block_deterioration_from_exceptions = true`; intended scope is actual demoted core tickers only
- `core_n = 10`
- `exception_slots = 5`

Shadow refill is opt-in and not official.

Core deterioration flags are computed only for rows treated as core.

RM/HP count nuance: deterioration counts use label-active signal counting over the RM/HP field lists. `HP_SIGNAL_FIELDS` includes `hp_LLM_best`, so HP count can include that field. False labels such as blank, `0`, `false`, `no`, `none`, `null`, `nan`, `na`, and `n/a` do not count.

High-score deterioration:

```text
high_score_deterioration =
  entry_score_0_100 >= 80
  AND score_change <= -1
  AND negative_revision_risk >= 2
```

Weak no-theme repricing stack:

```text
weak_no_theme_repricing_stack =
  primary_theme is blank
  AND pre_llm_fundamental_bucket == "weak"
  AND (
    active RM signal count >= 3
    OR (active HP signal count > 0 AND market_repricing_score >= 6)
  )
  AND (
    score_change <= 0
    OR negative_revision_risk >= 2
  )
```

Review / downgrade / strict:

```text
core_deterioration_review =
  selected_sleeve == "core"
  AND (high_score_deterioration OR weak_no_theme_repricing_stack)

core_deterioration_downgrade =
  core_deterioration_review
  AND (
    weak_no_theme_repricing_stack
    OR (primary_theme is blank AND pre_llm_fundamental_bucket == "weak")
  )

core_deterioration_strict_override_required =
  core_deterioration_review
  AND high_score_deterioration
  AND weak_no_theme_repricing_stack
```

Demotion modes:

```text
strict    -> demote if core_deterioration_strict_override_required
downgrade -> demote if core_deterioration_downgrade
all_review -> demote if core_deterioration_review
```

Shadow refill process:

1. Rank the full eligible core pool using Top 10 core formula.
2. Build deterioration candidates from rows that meet the selected demotion mode.
3. Walk ranked core candidates in order.
4. Skip tickers selected for shadow demotion.
5. Select the first `core_n` unblocked candidates as shadow core.
6. If a skipped ticker had original core rank `<= core_n`, record it as an actual demoted core ticker.
7. Replacement rows are shadow core rows whose original `core_candidate_rank > core_n`.
8. Build Plus 5 exception sleeve from original rows, excluding shadow core and, by intended default, actual demoted core tickers.
9. Strip outcome/label fields from shadow artifacts.

Implementation nuance to audit: as of this verification, the current selector may pass the broader deterioration-flagged `blocked_tickers` set into Plus 5 blocking when `block_deterioration_from_exceptions = true`. Intended behavior is narrower: block actual demoted core tickers only.

Outcome fields stripped from shadow artifact rows:

```text
any key containing return, winner, loser, target, monitoring_score,
final_rank, _delta_, or starting with delta_
```

Shadow outputs:

- `high_conviction_top15_core_deterioration_refill_shadow.csv`
- `high_conviction_top15_core_deterioration_refill_shadow.json`
- `core_deterioration_refill_shadow_replacements.csv`

PM rule:

Shadow refill is review-only. PM override required before action.
