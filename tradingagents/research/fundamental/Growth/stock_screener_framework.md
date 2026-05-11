# Fundamental Stock Screener Framework

This file is the source of truth for the fundamental stock screener and picker. Update this file first when the framework changes.

## Goal

Identify which ticker deserves limited capital at each decision point.

The framework is not trying to answer “is this company good?” It is trying to answer:

- What changed?
- Is the change bullish or bearish?
- Is the change durable enough to matter?
- Is this ticker more attractive than the other candidates right now?

## Current Pipeline

```text
SEC 8-K / EX-99.1
-> sec-parser text + tables
-> event shock engine
-> latest no-lookahead venture score
-> convexity + risk + cyclicality monitor
-> quarterly top-1 capital priority pick
```

## Provenance Map

This section defines what is Python-derived, LLM-derived, or manually/proxy-derived.

### Python-Derived

These steps are deterministic code outputs.

- SEC filing discovery from SEC submissions API.
- 8-K / EX-99.1 raw HTML fetch.
- SEC filing cache writes.
- `sec-parser` semantic element extraction.
- HTML table extraction with pandas.
- Edgartools context capture when enabled.
- 8-K to 10-Q/K date matching.
- return calculations from next trading day open.
- event shock baseline construction.
- event shock counts and deltas.
- `demand_shock_score`.
- `risk_shock_score`.
- `event_shock_bucket`.
- `cyclicality_penalty`.
- `cyclicality_gate`.
- venture score join using latest filing date at/before decision date.
- capital priority score.
- quarterly top-1 ranking.
- fundamental summary metrics.

### LLM-Derived / In-Session Extraction

These fields are currently generated through schema-style extraction from `sec-parser` text/tables and then consumed by Python scoring.

Current implementation uses local/in-session extraction JSON files, not a production OpenAI API call.

LLM-style extracted fields:

- reported period text
- period end date
- reported revenue
- reported revenue YoY
- reported revenue QoQ
- gross margin
- non-GAAP gross margin
- forward revenue guidance if present
- forward guidance low/high/midpoint if present
- forward non-GAAP gross margin if present
- qualitative demand signal
- qualitative wave signal
- qualitative margin signal
- qualitative risk signal
- qualitative customer signal
- evidence quotes
- missing fields
- confidence

Important guardrail:

If LLM-style extraction marks a required field missing, Python does not backfill it with regex guesses.

### Why These Fields Need LLM-Style Extraction

The SEC does not require EX-99.1 earnings releases to use a standardized schema. Companies use different wording, table layouts, period labels, non-GAAP formats, and guidance styles. `sec-parser` helps structure text and tables, but it does not understand which table row is the current quarter versus full year, which number is guidance versus historical actual, or whether a qualitative statement is a real business signal versus boilerplate.

Python still validates and scores extracted values, but LLM-style extraction is needed to identify the correct facts from messy disclosures.

Field rationale:

- `reported period text`: Companies phrase periods differently, such as “fourth quarter and full year ended,” “quarter ended,” “fiscal Q2,” or “second quarter fiscal 2026.” Python can match simple patterns, but an LLM-style extractor is better at selecting the actual reporting period from titles, headings, and management commentary without confusing conference call dates or prior-year comparison periods.

- `period end date`: The same filing can contain filing date, report date, quarter end date, fiscal year dates, dividend record dates, and conference call dates. Python regex can grab the wrong date. LLM-style extraction identifies the date tied to the reported operating period.

- `reported revenue`: Revenue appears in headlines, bullets, GAAP tables, non-GAAP tables, segment tables, full-year sections, prior-year comparisons, and reconciliation tables. Python can pick the wrong value, especially full-year revenue instead of current-quarter revenue. LLM-style extraction selects the current reported quarter/company-level revenue.

- `reported revenue YoY`: Some companies state YoY directly, some provide current and prior-year values, some say “up from a year ago,” some show it only in a table. Python can calculate YoY after the correct values are identified, but LLM-style extraction is needed to identify the correct comparison basis.

- `reported revenue QoQ`: QoQ may be stated as “sequentially,” “from the previous quarter,” or only implied by current and prior-quarter table columns. Python can calculate once columns are identified, but LLM-style extraction is needed to distinguish prior quarter from prior year and full-year columns.

- `gross margin`: Gross margin may appear as GAAP, product gross margin, segment gross margin, full-year gross margin, or reconciliation gross margin. Python cannot reliably know which one is company-level current-quarter GAAP gross margin without semantic context.

- `non-GAAP gross margin`: Non-GAAP metrics are especially inconsistent. They may appear in a non-GAAP table, outlook section, reconciliation, or bullet list. Python can confuse reported non-GAAP margin with guidance non-GAAP margin or reconciliation adjustments. LLM-style extraction is needed to assign the value to the correct section and period.

- `forward revenue guidance if present`: Many companies do not provide next-quarter revenue guidance. Others provide annual guidance, capex guidance, “outlook,” or prior outlook comparisons. Python regex can accidentally treat annual revenue guidance or prior outlook as next-quarter revenue guidance. LLM-style extraction decides whether forward revenue guidance is actually present and what kind it is.

- `forward guidance low/high/midpoint if present`: Guidance may be a range, midpoint, “plus or minus,” annual target, fiscal-year range, or non-revenue outlook. Python can compute midpoint, but only after the correct low/high values and time horizon are identified. LLM-style extraction avoids mixing annual and quarterly ranges.

