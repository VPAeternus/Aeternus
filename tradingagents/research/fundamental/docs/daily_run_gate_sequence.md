# Fundamental Daily Run Gate Sequence

## Implemented command

Use:

`python -m cli.main fundamental-run-today --mode broad-master-final --date <YYYY-MM-DD> --quarter <YYYYQ#> --master-universe <path>`

The legacy `fundamental` command remains scout-smoke/backward-compatible. It is not the official broad daily final run.


This is the required operating contract for the request: **"run the fundamental framework for today."**

A daily run is not a single scoring script. It is a gated production workflow. Each gate must produce an artifact, a count summary, and either a pass/fail status or an explicit quarantine list. If any hard gate fails, do not publish Top10 + Plus5 + shadow refill as final.

Related contract: `tradingagents/research/fundamental/docs/daily_universe_llm_funnel_contract.md`.

## Non-negotiable rule

The daily framework must start from the broad persistent master universe, append daily scout names, score the broad universe, run LLM only on Tier 1-4 candidates, then publish Top10 + Plus5 + shadow refill from the broad final scores.

Daily scout names are not the universe. They are append/update inputs.

## Required run modes

Every run must declare one mode:

1. `broad-master-final`
   - Official daily run.
   - Expected broad universe: ~1,200+ tickers.
   - Top10 + Plus5 + shadow refill may be published only in this mode.

2. `scout-smoke`
   - Narrow validation run on daily scouts only.
   - Useful for parser/LLM smoke testing.
   - Must never be labeled final.

3. `diagnostic-only`
   - Checks coverage, missing data, and blockers.
   - Does not publish rankings.

If mode is missing, stop.

---

# Gate 1 - Run identity and immutable snapshot

## Purpose

Create a traceable daily run before touching data. Prevent accidental reuse of stale files or overwritten scout-only universes.

## Inputs

- as-of date
- quarter
- requested run mode
- persistent master universe
- daily scout/dealflow ticker source
- SEC/cache root
- price cache/source
- prior completed run, if available

## Required checks

- `as_of` is explicit and matches today's intended run date.
- `quarter` is explicit.
- run mode is one of `broad-master-final`, `scout-smoke`, or `diagnostic-only`.
- output directory is new or explicitly marked resumable.
- source file hashes are recorded.
- no core input file is modified in place.

## Stop conditions

Stop if:

- run mode is absent.
- output directory would overwrite a prior final run.
- master universe file is missing.
- daily scout source is missing and the run expects scout append.

## Output artifacts

- `run_manifest.json`
- `source_hashes.json`
- immutable copied inputs under `snapshots/`

---

# Gate 2 - Universe construction and drift control

## Purpose

Build the correct combined universe: persistent master universe plus daily scout append. Prevent the known failure where the process scored only the 162 scout/dealflow rows instead of the broad ~1,200+ universe.

## Inputs

- persistent master universe
- daily scout ticker list
- CIK/company metadata source
- prior master universe snapshot

## Required checks

- normalize tickers to uppercase.
- dedupe by ticker.
- preserve CIK and company title.
- append new scouts into master universe; do not replace master with scouts.
- validate CIK coverage.
- report added, removed, unchanged, and metadata-changed tickers.
- compare row count against expected broad range.

## Current reference numbers

On 2026-05-11:

- broad SEC-eligible universe: `1,276`
- scout/dealflow scoring file: `162`

A final daily run must use the broad universe, not the 162-row scout-only file.

## Stop conditions

Stop if:

- `broad-master-final` universe is below the expected broad threshold unless explicitly approved.
- ticker count changes materially without a drift explanation.
- CIK is missing for SEC-required tickers.
- the selected universe equals only the daily scout list in final mode.

## Output artifacts

- `master_fundamental_universe_<quarter>.csv`
- `universe_drift_report.csv`
- `universe_gate_summary.json`

---

# Gate 3 - Filing and companyfacts coverage check

## Purpose

Determine what data is already available before fetching anything. Separate pre-LLM scoring requirements from LLM evidence-pack requirements.

## Inputs

