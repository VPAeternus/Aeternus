# Live Fundamental Pipeline Framework

## Purpose

This framework turns the SEC filing screener into a live production pipeline.

The production system has two separate pipelines:

- Pipeline A: Signal generation + entry decision
- Pipeline B: Candidate / position monitoring

The most important rule:

- Future returns must never be used to create an entry signal.
- Returns are used only after a candidate is already live.
- Return columns are monitoring inputs, not discovery inputs.
- Signal generation is no-forward-looking.
- Monitoring is post-entry risk management.
- Do not combine these mentally.

## Pipeline A: Signal Generation + Entry Decision

Pipeline A runs when new earnings or SEC filing data becomes available.

Purpose:

- Find new candidates.
- Score them.
- Assign tiers/subtiers.
- Compute entry score.
- Send names to fundamental review list immediately.
- Make buy / starter / watchlist / pass decision.

This is where new investment decisions happen.

Important:

- Entry score is available on the first tradable date.
- Do not wait for 10d / 20d / 30d / 60d returns before researching or buying.

Forward-looking rule:

- Pipeline A must never use future returns.
- Pipeline A must never use post-entry price action.
- Pipeline A must never use future filings.
- Pipeline A is allowed to use only data available as of the filing / scoring date.

Pipeline A flow:

```text
SEC filings / earnings docs
        ↓
Pre-LLM fundamental score
        ↓
Tier 0-4 classification
        ↓
Post-LLM causal / narrative scoring
        ↓
Entry score 0-100
        ↓
Investment underwriting
        ↓
Research queue / investment decision
        ↓
Buy / starter / watchlist / pass
```

Pipeline A outputs:

- Candidate row
- Tier 0-4 classification
- Post-LLM sub-tier labels
- Entry score `0-100`
- Entry score bucket
- Signal freshness status
- Research queue status
- Investment underwriting result
- Decision label: buy / starter / watchlist / pass
- Filing/evidence audit fields

## Pipeline B: Candidate / Position Monitoring

Pipeline B runs daily after a ticker is bought or actively tracked.

Purpose:

- Update prices.
- Track 10d / 20d / 30d / 60d returns.
- Apply kill-review rules.
- Update active monitoring score.
- Move stale or failed candidates out of active research.
- Support hold / add / reduce / sell decisions.

Forward-looking rule:

- Pipeline B can use realized post-entry returns only after those returns exist.
- Pipeline B cannot rewrite the original entry score.
- Pipeline B updates active monitoring score.
- Pipeline B is post-entry risk management, not signal generation.

Pipeline B flow:

```text
Bought or actively tracked candidate list
        ↓
Daily raw OHLCV update
        ↓
Return checkpoint calculation
        ↓
Stop / stress / kill-review rules
        ↓
Active monitoring score 0-100
        ↓
Hold / add / reduce / sell / kill-review
```

Pipeline B outputs:

- Updated return checkpoints
- Monitoring status
- Monitoring adjustment
- Active monitoring score `0-100`
- Signal return and position return
- Hold / add / reduce / sell / kill-review state

## Core Live Database Tables

Use a simple database or parquet-based lake with these tables.

The system should keep signal-generation data separate from monitoring data and portfolio-decision data.

All generated tables should include run lineage fields where practical:

- `pipeline_run_id`
- `as_of_date`
- `created_at`
- `source_file_hash`

### `universe`

One row per ticker.

Columns:

- `ticker`
- `company_name`
- `sector`
- `industry`
- `exchange`
- `is_active`
- `market_cap`
- `avg_dollar_volume`
- `tradability_flag`

Purpose:

- Liquidity filters.
- Tradability filters.
- Active ticker universe management.

### `filing_events`

One row per filing or earnings event.

Columns:

- `ticker`
- `quarter`
- `filing_type`
- `filing_accession`
- `filing_accepted_datetime`
- `filing_event_date`
- `document_url`
- `document_status`

Critical rule:

- Use `filing_accepted_datetime`, not report period date, as availability time.

Purpose:

- Point-in-time filing availability tracking.
- Prevent look-ahead bias.

### `raw_documents`

Stores parsed SEC / earnings text.

Columns:

- `ticker`
- `quarter`
- `accession`
- `document_type`
- `raw_text`
- `clean_text`
- `extraction_ready_flag`
- `quality_fail_reasons`

Purpose:

- Preserve raw evidence.
- Store cleaned text used for extraction.
- Track quality failures before scoring.

Cache rule:

- All SEC documents, SEC metadata, CompanyFacts, filing packets, and earnings exhibit/raw SEC text must live under `/Users/aeternusholdings/Documents/GitHub/AeternusHoldings/cache/sec`.
- Do not create separate SEC cache directories inside project-specific repos.
- Repo-local paths may keep compatibility symlinks only; physical SEC files should have one canonical cache root.
- Market price cache can remain separate from SEC cache.

### `pre_llm_scores`

One row per ticker-quarter.

Columns:

- `ticker`
- `quarter`
- `tradable_date`
- `entry_open`
- `revenue_bucket`
- `pre_llm_fundamental_score`
- `pre_llm_fundamental_bucket`
- `profitability_score`
- `operating_cash_flow_score`
- `fcf_proxy_score`
- `financing_dependence_score`
- `asset_efficiency_score`
- `missing_fields`

Purpose:

- Deterministic pre-LLM scoring.
- Cheap first-pass candidate filter.
- Input into Tier 0-4 classification.

### `post_llm_scores`

One row per ticker-quarter.

Columns:

- `ticker`
- `quarter`
- `post_llm_candidate_flag`
- `post_llm_high_priority_flag`
- `post_llm_demote_flag`
- `post_llm_score_delta`
- `score_addition`
- `causal_change`
- `negative_revision_risk`
- `narrative_delta_bucket`
- `operating_leverage_quality`
- `durability`
- `proof_alignment`
- `driver_summary`
- `bear_case_summary`
- `llm_status`
- `llm_model_version`
- `llm_prompt_version`
- `llm_schema_version`
- `llm_run_datetime`
- `llm_evidence_snippets`
- `llm_extraction_confidence`

Most important fields:

- `post_llm_candidate_flag`
- `causal_change`
- `negative_revision_risk`
- `post_llm_high_priority_flag`
- `post_llm_demote_flag`
- `narrative_delta_bucket`

Purpose:

- Store LLM-derived causal and narrative signals.
- Keep LLM evidence separate from deterministic pre-LLM scoring.
- Make every LLM output reproducible across model and prompt changes.

### `tier_classification`

One row per ticker-quarter.

Columns:

- `ticker`
- `quarter`
- `tier_0_bucket`
- `tier_1_bucket`
- `tier_2_bucket`
- `tier_3_bucket`
- `tier_4_bucket`
- `hp0_high_price_broad`
- `hp1_quality_pullback`
- `hp2_dislocation_momentum_priority`
- `hp2_dislocation_momentum_watch`
- `hp3_large_quality_theme_exception`
- `hp4_score_reacceleration_watch`
- `hp_production_extension`
- `hp_research_extension`
- `extended_candidate_universe`
- `extended_research_universe`
- `tier1_L1_llm_supported`
- `tier1_L2_causal_rerating`
- `tier1_L3_best_balanced`
- `tier1_L4_clean_high_priority`
- `tier1_L5_inflecting`
- `tier1_L6_mid_price_rerater`
- `tier1_L7_clean_non_distressed_rerater`
- `tier2_L1_llm_supported`
- `tier2_L2_causal_rerating`
- `tier2_L3_best_balanced`
- `tier3_L1_llm_supported`
- `tier3_L2_inflecting`
- `tier3_L3_persistent_positive`
- `tier3_L4_persistent_high_priority`
- `tier4_L1_llm_supported`
- `tier4_L2_causal_rerating`
- `tier4_L3_clean_high_priority`
- `hp1_LLM_best`
- `hp2_LLM_best`
- `hp3_theme_confirmed`
- `hp4_LLM_supported`
- `hp_LLM_best`
- `demote_risk_flag`
- `deteriorating_risk_flag`
- `negative_revision_risk_flag`