- `forward non-GAAP gross margin if present`: Forward margin guidance often appears in an outlook block and uses “plus or minus basis points,” “range,” or “approximately.” Python can parse numbers, but LLM-style extraction distinguishes forward margin from reported margin and GAAP from non-GAAP.

- `qualitative demand signal`: Demand language can be bullish, bearish, or boilerplate. Examples include “strong demand,” “demand diminished,” “customer demand,” and forward-looking risk boilerplate. Python keyword counts cannot reliably separate real operating demand from legal risk language. LLM-style extraction selects the sentence that reflects actual business demand.

- `qualitative wave signal`: “AI,” “cloud,” “data center,” “power,” “optical,” or “capacity” can be central to the thesis or just generic market language. LLM-style extraction identifies whether the filing ties the company to a relevant demand wave in a business-specific way.

- `qualitative margin signal`: Margin commentary can describe improvement, degradation, mix, cost reduction, utilization, tariffs, inventory charges, or one-time adjustments. Python terms alone cannot reliably classify whether margin signal is structurally bullish or temporary/noisy.

- `qualitative risk signal`: Risk can appear in boilerplate forward-looking statements or in actual operating commentary. Python overcounts legal boilerplate. LLM-style extraction isolates the risk that management is actually emphasizing in the earnings release.

- `qualitative customer signal`: Customer language may refer to actual wins, existing demand, customer concentration risk, unnamed hyperscaler, channel partners, or general customer boilerplate. LLM-style extraction identifies the business-relevant customer signal and avoids counting generic mentions.

- `evidence quotes`: Every extracted value or qualitative signal needs a source quote. Python can store snippets, but LLM-style extraction chooses the most relevant support sentence/table row for each field. This makes audit and debugging possible.

- `missing fields`: Missingness is a judgment, not just a blank regex match. A field can be absent, present only annually, present only as capex, or present in a non-comparable format. LLM-style extraction marks true missing fields so Python does not guess.

- `confidence`: Confidence depends on table clarity, text ambiguity, conflicting values, missing context, and whether evidence supports the extraction. Python can compute crude coverage checks, but LLM-style extraction can assign uncertainty based on semantic ambiguity.

Python responsibilities after extraction:

- validate numeric types
- compute midpoint from extracted low/high
- compute scores deterministically
- enforce no-lookahead
- reject scoring if required extracted fields are missing
- preserve evidence and missing-field flags

### Manual / Proxy-Derived

These are framework assumptions or placeholders that should eventually be replaced with real data.

- convexity proxy by ticker class
- current capital priority weights
- current cyclicality thresholds
- current event shock bucket thresholds
- decision to use quarterly top-1 as default

Manual/proxy items must be monitored and updated only through this file.

### Validation-Only Fields

These fields are never used as scoring inputs.

- `return_10d_pct`
- `return_20d_pct`
- `return_30d_pct`
- `return_60d_pct`
- `return_90d_pct`

Returns are used only after the decision for validation.

## Core Philosophy

Use 8-Ks as event/tone/narrative shock detectors.

Use 10-Q/K venture scoring as durability/context.

Use fundamental ranking to choose between tickers such as `BE`, `NVDA`, `AAOI`, `MU`, `LITE`, `GOOGL`, and `SNDK`.

## Why 8-Ks Matter

8-Ks are not consistent enough for universal numeric scoring. Many companies do not provide next-quarter revenue guidance.

8-Ks are useful because they are usually the first official earnings document and can reveal event shocks:

- demand acceleration
- new customer/order/backlog signal
- AI/data center/cloud/power/capacity inflection
- margin improvement
- shortfall
- inventory issue
- export restriction
- weak demand
- management tone shift

## Why 10-Q/K Matters

10-Q/K filings provide more durable, apples-to-apples business context.

Current use:

- `venture_score`
- `wave_exposure`
- `asymmetric_upside`
- `fundable_scaling`
- `wave_torque_operating_leverage`
- penalties such as `false_promise_penalty`

## Current Files

Scripts:

- `Growth/earnings_8k_sec_parser_pipeline.py`
- `Growth/create_in_session_llm_earnings_extractions.py`
- `Growth/event_shock_engine.py`
- `Growth/fundamental_event_picker.py`
- `Growth/quarterly_filter_tester.py`

Core outputs:

- `Growth/earnings_8k_sec_parser/manifest.csv`
- `Growth/earnings_8k_sec_parser/event_shock_scores.csv`
- `Growth/earnings_8k_sec_parser/quarterly_filter_audit.csv`
- `Growth/earnings_8k_sec_parser/fundamental_candidates.csv`
- `Growth/earnings_8k_sec_parser/fundamental_picks.csv`
- `Growth/earnings_8k_sec_parser/fundamental_summary.csv`

Framework doc:

- `Growth/fundamental_stock_screener_framework.md`

## Event Shock Engine

Script:

```text
Growth/event_shock_engine.py
```

Purpose:

Compare each ticker only to its own prior earnings 8-Ks.

The engine does not compare `NVDA` language directly to `BE` or `GOOGL`. This prevents a large-cap AI company from dominating simply because it always talks about AI.

Baseline:

- prior same-ticker filings
- default baseline window: `4`
- minimum history: `2`

Main outputs:

- `event_shock_score`
- `event_shock_bucket`
- `demand_shock_score`
- `risk_shock_score`
- `mixed_high_shock`
- `positive_delta_drivers`
- `negative_delta_drivers`
- `new_driver_detected`
- `fading_driver_detected`
- `risk_delta`
- `novelty_score`
- `numeric_delta_score`
- `evidence_snippets`
- `cyclicality_penalty`
- `cyclicality_delta`