- combined master universe
- SEC submissions cache
- SEC companyfacts cache
- archive index cache
- documents cache
- current quarter

## Required checks

For each ticker, check:

- companyfacts availability.
- required 8-K Item 2.02 metadata.
- earnings press-release/exhibit metadata.
- periodic 10-Q/10-K metadata.
- required document materialization in local cache.
- foreign issuer / no domestic 10-Q or 10-K pattern.

## Important distinction

Missing earnings exhibits usually block LLM packets, not pre-LLM scoring.

Pre-LLM scoring mainly needs companyfacts fundamentals. Tier 0-4 additionally needs entry/tradable date and price data.

## Current reference numbers

On the 2026Q2 master check:

- master tickers: `1,276`
- companyfacts cached: `1,276`
- pre-LLM scorable from companyfacts: `1,262`
- strict full LLM-doc ready: `76`
- strict LLM-doc blocked/incomplete: `1,200`
- known invalid domestic-pipeline blockers: `NOK`, `SILC`, `TSEM`

## Stop conditions

Stop final LLM stage if required evidence-pack coverage is not enough for Tier 1-4 packets.

Do not stop pre-LLM scoring only because earnings exhibits are missing.

Stop full daily final if coverage status cannot distinguish:

- pre-LLM data missing
- price/trade-date missing
- LLM document missing
- invalid issuer routing

## Output artifacts

- `sec_coverage_manifest_<quarter>.csv`
- `sec_coverage_summary.json`
- `sec_coverage_blockers.json`
- `pre_llm_data_availability.csv`

---

# Gate 4 - Fetch and materialization gate

## Purpose

Fetch what is actually fetchable, then prove whether the missing-data count improved. Do not assume a download run fixed coverage.

## Inputs

- coverage manifest
- SEC fetch queue
- SEC cache root
- rate-limit settings
- resumable progress file

## Required checks

- build a fetch queue from missing but fetchable SEC inputs.
- exclude hard invalid issuer cases from domestic 10-Q/8-K fetch.
- run fast SEC fetch/materialization.
- materialize documents from complete submission files when possible.
- rerun the coverage manifest after fetch.
- compare before/after missing counts.

## Stop conditions

Stop fetch loop if:

- fetch queue is empty after regeneration.
- all remaining gaps are metadata/parser/routing gaps, not downloadable URLs.
- SEC returns repeated hard failures or rate-limit errors.

Do not keep rerunning fetch if `fetch_queue_count=0`. That is not a download problem.

## Current reference outcome

For the isolated 2026Q2 master run:

- initial regenerated fetch queue: `11`
- final fetch queue: `0`
- remaining gaps: mostly `earnings_exhibit_metadata` and `8k_item_202_metadata`

Conclusion from that run: pure SEC fetch was complete; remaining work was metadata/exhibit discovery/parser/routing.

## Output artifacts

- `sec_fetch_queue_resumable.json`
- `sec_download_manifest.json`
- `sec_download_progress.json`
- rerun `sec_coverage_summary.json`
- `fetch_delta_report.json`

---

# Gate 5 - Pre-LLM scoring readiness gate

## Purpose

Compute deterministic fundamental features and identify which rows can receive pre-LLM scores. This stage must not depend on LLM extraction.

## Inputs

- combined master universe
- companyfacts cache
- quarter
- prior quarter rows, if available

## Required fields

For each ticker, attempt to derive:

- revenue
- net income
- assets
- operating cash flow
- investing cash flow
- financing cash flow

From these, compute:

- profitability score
- operating cash-flow score
- FCF proxy score
- financing dependence score
- asset efficiency score
- total pre-LLM fundamental score
- pre-LLM bucket
- revenue bucket
- missing field list

## Required checks

- row count equals combined master universe count.
- every row has a ticker and quarter.
- missing fields are explicit, not silent blanks.
- `not_scored` rows are quarantined with reasons.
- pre-LLM output preserves source lineage.

## Stop conditions

Stop final mode if:

- pre-LLM scorable count drops materially versus prior run without explanation.
- companyfacts cache is unavailable for a broad portion of the universe.
- missing fields are not recorded.