Purpose:

- Store base tier and post-LLM sub-tier labels.
- Store HP0 high-price tracking label separately from buyable Tier 0-4 labels.
- Keep candidate labeling auditable.
- Separate tier/sub-tier membership from raw scoring fields.

### `candidate_scores`

Stores entry and monitoring scores.

Columns:

- `ticker`
- `quarter`
- `tradable_date`
- `candidate_state`
- `state_updated_at`
- `state_reason`
- `manual_override_flag`
- `manual_override_user`
- `manual_override_datetime`
- `manual_override_reason`
- `manual_override_outcome`
- `manual_override_expiration_date`
- `entry_score_pre_llm_only`
- `entry_score_is_provisional`
- `llm_required_for_full_buy_flag`
- `entry_score_0_100`
- `active_monitoring_score_0_100`
- `dashboard_score_0_100`
- `macro_score_adjustment`
- `macro_regime`
- `theme_score_adjustment`
- `theme_label`
- `theme_confidence`
- `macro_adjusted_entry_score`
- `macro_adjusted_monitoring_score`
- `score_label`
- `monitoring_status`
- `risk_penalty_score`
- `applied_monitoring_delta`
- `scoring_formula_version`
- `tier_rule_version`
- `monitoring_rule_version`
- `last_scored_at`

Recommended definitions:

- `entry_score_0_100`: available at first tradable date; used for research / buy / starter / watchlist / pass decisions.
- `active_monitoring_score_0_100`: available after checkpoint price data exists; used for hold / add / reduce / sell / kill-review decisions.
- `dashboard_score_0_100`: entry score for fresh candidates, monitoring score for active/aged candidates.

Required audit column:

- `applied_monitoring_delta = active_monitoring_score_0_100 - entry_score_0_100`

Purpose:

- Store production rank scores.
- Separate immutable entry score from monitoring-adjusted score.
- Track when scores were last updated.
- Store central candidate lifecycle state for daily and weekly filters.
- Make LLM fallback and provisional scores auditable.
- Make manual overrides explicit and auditable.

### `investment_decisions`

One row per investment decision.

Columns:

- `ticker`
- `quarter`
- `decision_date`
- `decision_type`
- `decision_price`
- `entry_score_0_100`
- `active_monitoring_score_0_100`
- `monitoring_status`
- `investment_decision_score`
- `position_size`
- `primary_thesis`
- `primary_catalyst`
- `valuation_summary`
- `risk_summary`
- `invalidation_trigger`
- `decision_notes`
- `one_sentence_thesis`
- `why_now`
- `main_causal_driver`
- `expected_upside`
- `expected_downside`
- `valuation_view`
- `liquidity_view`
- `macro_theme_view`
- `position_size_rationale`
- `next_review_date`

Decision types:

- `buy`
- `starter`
- `watchlist`
- `pass`
- `sell`
- `reduce`
- `add`

Purpose:

- The model should not just produce scores.
- It should support actual PM decisions.
- Store why a decision was made, not only what the score was.

### `research_memos`

Repeatable memo template for underwriting decisions.

Columns:

- `ticker`
- `decision_date`
- `decision_type`
- `one_sentence_thesis`
- `why_now`
- `main_causal_driver`
- `expected_upside`
- `expected_downside`
- `valuation_view`
- `liquidity_view`
- `macro_theme_view`
- `position_size_rationale`
- `invalidation_trigger`
- `next_review_date`

Purpose:

- Prevent the process from becoming "score says buy."
- Force thesis, risk, valuation, and invalidation into a repeatable format.

### `positions`

One row per active or historical position.

Columns:

- `ticker`
- `quarter`
- `position_open_date`
- `position_close_date`
- `entry_price`
- `actual_entry_date`
- `actual_entry_price`
- `current_price`
- `position_size`
- `cost_basis`
- `unrealized_return_pct`
- `realized_return_pct`
- `return_since_signal_pct`
- `return_since_purchase_pct`
- `days_since_signal`
- `days_since_purchase`
- `status`
- `exit_reason`
- `prior_quarter_entry_score`
- `score_change_qoq`
- `prior_narrative_bucket`
- `narrative_change_qoq`
- `thesis_refresh_status`

Status values:

- `active`
- `reduced`
- `exited`
- `kill_review`

Purpose:

- Track actual portfolio decisions separately from candidate generation.
- Separate investment positions from research candidates.
- Position risk uses return since actual purchase, not only return since signal.

### `price_history`

Daily OHLCV.

Columns:

- `ticker`
- `date`
- `open`
- `high`
- `low`
- `close`
- `volume`
- `dollar_volume`
- `split_factor`
- `dividend_amount`
- `corporate_action_flag`
- `adjusted_close_for_return_calc`
- `split_adjusted_entry_price`

Purpose:

- Real stop-loss simulation.
- Live return monitoring.
- Liquidity checks.

Rules:

- Store raw OHLCV.
- Store split/dividend/corporate-action adjustments.
- Use raw intraday/high/low/open data for execution and stop simulation.
- Use split-adjusted return calculations for historical comparability.
- Never blindly trust vendor `Adj Close` without audit.

### `candidate_monitoring`

One row per active candidate.

Columns:

- `ticker`
- `quarter`
- `tradable_date`
- `entry_price`
- `actual_entry_date`
- `actual_entry_price`
- `days_since_signal`
- `days_since_purchase`
- `signal_age_days`
- `signal_freshness_status`
- `return_10d_pct`
- `return_20d_pct`
- `return_30d_pct`
- `return_60d_pct`
- `current_return_pct`
- `return_since_signal_pct`
- `return_since_purchase_pct`
- `monitoring_status`
- `kill_review_reason`
- `last_price_update`

Purpose:

- Track active candidate health.
- Apply stop / stress / kill-review rules.
- Move stale or failed candidates out of active research.
- Candidate health uses `return_since_signal_pct`.
- Position risk uses `return_since_purchase_pct`.

## Pipeline Flow

The full conceptual flow remains:

```text
SEC filings / earnings docs
        ↓
Pre-LLM fundamental score
        ↓
Tier 0-4 classification
        ↓
Post-LLM causal / narrative scoring
        ↓
Entry score 0-100
        ↓
Research queue / investment decision
        ↓
Buy / starter / watchlist / pass
        ↓
If bought or actively tracked:
Daily price monitoring + stop/kill rules
        ↓
Active monitoring score 0-100
        ↓
Hold / add / reduce / sell / kill-review
```

But production implementation must keep Pipeline A and Pipeline B separate.

## Stage 1: SEC Filings / Earnings Docs

Input documents:

- 8-K earnings releases
- EX-99.1-like earnings exhibits
- Latest available 10-Q or 10-K
- SEC XBRL CompanyFacts where available

Live rule:

- Use only documents filed and available as of the scoring date.
- Do not use filings that were filed after the candidate entry date.
- Cache raw SEC documents locally.
- Track filing date, accession, ticker, quarter, and document quality.

Purpose:

- Build the raw evidence packet for each ticker-quarter.
- Confirm that the candidate has enough filing data to score.

## Stage 2: Pre-LLM Fundamental Score

This stage uses deterministic fields only.

Inputs:

- Revenue bucket
- Profitability score
- Operating cash flow score
- FCF proxy score
- Financing dependence score
- Asset efficiency score

Output:

- `pre_llm_fundamental_score`
- `pre_llm_fundamental_bucket`
- `pre_llm_fundamental_missing_fields`

Live rule:

- No LLM calls.
- No return columns.
- No future filings.

Purpose:

- Create a cheap, scalable first-pass company state score.
- Identify whether the ticker is scoreable before spending LLM budget.

## Stage 3: Exact Tier Rules For Live Use

### Hard Exclusions

Exclude from live tier classification if any of these are true:

```text
pre_llm_fundamental_bucket = "not_scored"
OR missing entry_open
OR missing revenue_bucket
OR extraction quality failure
OR tradable_date before required filings are available
```

Definition of `scored`:

- `pre_llm_fundamental_bucket != "not_scored"`
- `entry_open` is present
- `revenue_bucket` is present
- Extraction quality checks pass
- Required filings are available before or on `tradable_date`

### Tier 0

Rule:

```text
scored
AND entry_open < 25
AND revenue_bucket in [
  "<$100M",
  "$100M-$500M",
  "$500M-$1B",
  "$1B-$2B",
  "$2B-$10B"
]
```

Use as:

- Broad recall feed.

### Tier 1

Rule:

```text
scored
AND entry_open < 15
AND revenue_bucket in [
  "<$100M",
  "$100M-$500M",
  "$500M-$1B",
  "$1B-$2B",
  "$2B-$10B"
]
```

Use as:

- Default production feed.

### Tier 2

Rule:

```text
scored
AND entry_open < 10
AND revenue_bucket in [
  "<$100M",
  "$100M-$500M",
  "$500M-$1B",
  "$1B-$2B",
  "$2B-$10B"
]
```

Use as:

- Compact high-priority feed.

### Tier 3

Rule:

```text
Tier 1
AND pre_llm_fundamental_score <= 0
```

Use as:

- Dislocation / rebound feed.

### Tier 4

Rule:

```text
scored
AND entry_open < 5
AND revenue_bucket in [
  "<$100M",
  "$100M-$500M",
  "$500M-$1B",
  "$1B-$2B",
  "$2B-$10B"
]
```

Use as:

- Aggressive sub-$5 right-tail tag.

## High-Price Re-Rater Extension

This is a parallel tracking module, not a buyable tier.

### HP0 — High-Price Broad Watchlist

Rule:

```text
hp0_high_price_broad =
    pre_llm_fundamental_bucket != "not_scored"
    AND entry_open >= 25
```

Use as:

- Tracking-only high-price re-rater watchlist.
- Do not treat this as a buyable tier.
- Do not include HP0 in `hp_structure_score`.
- Do not trigger LLM extraction from HP0 alone.

### HP1 — Quality Pullback Re-Rater

Rule:

```text
hp1_quality_pullback =
    pre_llm_fundamental_bucket != "not_scored"
    AND entry_open >= 25
    AND entry_qoq_pct <= -20
    AND pre_llm_fundamental_bucket in ["good", "strong"]
```

Use as:

- Higher-price quality pullback / rebound candidate.
- Tracking-only until required downstream confirmations pass.
- Do not treat this as a buyable tier by itself.
- Include HP1 in `hp_structure_score`, not in original Tier 0-4.

Needs before it becomes actionable:

- Post-LLM causal support.
- Macro stabilization.
- Valuation still attractive.

### HP2 — Dislocation Momentum Re-Rater

Priority rule:

```text
hp2_dislocation_momentum_priority =
    pre_llm_fundamental_bucket != "not_scored"
    AND entry_open >= 25
    AND pre_llm_fundamental_score <= 0
    AND entry_qoq_pct >= 20
```

Watch rule:

```text
hp2_dislocation_momentum_watch =
    pre_llm_fundamental_bucket != "not_scored"
    AND entry_open >= 25
    AND pre_llm_fundamental_score <= 0
    AND 15 <= entry_qoq_pct < 20
```

Use as:

- Higher-price weak/dislocated name already being re-rated.
- LITE / WDC / BE-late-stage pattern.
- Tracking-only until downstream research confirms durability.
- Do not treat this as a buyable tier by itself.
- Include HP2 in `hp_structure_score`, not in original Tier 0-4.
- 15-20% watch band should not get production-priority treatment.

### HP3 — Large-Revenue Theme-Leader Exception

Rule:

```text
hp3_large_quality_theme_exception =
    pre_llm_fundamental_bucket != "not_scored"
    AND entry_open >= 25
    AND revenue_bucket = ">$10B"
    AND pre_llm_fundamental_score >= 8
```

Use as:

- Large-cap / large-revenue theme leader watchlist.
- Catches SNDK / NVDA-type names.
- Tracking-only until required confirmations pass.
- Do not treat this as a buyable tier by itself.
- Include HP3 in `hp_structure_score`, not in original Tier 0-4.

Needs before it becomes actionable:

- Theme confirmation.
- Post-LLM causal support.
- Sector / cohort strength.

### HP4 — Fundamental Reacceleration Watch Tag

Rule:

```text
hp4_score_reacceleration_watch =
    pre_llm_fundamental_bucket != "not_scored"
    AND entry_open >= 25
    AND score_change >= 2
    AND entry_qoq_pct >= 10
```

Use as:

- Watch / ranking tag only.
- Not useful as a standalone rule.
- Useful when LLM also sees causal improvement.
- Do not treat this as a buyable tier by itself.
- Include HP4 in `hp_structure_score`, not in original Tier 0-4.

## Extended High-Price Universes

Production HP extension:

```text
hp_production_extension =
    hp1_quality_pullback
    OR hp2_dislocation_momentum_priority
    OR hp3_large_quality_theme_exception
```

Use:

- Main HP production candidate universe.
- Excludes HP2 watch and HP4 because those are research/watch tags only.

Research HP extension:

```text
hp_research_extension =
    hp1_quality_pullback
    OR hp2_dislocation_momentum_priority
    OR hp2_dislocation_momentum_watch
    OR hp3_large_quality_theme_exception
    OR hp4_score_reacceleration_watch
```

Use:

- Broader HP research universe.
- Includes HP2 watch and HP4 watch/ranking names.

Production feed:

```text
extended_candidate_universe =
    Tier 0
    OR hp1_quality_pullback
    OR hp2_dislocation_momentum_priority
    OR hp3_large_quality_theme_exception
```

Broader research feed:

```text
extended_research_universe =
    Tier 0
    OR hp_research_extension
```

## Repricing Momentum Extension

This is a parallel module after Tier 0-4 and HP classification.

Purpose:

- Catch weak/dislocated names that the market has started re-rating before fundamentals fully improve.
- Force LLM review for repricing names even when entry score is low.

Core principle:

- Weak fundamentals are not always a reject.
- Weak fundamentals plus accelerating market repricing plus causal/theme confirmation is a separate re-rating setup.
- Repricing momentum does not mean chase.
- It means force research, LLM extraction, theme tagging, and underwriting.

Required fields:

- `entry_qoq_pct`
- `prior_entry_qoq_pct`
- `rm1_low_price_dislocation_momentum`
- `rm2_weak_acceleration`
- `rm3_mid_price_dislocation_momentum`
- `rm4_persistent_repricing_wave`
- `repricing_momentum_extension`
- `repricing_momentum_priority`
- `market_repricing_score`
- `force_llm_extraction`

Prior-quarter momentum:

```text
prior_entry_open =
    prior quarter entry_open for same ticker

entry_qoq_pct =
    (entry_open / prior_entry_open - 1) * 100

prior_entry_qoq_pct =
    prior quarter entry_qoq_pct for same ticker
```

No future data is used. This only compares current signal price to prior quarter signal price.

Scored:

```text
scored =
    pre_llm_fundamental_bucket != "not_scored"
    AND entry_open is present
    AND revenue_bucket is present
```

RM1:

```text
rm1_low_price_dislocation_momentum =
    scored
    AND entry_open < 25
    AND pre_llm_fundamental_score <= 0
    AND entry_qoq_pct >= 20
```

RM2:

```text
rm2_weak_acceleration =
    scored
    AND entry_open < 25
    AND pre_llm_fundamental_bucket = "weak"
    AND entry_qoq_pct >= 20
```

RM3:

```text
rm3_mid_price_dislocation_momentum =
    scored
    AND entry_open >= 15
    AND entry_open < 25
    AND pre_llm_fundamental_score <= 0
    AND entry_qoq_pct >= 20
```

RM4:

```text
rm4_persistent_repricing_wave =
    scored
    AND entry_open < 25
    AND pre_llm_fundamental_score <= 0
    AND entry_qoq_pct >= 20
    AND prior_entry_qoq_pct >= 20
```

Aggregate RM fields:

```text
repricing_momentum_extension =
    RM1 OR RM2 OR RM3 OR RM4

repricing_momentum_priority =
    RM2 OR RM3 OR RM4
```

Use:

- `repricing_momentum_extension` = research feed.
- `repricing_momentum_priority` = buy-underwriting feed.

Market repricing score:

```text
market_repricing_score =
    +6 if pre_llm_fundamental_score <= 0 AND entry_qoq_pct >= 20
    +4 additional if pre_llm_fundamental_score <= 0 AND entry_qoq_pct >= 50
    +4 additional if pre_llm_fundamental_score <= 0 AND entry_qoq_pct >= 100
    +5 if rm4_persistent_repricing_wave
    +5 if adaptive theme evidence is confirmed
    +5 additional if adaptive theme evidence is confirmed AND repricing_momentum_extension

market_repricing_score = min(20, total)
```

Use:

- Gives AXTI-type names credit for market repricing before fundamentals improve.
- Does not create a buy by itself.
- Highest value comes when weak/dislocated repricing is paired with adaptive theme confirmation.

## HP Structure Score

High-price tags do not change the original low-price Tier 0-4 structure score. Instead, the framework creates a separate HP-adjusted entry score.

```text
HP1 quality pullback:                 +15
HP2 dislocation momentum priority:    +18
HP2 dislocation momentum watch:        +8
HP3 large quality/theme exception:    +10
HP4 score reacceleration watch:        +8
```

Calculation:

```text
total_structure_score =
    max(tier_structure_score, hp_structure_score)
```

Entry raw score:

```text
entry_raw_score =
    total_structure_score
    + llm_business_improvement_score
    + fundamental_rerating_score
    + market_repricing_score
    + theme_tailwind_score
    - risk_penalty_score
```

Then:

```text
entry_score_0_100 = clamp(0, 100, entry_raw_score)
```

Use:

- `entry_score_0_100` includes `total_structure_score`, so HP candidates are no longer under-ranked.
- `base_entry_score_0_100` remains available as audit for old Tier 0-4-only structure scoring.

## HP Post-LLM Subtiers

### HP1 LLM Best

Rule:

```text
hp1_LLM_best =
    hp1_quality_pullback
    AND post_llm_candidate_flag = 1
    AND causal_change = 3
    AND negative_revision_risk <= 2
```

Use:

- Best HP1 quality-pullback subset after LLM causal review.

### HP2 LLM Best

Rule:

```text
hp2_LLM_best =
    hp2_dislocation_momentum_priority
    AND post_llm_candidate_flag = 1
    AND causal_change = 3
    AND negative_revision_risk <= 2
```

Use:

- Best HP2 dislocation-momentum priority subset after LLM causal review.

### HP3 Theme Confirmed

Rule:

```text
hp3_theme_confirmed =
    hp3_large_quality_theme_exception
    AND (
        llm_best
        OR theme_active = 1
        OR theme_cohort_strength = 1
        OR theme_leader_or_direct_beneficiary = 1
    )
```

Where:

```text
llm_best =
    post_llm_candidate_flag = 1
    AND causal_change = 3
    AND negative_revision_risk <= 2
```

Use:

- HP3 large-revenue quality/theme names with either LLM causal support or external theme confirmation.

### HP4 LLM Supported

Rule:

```text
hp4_LLM_supported =
    hp4_score_reacceleration_watch
    AND llm_best
```

Use:

- HP4 reacceleration watch names with LLM causal support.

### HP LLM Best

Rule:

```text
hp_LLM_best =
    hp_production_extension
    AND llm_best
```

Use:

- Main HP production universe with strong LLM confirmation.

Live rule:

- Tiers use only current point-in-time inputs.
- Tiers do not use future returns.

Purpose:

- Find the right haystack before applying expensive LLM review.

## LLM Extraction Stop Gate

After Step 3, run LLM extraction before moving to Step 4.

Stop gate:

- Do not create post-LLM subtiers until LLM extraction data exists.
- Do not move to Step 4 if required LLM fields are missing.
- Without LLM extraction, Step 4 cannot run.
- If LLM is delayed or fails, keep the candidate visible through the LLM fallback path.

Required LLM extraction fields:

- `post_llm_candidate_flag`
- `post_llm_high_priority_flag`
- `post_llm_demote_flag`
- `causal_change`
- `negative_revision_risk`
- `narrative_delta_bucket`
- `operating_leverage_quality`
- `durability`
- `proof_alignment`
- `score_addition`
- `driver_summary`
- `bear_case_summary`
- `primary_theme`
- `secondary_themes`
- `theme_tags`
- `theme_role`
- `theme_confidence`
- `theme_driver_type`
- `theme_momentum`
- `theme_evidence`
- `theme_tailwind_score`
- `theme_driver_summary`
- `theme_evidence_summary`

Theme extraction instruction:

- Use adaptive theme classification. Do not hard-code AI / data-center / semicap as permanent themes.
- Identify any macro, sector, product, commodity, infrastructure, technology, or cycle-driven theme that could be causing a re-rating.
- Return generic theme fields: `primary_theme`, `secondary_themes`, `theme_tags`, `theme_role`, `theme_confidence`, `theme_driver_type`, `theme_momentum`, `theme_evidence`, `theme_driver_summary`, and `theme_evidence_summary`.
- Store candidate-theme mappings in `candidate_theme_tags`; one candidate can have multiple themes.
- Maintain editable `theme_taxonomy`, `candidate_theme_tags`, and `theme_cohort_scores` tables.
- Calculate `theme_cohort_strength` point-in-time from candidates in the same theme.
- `theme_tailwind_score` rewards direct exposure to active themes only when paired with causal improvement, repricing momentum, or positive monitoring confirmation.
- Do not use outside knowledge or current market themes.
- Theme alone should not buy the stock. Theme + evidence + causal/repricing confirmation can boost priority.

LLM status values:

- `pending`
- `complete`
- `failed`
- `stale`

Fallback path:

```text
if required LLM fields are missing:
    llm_status = "pending" or "failed"
    candidate_state = "llm_pending"
    entry_score_pre_llm_only = computed
    entry_score_0_100 = null or provisional
    research_priority = "repricing_momentum_watch" if repricing_momentum_extension else "pre_llm_watchlist"
```

Production rule:

- No full buy decision without LLM for Tier 1-4 names unless manually overridden.
- Missing LLM should block post-LLM subtiers, not hide the candidate.
- LLM extraction is not gated by high entry score.
- Any repricing-momentum candidate must receive LLM extraction, even if entry score is low.

Force LLM trigger:

```text
force_llm_extraction =
    Tier 1
    OR Tier 2
    OR Tier 3
    OR Tier 4
    OR hp_production_extension
    OR hp_research_extension
    OR repricing_momentum_extension
    OR repricing_started
    OR repricing_confirmed
```

Historical note:

- Earlier versions skipped LLM for some non-Tier names. That was acceptable for SNDK-style HP gaps before the HP/RM extension existed, but it is no longer the production rule.
- Current rule: Tier 1-4, HP production/research, and RM extension names are all visible to LLM extraction.

RM candidate routing:

```text
if LLM is missing:
    candidate_state = "llm_pending"
    research_priority = "repricing_momentum_watch"

elif repricing_momentum_priority:
    candidate_state = "fundamental_review"

elif repricing_momentum_extension:
    candidate_state = "active_watchlist"
```

Use:

- Any RM candidate routes to at least research/watchlist handling.
- RM priority routes directly to fundamental review list.
- Weaker RM extension routes to active watchlist.

Live rule:

- LLM uses only filing text and evidence available at the time.
- LLM does not see future returns.
- LLM output must remain auditable with evidence snippets.

## Stage 4: Post-LLM Subtiers To Create

Subtiers are created only after LLM extraction passes the stop gate.

### Tier 1 Subtiers

Tier 1-L1: LLM-supported

```text
Tier 1
AND post_llm_candidate_flag = 1
```

Tier 1-L2: causal re-rating

```text
Tier 1
AND causal_change = 3
```

Tier 1-L3: best balanced production subset

```text
Tier 1
AND post_llm_candidate_flag = 1
AND causal_change = 3
AND negative_revision_risk <= 2
```

This is the most important Tier 1 subtier.

Tier 1-L4: clean high-priority

```text
Tier 1
AND post_llm_high_priority_flag = 1
```

Tier 1-L5: inflecting narrative

```text
Tier 1
AND narrative_delta_bucket = "inflecting"
```

Tier 1-L6: mid-price re-rater

```text
Tier 1
AND NOT Tier 2
AND post_llm_candidate_flag = 1
AND causal_change = 3
AND negative_revision_risk <= 2
```

This captures `$10-$15` names that Tier 2 misses.

Tier 1-L7: cleaner non-distressed re-rater

```text
Tier 1
AND NOT Tier 2
AND pre_llm_fundamental_score > 0
AND post_llm_candidate_flag = 1
AND causal_change = 3
AND negative_revision_risk <= 2
```

### Tier 2 Subtiers

Tier 2-L1

```text
Tier 2
AND post_llm_candidate_flag = 1
```

Tier 2-L2

```text
Tier 2
AND causal_change = 3
```

Tier 2-L3

```text
Tier 2
AND post_llm_candidate_flag = 1
AND causal_change = 3
AND negative_revision_risk <= 2
```

This is the best compact LLM-enhanced feed.

### Tier 3 Subtiers

Tier 3-L1

```text
Tier 3
AND post_llm_candidate_flag = 1
```

Tier 3-L2

```text
Tier 3
AND narrative_delta_bucket = "inflecting"
```

Tier 3-L3

```text
Tier 3
AND current score_addition > 0
AND prior quarter score_addition > 0
```

Tier 3-L4

```text
Tier 3
AND post_llm_high_priority_flag = 1
AND prior quarter score_addition > 0
```

This is the persistent positive dislocation tag.

### Tier 4 Subtiers

Tier 4-L1

```text
Tier 4
AND post_llm_candidate_flag = 1
```

Tier 4-L2

```text
Tier 4
AND causal_change = 3
```

Tier 4-L3

```text
Tier 4
AND post_llm_candidate_flag = 1
AND causal_change = 3
AND negative_revision_risk <= 2
```

This is the strongest aggressive right-tail subtier.

### Post-LLM Subtier Flag Rule

Post-LLM subtier flags must be recomputed from the formula definitions above.

Do not carry scoped-tier legacy labels forward as the source of truth.

Reports and filters should rely on formula-clean fields:

```text
post_llm_tier_2_1_flag = Tier 2 AND post_llm_candidate_flag = 1
post_llm_tier_2_2_flag = Tier 2 AND causal_change = 3
post_llm_tier_2_3_flag = Tier 2 AND post_llm_candidate_flag = 1 AND causal_change = 3 AND negative_revision_risk <= 2

post_llm_tier_3_1_flag = Tier 3 AND post_llm_candidate_flag = 1
post_llm_tier_3_2_flag = Tier 3 AND narrative_delta_bucket = "inflecting"
post_llm_tier_3_3_flag = Tier 3 AND current score_addition > 0 AND prior quarter score_addition > 0
post_llm_tier_3_4_flag = Tier 3 AND post_llm_high_priority_flag = 1 AND prior quarter score_addition > 0

post_llm_tier_4_1_flag = Tier 4 AND post_llm_candidate_flag = 1
post_llm_tier_4_2_flag = Tier 4 AND causal_change = 3
post_llm_tier_4_3_flag = Tier 4 AND post_llm_candidate_flag = 1 AND causal_change = 3 AND negative_revision_risk <= 2
```

## Stage 5: Live Scoring

### Entry Score

Use before the candidate has monitoring data.

Formula:

```text
entry_score_0_100 =
tier_structure_score
+ llm_business_improvement_score
+ fundamental_rerating_score
+ market_repricing_score
+ theme_tailwind_score
- risk_penalty_score
```

Current macro/theme handling:

- `theme_tailwind_score` is adaptive and capped at `20`.
- `market_regime_penalty` should remain excluded for now.
- Macro framework will handle market regime later.

Live rule:

- Entry score cannot use `return_10d_pct`, `return_20d_pct`, `return_30d_pct`, `return_60d_pct`, or `return_90d_pct`.
- Entry score cannot use future price action.
- Entry score is available on the first tradable date.

Entry score is used for:

- Research queue.
- Buy decision.
- Starter decision.
- Watchlist / pass decision.

### Active Monitoring Score

Use only after checkpoint price data exists.

Formula:

```text
active_monitoring_score_0_100 =
entry_score_0_100
+ monitoring_adjustment
```

Main monitoring rule:

```text
if return_60d_pct <= -10:
    monitoring_status = "kill_review"
    active_monitoring_score_0_100 = min(entry_score_0_100, 20)
```

Note:

- Consider changing the cap to `10` or `0` later.
- `20` is fine as long as filtering always uses `monitoring_status`.

Active monitoring score is used for:

- Hold.
- Add.
- Reduce.
- Sell.
- Kill-review.
- Stale candidate review.

Boundary rule:

- Active monitoring score is not used to decide whether to research a fresh candidate.

## Stage 5A: Investment Underwriting

Purpose:

- Turn a high-scoring candidate into an actual buy / starter / watchlist / pass decision.

Entry score creates eligibility. It does not automatically create a buy.

Required checks:

1. Score gate: `entry_score_0_100 >= 75` OR `entry_score_0_100 >= 65` with strong downstream override.
2. Catalyst gate: why now?
3. Price gate: current price still attractive vs signal price.
4. Valuation gate: upside/downside still favorable.
5. Liquidity gate: tradable enough for intended size.
6. Risk gate: demote / deteriorating / financing / revision risk understood.
7. Portfolio gate: position size, sector/theme exposure, macro permission.
8. Exit gate: invalidation trigger defined before entry.

AXTI-style PM underwriting path:

```text
force_pm_underwriting =
    repricing_momentum_priority = true
    AND theme_tailwind_score > 0
    AND (
        post_llm_candidate_flag = 1
        OR causal_change = 3
        OR positive_repricing_status = "repricing_confirmed"
    )
```

Use:

- Force PM underwriting / buy-decision review.
- Does not mean automatic buy.
- Routes to `fundamental_review` unless blocked by hard underwriting gates.

RM-specific risk controls:

```text
if repricing_momentum_extension:
    rm_risk_size_multiplier = 1.0

    if financing_dependence_score = -1:
        rm_risk_size_multiplier *= 0.5

    if post_llm_demote_flag = 1:
        rm_risk_size_multiplier *= 0.5

    if entry_qoq_pct >= 100:
        warning = "starter only unless fresh catalyst"

    if current_price_vs_signal > 50:
        warning = "starter or watchlist only unless fresh catalyst"
```

Use:

- AXTI-type moves can become overextended quickly.
- These controls affect sizing / PM review, not the entry signal itself.

Current Price Vs Signal Price Rules:

```text
0% to +15% vs signal:
    normal underwriting

+15% to +30% vs signal:
    require stronger catalyst / valuation support

+30% to +50% vs signal:
    starter only or wait for pullback unless fresh catalyst exists

> +50% vs signal:
    do not buy from old signal without new confirmation

below signal price:
    check whether thesis is intact or monitoring stress is emerging
```

Liquidity / Tradability Gates:

- `minimum_avg_dollar_volume`
- `minimum_market_cap`
- `exchange_allowed`
- `borrowability_flag`, if short/hedge relevant
- `halt_or_delisting_risk_flag`

Rule:

```text
if avg dollar volume < required threshold:
    watchlist only or manual approval required
```

Default `decision_rules.yaml` values should include:

- `min_avg_dollar_volume`
- `min_market_cap`
- `entry_score_buy_threshold`
- `entry_score_research_threshold`
- `price_vs_signal_soft_limit`
- `price_vs_signal_hard_limit`
- `manual_override_allowed_outcomes`

Manual override outcome values:

- `approved_buy`
- `force_watchlist`
- `force_reject`
- `ignore_kill_review`

No-Buy Conditions:

- `monitoring_status = "kill_review"`
- `signal_freshness_status = "expired_signal"`
- LLM required fields missing, unless manual override
- Current price has already exceeded thesis upside
- Liquidity below threshold
- Extraction quality failure
- No identifiable catalyst
- Invalidation trigger undefined

## Stage 6: Daily Pipeline

Run this every trading day after market close.

### Daily Job 1: Update Price History

Fetch daily OHLCV for all:

- Active positions.
- Active watchlist candidates.
- Recent SEC/earnings names.
- Universe names.

Update:

- `current_return_pct`
- `return_10d_pct`
- `return_20d_pct`
- `return_30d_pct`
- `return_60d_pct`
- `days_since_signal`
- `days_since_purchase`
- `signal_age_days`
- `signal_freshness_status`
- `return_since_signal_pct`
- `return_since_purchase_pct`

Signal freshness statuses:

```text
fresh_signal:   0-5 trading days after tradable_date
active_signal:  6-20 trading days
aging_signal:   21-45 trading days
stale_signal:   46-90 trading days
expired_signal: >90 trading days
```

Signal freshness rules:

```text
fresh_signal:
    normal entry process

active_signal:
    still eligible, but check current price vs signal price

aging_signal:
    require price/thesis confirmation before buying

stale_signal:
    no new buy unless there is a refreshed catalyst or new filing

expired_signal:
    archive unless refreshed by new quarter
```

### Daily Job 2: Update Monitoring Status

Rules:

```text
if return_60d_pct <= -10:
    monitoring_status = "kill_review"

elif return_30d_pct <= -15:
    monitoring_status = "midpoint_stress"

elif return_20d_pct <= -20:
    monitoring_status = "early_stress"

elif return_10d_pct <= -20:
    monitoring_status = "early_stress"

elif no checkpoint data exists:
    monitoring_status = "pre_checkpoint"

else:
    monitoring_status = "active_ok"
```

The 60-day rule is the most important one.

Positive monitoring promotion:

```text
repricing_started =
    monitoring_status != "kill_review"
    AND (
        return_20d_pct >= 20
        OR return_30d_pct >= 20
    )

repricing_confirmed =
    monitoring_status != "kill_review"
    AND return_60d_pct >= 30
```

Positive repricing status:

```text
positive_repricing_status = "none"

if repricing_started:
    positive_repricing_status = "repricing_started"

if repricing_confirmed:
    positive_repricing_status = "repricing_confirmed"
```

Important:

- These are not entry signals.
- Do not overwrite `monitoring_status`; keep `positive_repricing_status` separate.
- Example: `monitoring_status = active_ok` and `positive_repricing_status = repricing_confirmed`.
- Use only after candidate is live or on an active watchlist.
- Use to promote to active research, trigger LLM if missing, refresh thesis, or consider starter/add decision.

Monitoring status values:

- `pre_checkpoint`
- `active_ok`
- `early_stress`
- `midpoint_stress`
- `kill_review`
- `expired_signal`

### Daily Job 3: Rescore Active Candidates And Positions

Recompute:

- `active_monitoring_score_0_100`
- `dashboard_score_0_100`
- `score_label`
- `applied_monitoring_delta`
- `monitoring_status`

Important:

- Fresh candidates use `entry_score_0_100`.
- Active / aged candidates use `active_monitoring_score_0_100`.

### Daily Job 4: Produce Daily Report

The daily report should have ten sections.

#### 1. New Candidates

New ticker-quarter candidates added in last 24 hours.

Columns:

- `ticker`
- `quarter`
- `tradable_date`
- `tier`
- `subtiers`
- `entry_score_0_100`
- `score_label`
- `driver_summary`
- `risk_flags`
- `current_price`
- `current_price_vs_signal`

Purpose:

- Most important section for new research and potential new entries.

#### 2. Top New-Entry Research Candidates

Filter:

```text
entry_score_0_100 >= 70
AND candidate_state in ["new_signal", "fundamental_review", "watchlist"]
AND monitoring_status != "kill_review"
```

Sort:

```text
entry_score_0_100 desc
```

Purpose:

- New buy/starter decisions should start here.

#### 3. Top Active Positions / Active Tracked Candidates

Filter:

```text
candidate_state in ["active_position", "starter_position", "active_watchlist"]
AND monitoring_status != "kill_review"
AND active_monitoring_score_0_100 >= 70
```

Sort:

```text
active_monitoring_score_0_100 desc
```

Purpose:

- Hold/add/reduce decisions.
- Not initial entry decisions.

#### 4. Kill-Review Names

Filter:

```text
monitoring_status = "kill_review"
```

Sort:

```text
current_return_pct ascending
```

Purpose:

- These should not remain in the active long candidate list without a decision.

#### 5. Stale / Expired Candidates

Archive candidates after:

- `90` trading days after `tradable_date`.

Exception:

- Do not archive if a new quarter's signal refreshes the thesis.

#### 6. Buy-Decision Candidates

Filter:

```text
candidate_state in ["new_signal", "fundamental_review", "watchlist"]
AND entry_score_0_100 >= 75
AND post_llm_candidate_flag = 1
AND causal_change = 3
AND negative_revision_risk <= 2
AND monitoring_status not in ["kill_review", "expired_signal"]
```

Purpose:

- Short list that requires PM decision today.

#### 7. Aging High-Score Candidates

Filter:

```text
entry_score_0_100 >= 70
AND signal_freshness_status in ["aging_signal", "stale_signal"]
AND investment_decision not in ["buy", "starter", "pass"]
```

Purpose:

- Force a decision or archive.

#### 8. Repricing Momentum Candidates

Filter:

```text
repricing_momentum_extension = true
AND monitoring_status != "kill_review"
```

Columns:

- `ticker`
- `quarter`
- `entry_open`
- `entry_qoq_pct`
- `prior_entry_qoq_pct`
- `pre_llm_fundamental_score`
- `pre_llm_fundamental_bucket`
- `rm1_low_price_dislocation_momentum`
- `rm2_weak_acceleration`
- `rm3_mid_price_dislocation_momentum`
- `rm4_persistent_repricing_wave`
- theme flags
- `entry_score_0_100`
- `market_repricing_score`
- `llm_status`

#### 9. Persistent Repricing Wave Candidates

Filter:

```text
rm4_persistent_repricing_wave = true
AND monitoring_status != "kill_review"
```

Purpose:

- Keep-riding-the-wave list.

#### 10. Positive Repricing Promotion Candidates

Filter:

```text
positive_repricing_status in ["repricing_started", "repricing_confirmed"]
AND monitoring_status != "kill_review"
```

Purpose:

- Catches names that were low-score at entry but started working.