## Event Shock Buckets

`positive_shock`

Clean positive event shock. Demand/novelty/numeric delta stronger than risk.

`negative_shock`

Risk/deceleration dominates. Usually avoid unless other framework layers explain why the risk is temporary.

`mixed_high_shock`

Both demand shock and risk shock are high. Important event, but contaminated.

Example: `NVDA 2025-05-28` had strong AI infrastructure demand and Blackwell/full-scale production, but also H20/export/inventory risk.

`neutral`

No strong event delta.

`insufficient_history`

Not enough same-ticker prior 8-Ks to build baseline.

## Capital Priority Picker

Script:

```text
Growth/fundamental_event_picker.py
```

Default behavior:

- quarterly rebalance
- top `1` ticker per quarter
- no lookahead
- venture filing date must be `<= decision_date`

Capital priority combines:

- `demand_shock_score`
- `event_shock_score`
- `venture_score`
- `wave_exposure`
- `asymmetric_upside`
- `fundable_scaling`
- `wave_torque_operating_leverage`
- convexity proxy
- `risk_shock_score`
- `false_promise_penalty`
- `incumbent_saturation_penalty`
- cyclicality monitor/tiebreaker

## No-Lookahead Rules

Required:

- Use only filings available by `decision_date`.
- Use only prior same-ticker 8-Ks for baseline.
- Use latest venture score with `filing_date <= decision_date`.
- Returns are validation only, never input.
- Driver maps must be learned from past/current text only, never future filings.

## Cyclicality Monitor

Purpose:

Flag cyclicality risk without hard-filtering convex winners.

Detected from generic filing language:

- pricing / ASP pressure
- inventory digestion or correction
- supply-demand balance
- utilization / fab / wafer
- DRAM / NAND / memory
- commodity / cyclical / downturn/upturn

Current rule:

```text
cyclicality_penalty >= 3
AND NOT (venture_score >= 14 AND demand_shock_score >= 8)
=> cyclicality_gate = True
```

Current action:

- Monitor only.
- Tiny `-1` tiebreaker penalty.
- Not a hard filter.

Reason:

AAOI 2023-05 was flagged by cyclicality logic but later returned `+311.88%` over 90 days. This proves cyclicality can mark real convex winners, so it should not be used as a hard exclusion yet.

## Current Fundamental Result

Current universe:

- `AAOI`
- `BE`
- `GOOGL`
- `LITE`
- `MU`
- `NVDA`
- `SNDK`

Current run:

- `131` candidates
- `19` quarterly top-1 picks
- pick mix: `AAOI 7`, `MU 4`, `NVDA 4`, `BE 4`

Current performance:

- avg 90d return: `+32.82%`
- 90d win rate: `55.56%`

Ticker performance among picks:

- `AAOI`: avg 90d `+33.78%`, win rate `71.43%`
- `BE`: avg 90d `+96.84%`, win rate `75.00%`
- `NVDA`: avg 90d `+15.29%`, win rate `66.67%`
- `MU`: avg 90d `-19.74%`, win rate `0.00%`

## Current Key Learnings

BE and GOOGL do not fit a next-quarter-guidance scoring framework. They need event shock/narrative analysis instead.

AAOI and BE show strongest convexity in current test set.

NVDA can still be selected correctly during AI acceleration windows, but large-cap convexity is lower.

MU remains weak in current picker. Do not add an MU-specific penalty. Use generic cyclicality monitoring and add more tickers before hardening thresholds.

AAOI 2023-05 is a caution case. Cyclicality flags can mark real future winners.

## Current Caveats

The framework is V1.

Thresholds are not final.

Universe is still small.

Current convexity proxy is manually approximated by ticker class. Do not use market cap as an initial historical filter until point-in-time market cap is solved. First-stage universe gating should stay permissive and yes/no.

LLM extraction is currently represented by local/in-session schema outputs, not a production OpenAI API pipeline.

Event shock scoring is deterministic and inspectable but still noisy.

## Filter Framework

The framework cannot extract and score every SEC-reporting company. We need an initial filter that is broad enough to catch needles but narrow enough to run repeatedly.

The filter framework is not final. It must be tested one quarter at a time before becoming a hard production rule.

### Universe Source: AKG Seed

The first production step is to create a broad ticker universe. We can leverage the existing AKG work from:

```text
/Users/aeternusholdings/Documents/AeternusAgents-codex/
```

Useful AKG files:

- `eval_results/control/knowledge_graph.json`: current AKG graph with roughly `5,300` company nodes.
- `tradingagents/dealflow/sources/universe_seeder.py`: seed builder using Dow, static ETFs, growth watchlist, S&P 500, NASDAQ list, Russell 2000/IWM holdings, and ARK holdings.
- `tradingagents/dealflow/akg_universe.py`: tiered AKG universe builder using anchors, supply-chain neighbors, scout/emergence tiers, dark nodes, and recall channels.
- `tests/test_universe_seeder.py`: tested behavior for fetching, sanitizing, deduping, and seeding nodes.

How to use AKG here:

- Treat AKG as the broad seed universe, not the final filtered universe.
- Import/export AKG nodes into this project as candidate tickers with `seed_sources`, `asset_class`, `sector_gics`, `liquidity_score`, and AKG tier metadata when available.
- Cross-check every AKG ticker against SEC CIK mapping before SEC filing work.
- Cross-check every AKG ticker against raw Yahoo price cache before price/liquidity viability checks.
- Run LLM only after AKG + SEC + price/liquidity + filing availability checks.