Do not stop if a small minority is `not_scored`; quarantine them.

## Output artifacts

- `pre_llm_scores.csv`
- `pre_llm_missing_fields_report.csv`
- `pre_llm_gate_summary.json`

---

# Gate 6 - Trade date, price, and entry-open gate

## Purpose

Tier 0-4 assignment requires entry price data. Pre-LLM scores alone are not enough.

## Inputs

- pre-LLM scores
- filing event dates
- signal available datetime
- tradable date
- price history source/cache

## Required checks

For each ticker, determine:

- signal available datetime.
- tradable date, normally next trading day after the latest required filing acceptance time.
- entry open price.
- entry price source.

If exact filing event data is unavailable, the run must explicitly classify whether a safe proxy is permitted. No same-day lookahead.

## Required checks

- every Tier 0-4 candidate has `entry_open`.
- every `entry_open` has a source and date.
- price fetch failures are separated from filing-date failures.
- stale or future-dated prices are rejected.

## Stop conditions

Stop Tier 0-4 assignment for rows missing `entry_open`.

Stop final mode if price coverage is too low to produce a broad daily ranking.

## Output artifacts

- `price_history.csv`
- `entry_price_coverage.csv`
- `price_fetch_failures.csv`
- `price_gate_summary.json`

---

# Gate 7 - Tier 0-4 and LLM eligibility gate

## Purpose

Assign deterministic Tier 0-4 categories before LLM. This is the main cost-control and correctness gate.

## Inputs

- pre-LLM scores
- revenue buckets
- entry open prices
- trade dates
- HP/RM preconditions if already available

## Tier logic requirement

Tier assignment must be deterministic and pre-LLM:

- Tier 0: broad right-tail scouting universe.
- Tier 1: balanced priority feed.
- Tier 2: high-priority compact feed.
- Tier 3: revised dislocation feed.
- Tier 4: ultra-distressed tag, not production by itself.

Only Tier 1-4 rows are LLM eligible by default.

Tier 0 rows remain in the broad scored universe but do not receive default LLM packets.

## Required checks

- every scored row receives explicit Tier fields or an explicit quarantine reason.
- LLM eligibility count equals count of Tier 1-4 rows that also have required evidence docs.
- Tier 0 rows are not silently dropped.
- Tier 1-4 rows missing LLM docs are quarantined as `llm_evidence_missing`, not sent to LLM.

## Stop conditions

Stop LLM stage if:

- LLM packet count does not equal eligible Tier 1-4 evidence-ready count.
- packet count equals the full broad universe without explicit full-universe approval.
- Tier 0 rows are included in default LLM packets.

## Output artifacts

- `tier_classification.csv`
- `llm_eligibility.csv`
- `tier_gate_summary.json`

---

# Gate 8 - LLM packet, extraction, and validation gate

## Purpose

Run expensive qualitative extraction only where allowed, and validate that every packet has exactly one usable post-LLM row.

## Inputs

- Tier 1-4 LLM eligibility list
- raw SEC document texts
- prompt/version metadata
- LLM model settings
- existing resumable batch outputs, if any

## Required checks

Before LLM:

- packet count equals eligible Tier 1-4 evidence-ready count.
- every packet has ticker, quarter, sample ID, and source documents.
- packet text is non-empty.
- packet hashes are recorded.

After LLM:

- one output row per packet/sample ID.
- no duplicate sample IDs.
- required post-LLM fields present.
- parse errors and model errors are isolated.
- failed packets can be resumed without rerunning completed packets.

## Stop conditions

Stop post-LLM merge if:

- post-LLM row count does not match completed packet count.
- required fields are missing for completed packets.
- packet universe is wrong.
- LLM was run on all ~1,200+ names by accident.

## Output artifacts

- `<quarter>_llm_packets.jsonl`
- `llm_batch_manifest.json`
- `post_llm_scores.csv`
- `llm_validation_report.json`

---

# Gate 9 - Final scoring, HP buckets, and RM buckets gate

## Purpose

