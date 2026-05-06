# AKG Theme Acceleration Upgrade

## Status

Planning source of truth. Use this document to verify implementation completeness before marking the upgrade done.

## Verdict

Reject the prior standalone “Pipeline 0” plan as written.

Do not build:

- standalone `src/` discovery stack
- separate Parquet theme universe tables
- Reddit/GDELT/policy ingestion in v1
- standalone market radar module
- separate forced-ingestion queue

Build an AKG-native upgrade instead.

## Goal

Catch theme-relevant names that current universe/scoring can miss, especially:

- AXTI-type hidden suppliers: theme edge + emergence/price repricing
- GLW-type filing-confirmed acceleration: filing shows theme-driven segment growth/guidance/margins/customer wins/capacity expansion before price/fundamentals fully screen well

This upgrade must not create buy signals. It creates rescan/research-visibility events only.

## Architecture

Existing filing / analysis / LLM output
→ extract theme acceleration fields
→ write theme acceleration signal to AKG node
→ mark node as rescan/emergence/research-visible candidate
→ existing DealFlowPipeline picks it up
→ research queue / fundamental framework

AKG remains the source of truth.

## Implementation checklist

### 1. Theme acceleration extraction fields

Add these fields to existing filing/fundamental/LLM analysis outputs:

- `primary_theme`
- `secondary_themes`
- `theme_role`
- `theme_confidence`
- `theme_driver_type`
- `theme_momentum`
- `filing_theme_growth_flag`
- `filing_theme_guidance_flag`
- `filing_theme_margin_flag`
- `filing_theme_customer_win_flag`
- `filing_theme_capacity_expansion_flag`
- `theme_evidence`
- `theme_acceleration_score`

Scoring:

- `+5` growth
- `+5` guidance
- `+3` margin
- `+3` customer win
- `+3` capacity expansion
- `theme_acceleration_score = min(15, total)`

Evidence rule:

- No evidence snippets → no high score.
- Missing evidence should cap or zero the score.

### 2. LLM prompt update

Add a Theme Acceleration section:

Return:

- primary theme
- secondary themes
- theme role
- theme confidence
- theme driver type
- theme momentum
- whether filing shows theme-driven revenue/segment growth
- whether filing shows theme-driven guidance
- whether filing shows theme-driven margin improvement
- whether filing shows theme-driven customer wins
- whether filing shows theme-driven capacity expansion
- evidence snippets

Constraint:

- Require filing evidence snippets.
- Do not infer acceleration from market narrative alone.

### 3. AKG node fields and methods

Add/support AKG node fields:

- `signal_theme_acceleration_score`
- `signal_theme_acceleration_updated`
- `primary_theme`
- `secondary_themes`
- `theme_role`
- `theme_confidence`
- `theme_driver_type`
- `theme_momentum`
- `theme_evidence`
- `theme_acceleration_rescan_flag`
- `theme_acceleration_reason`

Add methods:

- `update_theme_acceleration_signal(ticker, payload)`
- `mark_theme_acceleration_rescan(ticker, reason)`
- `get_theme_acceleration_candidates(as_of_date)`

### 4. Route into existing rescan path

Rules:

- If `theme_acceleration_score >= 5`, set `theme_acceleration_rescan_flag = true`.
- If `theme_acceleration_score >= 10` and `theme_confidence in ["medium", "high"]`, promote to research visibility/rescan.
- Never create approved buy/trade/order state.

Use current AKG universe/rescan/dealflow path. Do not add a separate forced-ingestion table.

### 5. Theme heatmap report

Create:

`eval_results/deal_flow/theme_heatmap_<date>.json`

Include:

- `theme`
- `linked_ticker_count`
- `ticker_count_with_emergence`
- `ticker_count_with_price_momentum`
- `ticker_count_with_filing_theme_acceleration`
- `average_theme_acceleration_score`
- `top_evidence_snippets`
- `top_tickers`

Purpose: PM visibility, not scoring/buy approval.

### 6. Theme aliases config

Do not refactor all themes at once.

Add:

`config/theme_aliases.yaml`

Initial examples:

```yaml
ai_data_center:
  aliases:
    - AI data center
    - gen AI infrastructure
    - hyperscaler capex
    - optical networking
    - 800G
    - 1.6T
    - photonics
    - data center power

optical_networking:
  aliases:
    - optical communications
    - silicon photonics
    - CPO
    - high-speed optical
    - transceiver
```

Wire aliases into existing theme detection / AKG theme nodes incrementally.

## Regression tests

### AXTI-type hidden supplier test

Purpose:

- AKG supply-chain/theme/emergence/breakout path should promote hidden supplier to research visibility.

Expected:

- AXTI-like node with theme edge + price/emergence signal becomes rescan candidate.

### GLW-type filing acceleration test

Purpose:

- Filing theme acceleration promotes ticker even without strong price momentum.

Expected:

- Filing evidence shows theme-driven segment growth.
- `theme_acceleration_score >= 5`.
- AKG node gets `theme_acceleration_rescan_flag`.
- Ticker enters research visibility/rescan.

### No-buy-signal test

Purpose:

- Theme acceleration cannot create approved buy/order/trade state.

Expected:

- Only rescan/research visibility fields change.

### No-forward-looking test

Purpose:

- Filing after as-of date cannot update earlier AKG theme acceleration state.

Expected:

- `signal_theme_acceleration_updated <= as_of_date` for PIT tests.

### Evidence-required test

Purpose:

- LLM cannot assign high theme acceleration without evidence snippet.

Expected:

- Missing evidence caps or zeros score.

## What stays out of v1

- GDELT broad ingestion
- Reddit ingestion
- policy feed ingestion
- new market radar module
- new Parquet source-of-truth tables
- separate forced ingestion queue

Future versions may add policy/GDELT as AKG causal-event nodes only if targeted and evidence-filtered.

## Acceptance criteria

Implementation is complete only when:

- extraction fields exist in filing/fundamental output
- theme acceleration score is computed deterministically
- evidence requirement is enforced
- AKG writes/reads theme acceleration fields
- rescan/research visibility uses existing AKG/dealflow route
- heatmap report is generated
- all regression tests above pass
- no code path creates buy/trade/order state from theme acceleration alone