AKG limitations for this framework:

- AKG contains ETFs, commodity proxies, and broad anchors; this screener mostly needs tradable U.S. common stocks.
- AKG seed sources are market/universe sources, not SEC filing validation.
- AKG liquidity can be stale or percentile-style; this screener should recompute raw price/liquidity features from cached Yahoo OHLCV.
- AKG current universe is not point-in-time for historical fundamental unless we snapshot/version it by decision date.

### Fundamental Convexity Truth

A `$1B` company has a much higher chance of becoming a `10x` than a `$1T` company.

This does not mean small companies are automatically better. It means capital priority must consider upside capacity. A large company can be a source-of-wave or confirmation signal, while smaller beneficiaries may offer better return asymmetry.

Implication:

- mega-caps can remain in the system as wave leaders or reference tickers
- smaller liquid companies should receive higher convexity credit
- capital should prefer companies where the event shock can plausibly re-rate the whole business

### Initial Filter Stack

Use layered filters. Do not rely on one screen.

The first-stage filter is not an alpha model. It is only a yes/no viability gate to avoid wasting parser and LLM cost on tickers that cannot be traded or cannot be scored.

Do not remove tickers in stage one because of untested alpha assumptions such as revenue growth, drawdown/recovery, market cap, relative strength, or theme strength. Those belong in later scoring/audit layers after we can measure whether they improve returns.

1. Tradable filter

- U.S.-listed common stocks
- exclude OTC
- exclude funds/ETFs/SPAC shells unless explicitly included
- active ticker
- minimum price, likely `>$2`
- minimum average dollar volume

2. Revenue-data viability filter

- keep if latest 10-Q/K before decision date contains enough revenue data to compute required score inputs
- reject only if revenue data needed for required calculations is missing
- do not score or penalize revenue growth at the initial filter stage
- after SEC filing/document viability is confirmed, compute revenue-scale buckets from SEC CompanyFacts/XBRL before any LLM work
- use revenue-scale buckets as a cost-control and convexity filter, not as proof of alpha

3. Filing availability filter

Keep companies that have:

- recent 10-Q/K filings
- 8-K Item 2.02 earnings history when earnings framework is being run
- EX-99.1 earnings release available when earnings framework is being run
- enough prior 8-Ks for ticker-relative baseline, ideally `>= 3`

4. Later-stage research filters

The following are not initial hard filters yet. They may be computed and tested later:

- revenue growth
- drawdown/recovery
- relative strength
- sector/theme strength
- market cap / size proxy
- convexity proxy

5. Venture pre-filter

Use 10-Q/K venture scanner before expensive 8-K extraction only after we have tested that it does not create false negatives.

Candidate inclusion examples:

```text
venture_score >= 10
OR wave_exposure >= 3
OR asymmetric_upside >= 3
```

These are starting points, not final thresholds.

6. Event trigger filter

Run full 8-K extraction only when a new Item 2.02 filing appears.

Do not repeatedly re-extract old filings unless parser/scoring logic changes.

7. Dynamic expansion filter

Expand the universe from discovered ecosystem relationships:

- customers
- suppliers
- competitors
- beneficiaries
- peers mentioned by winners

Example:

`NVDA` can identify wave direction, while suppliers/beneficiaries such as power, optical, networking, memory, and cooling companies may offer higher convexity.

### Market Data Cache / LLM Cost Control

LLM usage is the most expensive step. Production flow must therefore be:

```text
AKG seed universe -> common-stock + SEC CIK validation -> cached raw price/liquidity viability -> SEC filing metadata viability -> Python/sec-parser extraction -> LLM extraction only for survivors -> deterministic score math
```

The LLM must not run on the full SEC universe. It should run only after cheap checks prove the ticker is a valid common-stock candidate, has SEC mapping, has raw price/liquidity data, has relevant filing history, and has enough data for score calculations.

Local Yahoo-style price cache currently lives under:

```text
/Users/aeternusholdings/Documents/GitHub/AeternusHoldings/cache/sec/
```

Observed cache types:

- `prices_single_name_*.parquet`: single-ticker OHLCV history.
- `prices_*.parquet`: basket OHLCV history for selected ticker universes.
- `snapshots_*.json`: dated fundamentals/forward-return snapshots for selected universes.
- `facts_*.json`: SEC company facts cache for many tickers.

Current limitation:

- Price cache is useful, but not yet guaranteed to cover the full tradable universe.
- Basket price files cover selected universes, not every SEC filer.
- Single-name price files cover only names already pulled.
- Yahoo current market cap is not point-in-time and should not be used for historical fundamental filters without caveat.

Required market data cache before true full-universe filtering:

- daily raw Yahoo OHLCV for every candidate ticker, including `open`, `high`, `low`, `close`, `volume`
- computed `avg_dollar_volume_20d`, `avg_dollar_volume_60d`, and price floor
- exchange, security type, active/delisted status, and common-stock flag
- CIK/ticker mapping for SEC join
- sector/industry/theme tags when available
- later-stage technical research features such as `sma_50`, `sma_200`, 3/6/12-month relative strength, 52-week high distance, volatility, and drawdown

Cheap filters from this cache should decide whether a ticker is worth filing extraction. LLM extraction is reserved for the reduced set.

Initial yes/no viability rules:

- missing/invalid price data: hard fail
- raw close below price floor, initially `$2`: fail
- `avg_dollar_volume_60d < $500k`: fail
- `avg_dollar_volume_60d $500k-$2M`: keep but flag as low liquidity, do not hard fail until tested
- missing SEC CIK: fail
- missing required 10-Q/K revenue data: fail for frameworks that require revenue calculations

Revenue-scale bucket rule tested on `2024Q3`:

- Source: cached SEC CompanyFacts/XBRL only, no 8-K extraction, no LLM.
- As-of date: quarter start, `2024-07-01`.
- Revenue fact source: latest available 10-Q/10-K revenue fact filed before as-of date.
- Buckets: `<$100M`, `$100M-$500M`, `$500M-$1B`, `$1B-$2B`, `$2B-$10B`, `$10B-$50B`, `>$50B`.
- Current final pre-extraction revenue band: require `>= $100M` and `< $10B` revenue for the main screener pass.
- Reason: sub-`$100M` revenue names are often too noisy, pre-revenue, or structurally different enough to require a separate microcap/biotech-style framework.
- Mandatory index backstop: reconcile SPY/S&P 500, QQQ/Nasdaq-100, and Dow constituents against the candidate universe before finalizing each quarterly list.
- If a mandatory index constituent passes the `>= $100M` revenue rule but failed an earlier AKG/metadata/document gate, keep it in an augmented audit list with `pipeline_status` and `pipeline_missing_reason` instead of silently dropping it.
- Upper revenue boundary: remove or separately audit `>= $10B`.
- Reason for upper sizing: limited-capital screener should prioritize businesses where a filing shock can plausibly re-rate the whole company.
- Caveat: `>= $10B` companies can still be retained as wave anchors/reference tickers, but should not consume expensive LLM budget unless specifically selected.
- For `2024Q3`, the final pre-extraction universe contained `1,265` tickers.
- After earnings-document repair, `1,258` tickers have local cached 8-K plus earnings exhibit/EX-99.1-like text and are the active extraction universe.
- Removed from active extraction universe because 2024Q3 earnings docs were not ready: `ALNY`, `MKC`, `MS`, `PAYX`, `SATS`, `TXN`, `VICI`.

Local Python extraction status:

- Local 8-K / earnings exhibit extraction has been run for the `1,258` active `2024Q3` tickers.
- Regex-only extraction was rejected because it scored only `5 / 1,258` tickers.
- Correct local extraction now uses cached SEC docs, `sec-parser` semantic elements, `pandas.read_html` table extraction, and XBRL fallback. No LLM.
- Output manifest: `Growth/earnings_8k_sec_parser/local_earnings_extraction_manifest_2024Q3_secparser.csv`.
- JSON output folder: `Growth/earnings_8k_sec_parser/local_extractions_2024Q3_secparser/`.
- Clean no-LLM score CSV: `Growth/earnings_8k_sec_parser/no_llm_earnings_score_2024Q3.csv`.
- No-LLM extraction audit CSV: `Growth/earnings_8k_sec_parser/no_llm_extraction_audit_2024Q3.csv`.
- Reserved post-LLM score CSV schema: `Growth/earnings_8k_sec_parser/post_llm_earnings_score_2024Q3.csv`.
- Score-stage CSVs should not include fields that do not contribute to the stage score. Keep parser/debug columns in audit CSVs.
- Right-tools local extraction scored `996 / 1,258` tickers.
- Remaining `262` were missing reported revenue YoY under deterministic extraction.
- `sec-parser` succeeded on `1,256 / 1,258`; `2` filings used BeautifulSoup fallback after sec-parser recursion errors.
- Early one-quarter signal: `medium` score bucket had `36` names, 90-day average return `+14.86%`, median `+15.46%`, hit rate `80.6%`.
- This is promising but still one-quarter evidence; validate across more quarters before making it a production ranking rule.

Pre-LLM fundamental score:

- Built from universal XBRL fields only: revenue, net income, assets, financing cash flow, investing cash flow, operating cash flow.
- Output: `Growth/earnings_8k_sec_parser/pre_llm_fundamental_score_2024Q3.csv`.
- Must be built from the active extraction universe, not the broader augmented universe, so return fields are complete and excluded tickers do not leak in.
- For fundamental quarters, XBRL facts must be selected with each ticker's earnings event filing date as `asof_date`. Do not use future quarter-end filings if they were not filed by the event date.
- Score components: profitability, operating cash flow margin, FCF proxy margin, financing dependence, asset efficiency.
- Current combined fundamental file through 2022: `Growth/earnings_8k_sec_parser/pre_llm_fundamental_score_2021Q4_2022Q4.csv`.
- Combined 2021Q4-2022Q4 file has `5,960` rows, `5,885` scored rows, and no blank 90-day returns.
- In `2024Q3`, this score is not a hard filter. Weaker fundamental buckets had higher 90-day returns, likely because the period rewarded distressed/speculative re-rates.
- Treat this as a company-quality/risk lens, not an alpha filter until tested across more quarters.

Tier 0 — Broad Right-Tail Universe:

- Rule: `pre_llm_fundamental_bucket != "not_scored"` AND `entry_open < 25` AND `revenue_bucket` is one of `<$100M`, `$100M-$500M`, `$500M-$1B`, `$1B-$2B`, `$2B-$10B`.
- What it does: first-pass haystack reduction.
- Empirical role: keeps roughly `30%` of the universe.
- Empirical role: captures roughly `50%` of `+30%` winners.
- Typical characteristics: wide quality range.
- Typical characteristics: mix of `good`, `mixed`, and `weak` pre-LLM names.
- Typical characteristics: includes early-stage and mid-cap names.
- Use case: broad research feed.
- Use case: exploration.
- Use case: downstream system can handle large input.