Merge LLM output back into the broad universe, then compute final scores, HP buckets, and RM buckets. Do not let the final scored universe shrink to only LLM rows.

## Inputs

- broad pre-LLM scores
- Tier 0-4 classification
- post-LLM scores for eligible Tier 1-4 rows
- prior quarter scores
- price/repricing metrics
- theme/tailwind data

## Required checks

- final score row count equals broad universe count minus only explicitly invalid removals, not LLM packet count.
- Tier 0 rows remain present with safe neutral/no-LLM defaults.
- post-LLM fields merge only to matching ticker/quarter/sample IDs.
- HP buckets are computed after available pre/post evidence.
- RM buckets are computed after repricing/final score fields.
- hard reject reasons are explicit.
- every row has final score label or quarantine status.

## Stop conditions

Stop final publishing if:

- final scores row count equals only scout rows or LLM rows.
- HP/RM fields are missing from final scores.
- post-LLM merge duplicates rows.
- hard rejects are not separated from low scores.

## Output artifacts

- `fundamental_final_scores_<as_of>.csv`
- `hp_bucket_report.csv`
- `rm_bucket_report.csv`
- `final_scoring_gate_summary.json`

---

# Gate 10 - Top10 + Plus5 + shadow refill publish gate

## Purpose

Publish the official daily output only after proving the broad final scores are valid.

## Inputs

- broad final scores CSV
- HP/RM bucket fields
- hard reject flags
- prior official Top10 + Plus5, if available
- deterioration/refill rules

## Required checks

- input file is the broad final scores file.
- input row count is broad-universe scale, not scout-only scale.
- Top10 core and Plus5 exception logic use final scores plus HP/RM eligibility.
- shadow refill is review-only unless explicitly promoted by user/operator.
- labels use plain-English operator terms.

## Required labels

Use these labels in output CSVs:

- `top15_bucket = Top 10 core`
- `top15_bucket = Plus 5 exception`
- `shadow_refill_status = official_top15_selection`
- `shadow_refill_status = shadow_refill_review_only_not_official`

## Stop conditions

Do not publish final if:

- Top15 input is scout-only.
- final scores row count is materially below broad master count without quarantine explanation.
- Top10 + Plus5 labels are missing or unclear.
- shadow refill replacements are treated as official without review.

## Output artifacts

- `high_conviction_top15.csv`
- `high_conviction_top15_core_deterioration_refill_shadow.csv`
- `publish_manifest.json`
- `daily_fundamental_run_report.md`

---

# Required final run report

Every daily run must end with a human-readable report containing:

1. run mode
2. as-of date and quarter
3. master universe count
4. scout append count
5. invalid/rerouted tickers
6. pre-LLM scorable count
7. price/trade-date coverage
8. Tier 0/1/2/3/4 counts
9. LLM-eligible count
10. LLM packet count
11. post-LLM completed count
12. final score row count
13. HP bucket counts
14. RM bucket counts
15. Top10 + Plus5 tickers
16. shadow refill result
17. stop gates encountered
18. quarantined rows by reason
19. files produced
20. whether output is final or diagnostic only

If the report cannot answer these fields, the run is incomplete.

# Automation requirement

The intended command should be a single orchestrator, not manual step hunting:

`python -m cli.main fundamental run-today --mode broad-master-final --as-of <YYYY-MM-DD> --quarter <YYYYQ#>`

The orchestrator must run gates in order, write each gate artifact, and stop with a clear diagnosis when a gate fails.

A failed gate is not a failed session. It is a valid diagnostic output. The failure is only unacceptable if it is hidden and a partial CSV is called final.

# Known failure to avoid

The 2026-05-11 run produced useful scout-only smoke output, but it was not the official broad daily process because:

- SEC-eligible broad universe had `1,276` tickers.
- scoring/LLM/Top15 operated on `162` scout/dealflow rows.
- LLM packets were built for the scored scout universe, not Tier 1-4 candidates from the broad universe.

Future agents must not repeat this. If broad final mode is requested, stop whenever the selected scoring universe collapses to scout-only scale.