## Stage 7: Weekly Pipeline

Run once per week, ideally over the weekend.

### Weekly Job 1: Refresh Candidate Universe

Output:

- Tier 0 count
- Tier 1 count
- Tier 2 count
- Tier 3 count
- Tier 4 count
- `entry_score >= 70` count
- `active_monitoring_score >= 70` count
- Kill-review count
- New candidate count
- Expired candidate count

Purpose:

- Track whether the candidate pool is expanding or contracting.

### Weekly Job 2: Generate New-Entry Research Queue

Create a file like:

```text
weekly_new_entry_fundamental_review_YYYYMMDD.csv
```

Filter:

```text
candidate_state in ["new_signal", "fundamental_review", "watchlist"]
AND entry_score_0_100 >= 60
AND monitoring_status != "kill_review"
```

Sort by:

```text
entry_score_0_100 desc
```

Suggested sections:

- A+ / A entry candidates
- Tier 1-L3 names
- Tier 2-L3 names
- Tier 3-L4 names
- Tier 4-L3 names
- Demoted but high-entry-score names
- Theme candidates

Purpose:

- Queue for potential new investments.

### Weekly Job 3: Generate Active Position Monitoring Queue

Create a file like:

```text
weekly_active_monitoring_queue_YYYYMMDD.csv
```

Filter:

```text
candidate_state in ["active_position", "starter_position", "active_watchlist"]
```

Sort by:

```text
monitoring_status
active_monitoring_score_0_100 desc
```

Suggested sections:

- Hold candidates
- Add candidates
- Reduce candidates
- Kill-review candidates
- Aging candidates approaching 60d
- Positions with thesis deterioration

### Weekly Job 4: Review Stop/Kill Outcomes

Track:

- New kill-review names this week
- Positions exited due to kill-review
- Watchlist candidates removed due to kill-review
- Names saved by stop logic
- Names that recovered after stress
- False stop count

Purpose:

- Avoid over-tightening stops emotionally.

### Weekly Job 5: Monitor Model Drift

Track by quarter or rolling 90 days:

- Number of candidates
- Share of Tier 4 names
- Share of demoted names
- Share of `causal_change = 3`
- Share of high `negative_revision_risk`
- Average entry score
- Average active monitoring score
- Share of candidates in kill-review

Interpretation:

- If suddenly `70%` of candidates are Tier 4 or demoted, the opportunity set is getting riskier.

## Stage 8: Event-Driven Filing Pipeline

This should run daily.

### Filing Detection

Poll SEC / earnings document sources.

For each ticker-quarter:

- Detect new 8-K earnings release.
- Detect new 10-Q / 10-K.
- Detect exhibits.
- Check extraction readiness.

### Tradable Date Rule

Signal cannot be live until required documents are available.

Definition:

```text
signal_available_datetime =
max(
    earnings 8-K accepted datetime,
    10-Q / 10-K accepted datetime,
    required exhibit accepted datetime
)
```

Then:

```text
tradable_date = next valid market session after signal_available_datetime
```

This is critical for no-forward-looking discipline.

Use the stricter live rule:

```text
tradable_date = next trading day open after signal_available_datetime
```

Store:

- `signal_available_datetime`
- `signal_processed_datetime`
- `tradable_date`
- `entry_open_source`

### Pre-LLM Scoring

Calculate:

- `profitability_score`
- `operating_cash_flow_score`
- `fcf_proxy_score`
- `financing_dependence_score`
- `asset_efficiency_score`
- `pre_llm_fundamental_score`
- `pre_llm_fundamental_bucket`
- `revenue_bucket`

### Tier Classification

Assign:

- `tier_0_bucket`
- `tier_1_bucket`
- `tier_2_bucket`
- `tier_3_bucket`
- `tier_4_bucket`

### LLM Extraction

For Tier 1-4, run post-LLM extraction.

Extract:

- `post_llm_candidate_flag`
- `post_llm_high_priority_flag`
- `post_llm_demote_flag`
- `causal_change`
- `negative_revision_risk`
- `narrative_delta_bucket`
- `operating_leverage_quality`
- `durability`
- `proof_alignment`
- `driver_summary`
- `risk_summary`

### Scoring

Compute:

- `entry_score_0_100`
- `entry_score_label`
- `risk_flags`
- `research_priority`

Then insert into the live candidate table with:

```text
candidate_state = "new_signal"
```

Routing rule:

- If score is high enough, immediately route the name into the new-entry fundamental review list.

### Active Holding Refresh

If ticker already exists in `positions` and a new quarter signal arrives:

- Compare new `entry_score_0_100` to prior quarter entry score.
- Compare new LLM narrative to prior quarter LLM narrative.
- Classify thesis refresh status.

Add / update fields:

- `prior_quarter_entry_score`
- `score_change_qoq`
- `prior_narrative_bucket`
- `narrative_change_qoq`
- `thesis_refresh_status`

Thesis refresh statuses:

- `thesis_improved`
- `thesis_confirmed`
- `thesis_neutral`
- `thesis_weakened`
- `thesis_broken`

Purpose:

- Support hold/add/reduce decisions for existing positions.
- Avoid treating a new quarter for an owned ticker as an unrelated candidate.

## Stage 9: Candidate State Machine

Every candidate should have a lifecycle state and a separate monitoring status.

Candidate states:

- `new_signal`
- `llm_pending`
- `fundamental_review`
- `watchlist`
- `approved_buy`
- `starter_position`
- `active_position`
- `active_watchlist`
- `expired`
- `refreshed_by_new_quarter`
- `manually_rejected`
- `manually_approved`
- `exited`

Monitoring statuses:

- `pre_checkpoint`
- `active_ok`
- `early_stress`
- `midpoint_stress`
- `kill_review`
- `expired_signal`

Example combined states:

```text
candidate_state = active_position
monitoring_status = midpoint_stress

candidate_state = watchlist
monitoring_status = kill_review
```

State transitions:

```text
new_signal -> fundamental_review
new_signal -> llm_pending
llm_pending -> fundamental_review
llm_pending -> manually_rejected

fundamental_review -> approved_buy
fundamental_review -> starter_position
fundamental_review -> watchlist
fundamental_review -> manually_rejected

approved_buy -> active_position
starter_position -> active_position
watchlist -> active_watchlist

active_position -> exited
active_position -> refreshed_by_new_quarter

active_watchlist -> fundamental_review
active_watchlist -> expired

expired -> refreshed_by_new_quarter
```

Rule:

- Do not keep old stale candidates mixed with current fresh candidates.
- Price/risk condition belongs in `monitoring_status`, not `candidate_state`.

## Stage 10: Output Files To Generate

### Daily Outputs

Generate:

- `outputs/daily/YYYYMMDD_new_candidates.csv`
- `outputs/daily/YYYYMMDD_new_entry_fundamental_review.csv`
- `outputs/daily/YYYYMMDD_top_active_positions.csv`
- `outputs/daily/YYYYMMDD_kill_review.csv`
- `outputs/daily/YYYYMMDD_score_changes.csv`
- `outputs/daily/YYYYMMDD_buy_decision_candidates.csv`
- `outputs/daily/YYYYMMDD_aging_high_scoring_candidates.csv`

### Weekly Outputs

Generate:

- `outputs/weekly/YYYYMMDD_new_entry_fundamental_review.csv`
- `outputs/weekly/YYYYMMDD_active_monitoring_queue.csv`
- `outputs/weekly/YYYYMMDD_candidate_dashboard.csv`
- `outputs/weekly/YYYYMMDD_risk_review.csv`

### Live Dashboard

A simple dashboard should show:

- `ticker`
- `company_name`
- `quarter`
- `candidate_state`
- `tradable_date`
- `days_since_signal`
- `signal_freshness_status`
- `days_since_purchase`
- `tier`
- `subtiers`
- `entry_score_0_100`
- `active_monitoring_score_0_100`
- `dashboard_score_0_100`
- `macro_adjusted_entry_score`
- `macro_adjusted_monitoring_score`
- `score_label`
- `monitoring_status`
- `current_price`
- `current_price_vs_signal`
- `current_return_pct`
- `return_since_signal_pct`
- `return_since_purchase_pct`
- `return_10d_pct`
- `return_20d_pct`
- `return_30d_pct`
- `return_60d_pct`
- `driver_summary`
- `risk_summary`
- `llm_status`
- `investment_decision`
- `position_status`

## Stage 11: Practical Research Workflow

### Daily

Start with fresh or unowned candidates:

```text
candidate_state in ["new_signal", "fundamental_review", "watchlist"]
AND entry_score_0_100 >= 70
AND monitoring_status != "kill_review"
```

These are top-priority new-entry research candidates.

Then separately review:

- New Tier 1-L3
- New Tier 2-L3
- New Tier 3-L4
- New Tier 4-L3

For active positions, use a separate queue:

```text
candidate_state in ["active_position", "starter_position", "active_watchlist"]
AND monitoring_status != "kill_review"
```

Sort active names by:

```text
active_monitoring_score_0_100 desc
```

This queue is for hold/add/reduce decisions, not initial entry.

### Weekly

Use this as the main new-entry fundamental review list:

```text
candidate_state in ["new_signal", "fundamental_review", "watchlist"]
AND entry_score_0_100 >= 60
AND monitoring_status != "kill_review"
```

Group by:

- Sector/theme
- Tier
- LLM driver
- Risk flags

Your downstream system can then filter on:

- Current price
- Liquidity
- Valuation
- Theme
- Macro
- Catalyst
- Position sizing

Use this as the active monitoring queue:

```text
candidate_state in ["active_position", "starter_position", "active_watchlist"]
```

Group by:

- `monitoring_status`
- `days_since_signal`
- `active_monitoring_score`
- Risk flags
- Position size

## Stage 12: How To Handle Macro Later

Since there is already a macro framework, keep the equity scoring clean.

Add a later-stage adjustment for new entries:

```text
macro_adjusted_entry_score =
entry_score_0_100
+ macro_score_adjustment
```

Add a later-stage adjustment for existing positions or active candidates:

```text
macro_adjusted_monitoring_score =
active_monitoring_score_0_100
+ macro_score_adjustment
```

Macro system can adjust by:

- Market regime
- Sector risk
- SPY drawdown
- Rate environment
- Credit stress
- Liquidity regime

Rule:

- Do not bake macro into the core stock score yet.

## Stage 13: Minimal Implementation Plan

Build later with this structure:

```text
src/
  ingest/
    prices.py
    filings.py
    documents.py

  features/
    pre_llm_scores.py
    tiers.py
    post_llm_scores.py
    scoring.py
    monitoring.py
    investment_decisions.py
    signal_freshness.py
    underwriting.py
    thesis_refresh.py

  pipeline/
    run_daily.py
    run_weekly.py
    run_on_new_filing.py

  reporting/
    daily_report.py
    weekly_report.py
    investment_memo.py

  config/
    tier_rules.yaml
    scoring_weights.yaml
    monitoring_rules.yaml
    decision_rules.yaml
    schema_versions.yaml

  tests/
    test_tier_rules.py
    test_scoring_formula.py
    test_no_forward_looking.py
    test_monitoring_rules.py
    test_state_machine.py
    test_entry_vs_monitoring_separation.py
    test_signal_freshness.py
    test_underwriting_gates.py
    test_corporate_action_returns.py
    test_llm_fallback.py
    test_thesis_refresh.py
    test_pipeline_a_no_monitoring_leakage.py
```

Most important tests:

- Tier columns match rules.
- `entry_score` never uses return columns.
- New-entry fundamental review list uses `entry_score`, not monitoring score.
- Monitoring score uses return columns only after candidate is live.
- `tradable_date` is after all required filings.
- `kill_review` caps active monitoring score.
- `not_scored` rows never enter tiers.
- Fresh candidates can enter fundamental review list immediately.
- LLM missing blocks subtiers and full buy but keeps the candidate visible.
- Pipeline A cannot read return columns or the `candidate_monitoring` table.
- Candidate state and monitoring status remain separate.
- Actual position return uses actual purchase price.
- Candidate health uses signal return.
- Corporate-action-adjusted returns do not blindly trust vendor `Adj Close`.
- Signal freshness blocks stale/expired buy decisions unless refreshed.
- Active holding refresh classifies thesis improved/confirmed/neutral/weakened/broken.

## Stage 14: Live Screening Decision Tree

Use this operationally.

### 1. Is The Company Scored And Eligible?

Decision:

```text
No  -> reject/manual review
Yes -> continue
```

### 2. Is It Tier 1 Or Better?

Decision:

```text
No  -> broad watchlist only
Yes -> continue
```

### 3. Does It Have LLM Causal Support?

Rule:

```text
post_llm_candidate_flag = 1
AND causal_change = 3
AND negative_revision_risk <= 2
```

Decision:

```text
Yes -> high-priority research
No  -> lower priority unless theme override
```

### 4. Is Entry Score High Enough?

Decision:

```text
entry_score >= 75 -> immediate investment underwriting
entry_score 65-74 -> fundamental review list / possible starter
entry_score 50-64 -> watchlist
entry_score < 50  -> low priority
```

### 5. Does Downstream Investment Review Confirm?

Checklist:

- Catalyst clear?
- Valuation attractive?
- Current price still reasonable?
- Liquidity acceptable?
- Macro/theme supportive?
- Position size appropriate?
- Invalidation defined?

Decision:

```text
Yes -> Buy / starter
No  -> watchlist / pass
```

No-buy conditions:

- `monitoring_status = "kill_review"`
- `signal_freshness_status = "expired_signal"`
- LLM required fields missing, unless manual override
- Current price has already exceeded thesis upside
- Liquidity below threshold
- Extraction quality failure
- No identifiable catalyst
- Invalidation trigger undefined

### 6. If Bought Or Actively Tracked

Rule:

- Monitor daily.

### 7. Has Monitoring Status Become Kill Review?

Decision:

```text
Yes -> remove from active long candidate list / review exit
No  -> continue holding or tracking
```

### 8. Should We Hold / Add / Reduce?

Use:

- `active_monitoring_score`
- Thesis status
- Price action
- Macro framework
- Valuation
- Portfolio risk

## Bottom Line

Daily:

- Update prices.
- Update monitoring status.
- Refresh active monitoring scores.
- Produce new-entry / active / kill-review lists.

Event-driven:

- When new filings arrive, compute pre-LLM score.
- Assign tiers.
- Run LLM extraction.
- Compute entry score.
- Send to fundamental review list immediately.

Weekly:

- Produce new-entry fundamental review list.
- Produce active monitoring queue.
- Review risk.
- Monitor model drift.

Production role:

- Tier rules find the haystack.
- LLM causal scoring ranks the needles.
- Entry score sends fresh names to research and possible buy decisions.
- 60-day kill-review removes failed waves after they are live.
- Downstream macro/theme/valuation system makes the final investment decision.

## Production Guardrails

- Do not use future returns in candidate generation.
- Do not use future returns in LLM extraction.
- Do not use future returns in entry score.
- Store raw OHLCV and corporate-action fields.
- Never blindly trust vendor `Adj Close` without audit.
- Use split-adjusted returns for historical comparability.
- Cache SEC filings and price data.
- Keep LLM evidence auditable.
- Track missing fields explicitly.
- Separate entry score from active monitoring score.
- Separate `candidate_state` from `monitoring_status`.
- Track signal returns separately from actual position returns.
- Keep candidates visible when LLM is pending or failed.
- Apply macro regime adjustments later through the separate macro framework.