Tier 1 — Default Balanced Feed:

- Rule: `pre_llm_fundamental_bucket != "not_scored"` AND `entry_open < 15` AND `revenue_bucket` is one of `<$100M`, `$100M-$500M`, `$500M-$1B`, `$1B-$2B`, `$2B-$10B`.
- Importance: most important pre-LLM feed.
- What it does: best balance of recall and precision.
- Empirical role: roughly `2x` base hit rate.
- Empirical role: stable across all market regimes.
- Typical characteristics: low-to-mid price stocks.
- Typical characteristics: small/mid-cap names.
- Typical characteristics: mix of dislocation, re-rating, and growth setups.
- Use case: primary feed.
- Use case: default candidate universe.
- Use case: send this to downstream system.

Tier 1.1 — LLM-Supported Candidate:

- Rule: Tier 1 AND `post_llm_candidate_flag = 1`.
- Interpretation: modest upside improvement.
- Interpretation: better downside control.
- Use case: good general-purpose LLM-supported Tier 1 pool.

Tier 1.2 — Causal Re-Rating Candidate:

- Rule: Tier 1 AND `causal_change = 3`.
- Interpretation: LLM sees a concrete business driver.
- Business drivers include margin improvement, demand recovery, cost reset, operating leverage, pricing/mix improvement, FCF improvement, and restructuring progress.
- Use case: Tier 1 rows where unstructured evidence points to a plausible business re-rating mechanism.

Tier 1.3 — Best Balanced Production Subset:

- Rule: Tier 1 AND `post_llm_candidate_flag = 1` AND `causal_change = 3` AND `negative_revision_risk <= 2`.
- Interpretation: primary Tier 1 post-LLM candidate_list.
- Use case: best balanced production subset for limited capital deployment.

Tier 1.4 — Clean High-Priority Subset:

- Rule: Tier 1 AND `post_llm_high_priority_flag = 1`.
- Interpretation: not always highest raw `+30%` capture, but better risk-adjusted quality.
- Use case: sizing/ranking boost.
- Use case: cleaner Tier 1 candidate label.

Tier 2 — Compact High-Conviction Feed:

- Rule: `pre_llm_fundamental_bucket != "not_scored"` AND `entry_open < 10` AND `revenue_bucket` is one of `<$100M`, `$100M-$500M`, `$500M-$1B`, `$1B-$2B`, `$2B-$10B`.
- What it does: higher `+30%` hit rate than Tier 1.
- What it does: smaller, more concentrated list.
- Risk profile: more volatility.
- Typical characteristics: lower-priced names.
- Typical characteristics: higher beta.
- Typical characteristics: more extreme outcomes, both `+30%` and `-30%`.
- Use case: high-conviction candidate_list.
- Use case: aggressive strategy.
- Use case: when you want fewer names.

0-100 Rank Scoring:

- Script: `Growth/build_rank_scores.py`.
- Default input: `Growth/earnings_8k_sec_parser/combined_tier0_tier1_tier2_tier3_tier4_2021Q4_2026Q1_partial_gpt55_mixed.csv`.
- Default output: `Growth/earnings_8k_sec_parser/rank_scored_tier0_tier1_tier2_tier3_tier4_2021Q4_2026Q1_partial_gpt55_mixed.csv`.
- Formula: `Final Score = Tier Structure Score + LLM Business Improvement Score + Fundamental / Re-rating State Score + Theme / External Confirmation Score - Risk Penalty`.
- Clamp: `0` to `100`.
- Important rule: entry score never uses future return columns.
- Active monitoring score can use realized `return_10d_pct`, `return_20d_pct`, `return_30d_pct`, and `return_60d_pct`.
- Market regime risk is deliberately excluded from this formula because macro framework will adjust scores later.

Tier Structure Score:

- `tier_bucket` / Tier 0 only: `+10`.
- Tier 1: `+18`.
- Tier 2: `+25`.
- Tier 3: `+4` add-on.
- Tier 4: `+5` add-on.
- Cap: `30`.

LLM Business Improvement Score:

- `post_llm_candidate_flag = 1`: `+8`.
- `post_llm_high_priority_flag = 1`: `+6`.
- `causal_change = 1`: `+4`.
- `causal_change = 2`: `+10`.
- `causal_change = 3`: `+20`.
- `negative_revision_risk <= 1`: `+6`.
- `negative_revision_risk = 2`: `+4`.
- `narrative_delta_bucket = "inflecting"`: `+5`.
- `narrative_delta_bucket = "constructive"`: `+3`.
- `narrative_delta_bucket = "neutral"`: `+1`.
- `operating_leverage_quality = 2`: `+4`.
- `operating_leverage_quality = 1`: `+2`.
- `durability = 2`: `+3`.
- `durability = 1`: `+1`.
- Current `score_addition > 0` and prior quarter `score_addition > 0`: `+5`.
- `post_llm_high_priority_flag = 1` and prior quarter `score_addition > 0`: `+3`.
- Cap: `45`.

Fundamental / Re-rating State Score:

- `asset_efficiency_score = 2`: `+5`.
- `asset_efficiency_score = 1`: `+3`.
- `pre_llm_fundamental_score <= 0`: `+3`.
- `pre_llm_fundamental_score <= -2`: additional `+2`.
- Current and prior quarter `pre_llm_fundamental_score <= 0`: `+3`.
- `pre_llm_fundamental_score > 0` and `causal_change = 3`: `+3`.
- `financing_dependence_score = 1`: `+3`.
- `financing_dependence_score = 0`: `+1`.
- Cap: `15`.

Theme / External Confirmation Score:

- Optional input: pass `--theme-csv`.
- If no theme metadata exists, score is `0`.
- `theme_active = 1`: `+4`.
- `theme_leader_or_direct_beneficiary = 1`: `+3`.
- `theme_cohort_strength = 1`: `+3`.
- Cap: `10`.

Risk Penalty:

- `post_llm_demote_flag = 1`: `-7`.
- `narrative_delta_bucket = "deteriorating"`: `-5`.
- `negative_revision_risk >= 3`: `-6`.
- `financing_dependence_score = -1`: `-4`.
- `financing_dependence_score = 0`: `-1`.
- `entry_open < 5`: `-2`.
- `entry_open < 2`: `-6` total.
- Missing critical LLM fields in LLM-covered row: `-3`.
- Hard reject: missing `entry_open`, missing `revenue_bucket`, or `pre_llm_fundamental_bucket = "not_scored"`.

Monitoring / Stop-Loss Adjustment:

- `return_60d_pct <= -10`: `monitoring_status = "kill_review"` and score capped at `20`.
- `return_30d_pct <= -15`: subtract `12` and status `midpoint_stress`.
- `return_20d_pct <= -20`: subtract `10` and status `early_stress`.
- `return_10d_pct <= -20`: subtract `10` and status `early_stress`.
- No tight `-5%` early stop.

Rank Labels:

- `85-100`: `A+`.
- `75-84`: `A`.
- `65-74`: `B`.
- `50-64`: `C`.
- `30-49`: `D`.
- `<30`: `Avoid / stale / low priority`.
- Kill review cap: `Stop / review`.

Entry Score Buckets:

- `>=80`: `Highest-priority entry research`.
- `70-79`: `High-priority entry research`.
- `60-69`: `Good candidate, needs downstream confirmation`.
- `40-59`: `Watchlist / secondary research`.
- `<40`: `Low priority unless theme override exists`.

Revenue bucket plus pre-LLM fundamental score finding:

- In `2024Q3`, revenue bucket alone did not create a sharp filter.
- `$2B-$10B` and `$1B-$2B` had the best 90-day median returns among revenue buckets.
- `weak` pre-LLM fundamental bucket outperformed `strong`, `good`, and `mixed` across the active universe.
- Best combined 90-day buckets by median return were:
- `$2B-$10B + weak`: `34` names, median `+13.68%`, average `+12.54%`, hit rate `73.5%`.
- `$1B-$2B + weak`: `21` names, median `+9.37%`, average `+11.10%`, hit rate `76.2%`.
- `$100M-$500M + weak`: `124` names, median `+8.94%`, average `+11.04%`, hit rate `65.3%`.
- Worst notable combined bucket was `$500M-$1B + strong`: `82` names, median `+0.74%`, average `+1.60%`, hit rate `53.7%`.
- Interpretation: for this quarter, weaker fundamentals appear to identify re-rate/speculative setups rather than low-quality names to discard.
- Do not hard-filter on this until multiple quarters confirm stability.

Replication status:

- Core scripts now accept explicit quarter/path arguments and can be reused for the next quarter.
- Added helper runner: `Growth/run_quarter_pipeline.py`.
- Example dry-run: `.venv/bin/python Growth/run_quarter_pipeline.py --quarter 2024Q4 --dry-run`.
- Added SEC quarter cache manager: `Growth/sec_quarter_cache_manager.py`.
- Cache manager input: quarter plus ticker universe CSV.
- Cache manager default metadata mode is hybrid: bulk-load SEC quarterly master index first, then use ticker submissions only where needed to verify 8-K Item 2.02.
- Cache manager identifies 8-K Item 2.02 events, accession-tied earnings exhibit/EX-99.1-like docs, and latest 10-Q/10-K before or inside the quarter.
- Cache manager checks local HTML/text cache and fetches missing SEC documents before writing an audit CSV plus fetch report.
- Important implementation rule: use SEC submissions `primaryDocument` for 8-K/10-Q/10-K primary docs; archive index ordering can list exhibits first.
- Production hardening now included:
- SEC quarterly master-index cache under `/Users/aeternusholdings/Documents/GitHub/AeternusHoldings/cache/sec/sec_master_indexes/`.
- `--metadata-source hybrid` default; `--metadata-source submissions` available as fallback.
- historical SEC submissions support through `filings.files[]`, not only `filings.recent`.
- retry/backoff wrapper for SEC historical submissions and document fetches.
- checkpoint CSV writes during long runs.
- quality gates for primary 8-K text, earnings-like exhibit text, and periodic 10-Q/10-K text.
- optional fail-threshold exit gates: `--min-earnings-ready-rate` and `--min-periodic-ready-rate`.
- regression tests: `tests/test_sec_quarter_cache_manager.py`.
- Example production run: `.venv/bin/python Growth/sec_quarter_cache_manager.py --quarter 2021Q4 --universe Growth/earnings_8k_sec_parser/final_active_universe_2024Q3.csv --audit-output Growth/earnings_8k_sec_parser/sec_quarter_cache_audit_2021Q4_prod.csv --fetch-report Growth/earnings_8k_sec_parser/sec_quarter_cache_fetch_report_2021Q4_prod.csv --sleep 0.005 --checkpoint-every 50`.
- `2021Q4` production cache-manager audit on the `2024Q3` active universe produced `1,258` rows, `1,178` earnings-ready rows, `1,206` periodic-ready rows, and `1,178` rows ready for both earnings and periodic extraction.
- `2021Q4` production fetch report produced `4,022` doc checks: `1,552` earnings exhibits, `1,264` primary 8-K docs, and `1,206` periodic docs. Final run used cached docs for all `4,022` checks after prior fetches.
- Not fully one-button yet. The remaining manual/generated intermediates are:
- included viability CSV after `akg_quarter_viability`.
- metadata-passed CSV after `sec_filing_metadata`.
- revenue bucket/final active universe CSV construction.
- final-active XBRL feature CSV.
- clean no-LLM score CSV split from the extraction manifest.
- Next hardening step should automate those intermediate CSV derivations so changing `--quarter` is enough.

Initial `2024Q3` microcap liquidity observation:

- Do not treat ADV buckets as proven alpha from one quarter.
- ADV is currently an execution/liquidity control and LLM-cost queueing variable, not a validated return predictor.
- The only hard ADV rule remains `ADV60 < $500k` fails.
- `ADV60 $500k-$2M` remains keep-but-flag until tested across many quarters.
- In the single tested quarter, revenue `<$100M` plus `ADV60 >= $25M` cut the bucket from `547` names to `68` names.
- That cut is allowed only as a temporary priority queue for first-pass LLM/event-shock testing, not a permanent filter.
- Before making any ADV threshold stronger than the existing `$500k` hard fail, test multiple quarters and report stability of count, average return, median return, hit rate, and missed-winner rate.

Universal XBRL feature decision:

- Stop first-pass apples-to-apples XBRL features at operating cash flow.
- Required near-universal fields: revenue, net income, assets, financing cash flow, investing cash flow, operating cash flow.
- Do not require cash, equity, shares, or EPS in the first-pass hard feature set.
- Reason: through operating cash flow is available for `1,872 / 1,873` names in the `2024Q3` tested universe and `68 / 68` names in the current priority bucket.
- Cash, equity, shares, EPS, capex, R&D, SG&A, gross profit, and debt can remain optional audit/scoring fields when available, but should not be hard filters until tested.

Hard price-data rule:

- never use Yahoo `Adj Close` for scanner calculations, filters, entries, exits, returns, or technical features
- use raw `Open` for entries/exits when simulating executable next-trading-day behavior
- use raw `Close` only for close-based technical features
- keep `Adj Close` only as ignored source data if Yahoo returns it

### Mega-Cap Exception

Market cap filter should not blindly remove mega-caps.

Mega-caps can be included if they are:

- source-of-wave companies
- benchmark leaders
- demand creators
- ecosystem anchors

Example:

`NVDA` and `GOOGL` may not be highest-convexity picks, but they help identify demand waves and validate ecosystem direction.

### Quarter-by-Quarter Filter Testing

Each proposed filter must be tested quarter by quarter.

Script:

```text
Growth/quarterly_filter_tester.py
```

Process:

1. Pick one historical quarter.
2. Apply filter using only information available at that time.
3. Save candidate list.
4. Run 8-K event shock only on filtered candidates.
5. Run fundamental picker.
6. Review missed winners and bad inclusions.
7. Adjust filter only if rule is generic and explainable.
8. Repeat next quarter.

Required output per quarter:

```text
quarter
candidate_count
tickers_included
tickers_excluded
filter_reason
event_shock_available
venture_score_available
selected_pick
missed_big_winners
bad_inclusions
notes
```

Current first test:

`2024Q3`

Result:

- candidates: `7`
- included: `5`
- excluded: `2`
- included tickers: `GOOGL`, `AAOI`, `BE`, `NVDA`, `MU`
- excluded tickers: `LITE`, `LITE`

Important observation:

The filter caught `AAOI 2024-08-07`, which later returned `+99.28%` over 90 days.

The filter excluded two `LITE` events because venture context was missing, even though later returns were `+71.82%` and `+44.43%` over 90 days. This is not proof the filter is bad, but it shows that missing venture coverage can cause missed winners.

Action item:

Before making venture pre-filter a hard gate, expand venture scoring coverage for all candidate tickers in the theme universe.

### Anti-Overfit Rules For Filters

Do not create ticker-specific filters because a ticker lost money.

Allowed:

- generic cyclicality monitor
- generic liquidity rule
- generic market-cap/convexity rule
- generic filing-history rule
- generic theme exposure rule

Not allowed:

- `exclude MU because MU lost`
- `include AAOI because AAOI won`
- thresholds chosen only to maximize current historical return

Every filter must be defensible before seeing future returns.

## Next Improvements

Add more tickers before changing thresholds.

Add real market cap / liquidity / float data.

Add candidate-level ablation reports:

- base picker
- base + cyclicality monitor
- base + venture threshold
- base + convexity
- base + mixed shock treatment

Add portfolio constraints:

- max one pick per quarter
- optional top 3 per quarter
- skip low confidence
- no same ticker repeat if still in active holding window

Add stronger “why selected over alternatives” output.

Add production LLM extractor for evidence buckets and driver changes.

## Change Policy

Do not silently change framework rules in code only.

When adding, editing, or removing framework logic:

1. Update this markdown file.
2. Update script.
3. Rerun outputs.
4. Record impact in this file.

This file should remain the canonical source for framework behavior and rationale.
