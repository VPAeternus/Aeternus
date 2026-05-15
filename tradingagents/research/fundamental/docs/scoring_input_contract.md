# Fundamental Scoring Input Contract

Purpose: define the data required to calculate daily fundamental scores correctly. This is the permanent contract for the broad-universe daily funnel.

## Non-Negotiable Lessons From 2026-05-12

- Do not call a daily fundamental run ready just because quarterly filings exist.
- Do not call SEC evidence missing until the full discovery chain has run: submissions -> earnings 8-K -> archive index -> press-release exhibit -> document file.
- Do not trust a fetch queue that was built before all metadata layers were discovered.
- Do not run only one SEC fetch pass. The orchestrator must loop fetch + coverage until no fetchable work remains or hard-stop.
- Do not use `10-Q` / `10-K` alone for official Top 10 + Plus 5 LLM selection. It is base-score evidence only.
- Official LLM-required rows need fresh earnings evidence: primary earnings `8-K` or press-release exhibit. This includes Tier 1-4 rows, HP production/research extension rows, and repricing-momentum extension rows.
- Do not publish Top 10 + Plus 5 without prior-quarter context. `2026Q1` is required for a `2026Q2` final run because QoQ fields drive HP/RM/shadow-refill logic.
- Daily runs must derive the run quarter from the run date or explicit `--quarter`; the required prior quarter is calculated from that run quarter. Do not hard-code a quarter in SEC coverage or prior-LLM recovery logic.
- Apply prior-quarter context before LLM eligibility in official runs so RM-only names can compute `entry_qoq_pct` and enter LLM extraction when `repricing_momentum_extension` is true.
- If a current LLM-required row needs prior-quarter LLM data, final scoring must wait until that prior LLM extract is complete or SEC evidence proves no earnings `8-K` / press-release filing exists.
- Never make the user remember these rules. Check this contract before every fundamental readiness/final-publish claim.

## Required Inputs Per Ticker

| Input | Filing/source type | Data source | Cache / artifact | Used for |
|---|---|---|---|---|
| Quarterly filing text | `10-Q` or latest valid `10-K` when applicable | SEC submissions metadata + SEC filing document | `live_sec/submissions/CIK##########.json`; `live_sec/documents/{TICKER}_{ACCESSION}_{PRIMARY_DOC}` | LLM evidence, MD&A, risk/context review |
| Companyfacts/XBRL financials | Facts sourced from `10-Q` / `10-K` XBRL | SEC Companyfacts API | `live_sec/companyfacts/CIK##########.json` | Pre-LLM score inputs: revenue, net income, assets, operating cash flow, investing cash flow, financing cash flow |
| Filing / signal date | Prefer `8-K Item 2.02`; fallback to `10-Q` / `10-K` filing date | SEC submissions metadata | Coverage manifest columns: `earnings_8k_filing_date`, `periodic_filing_date` | Sets tradable signal date |
| Entry price | Market data, not SEC filing | Yahoo Finance raw OHLCV | Runtime price provider output; final column `entry_open` | Price/risk gates and final scoring |
| LLM evidence text for LLM-required rows | Required: press release exhibit or primary earnings `8-K`; supporting fallback: `10-Q` / `10-K` | Cached SEC filing HTML plus direct SEC archive index check | `live_sec/archive_indexes/...`; `live_sec/documents/...`; packets at `lake/artifacts/{QUARTER}_llm_packets.jsonl` | LLM fields: causal change, negative revision risk, narrative delta, operating leverage quality, durability, proof alignment |

## Hard Rules

- Broad universe rows must not be scored unless the score inputs are present.
- A valid score row requires:
  - quarterly filing metadata/document present;
  - Companyfacts financial inputs sufficient to calculate the pre-LLM fundamental score;
  - revenue bucket present;
  - tradable date present;
  - entry open present.
- Rows missing required score inputs must be explicitly quarantined, not silently fake-scored.
- LLM-required rows require fresh earnings evidence for official LLM review and Top 10 + Plus 5 eligibility. This includes Tier 1-4 rows, HP production/research extension rows, and repricing-momentum extension rows.
- LLM-required rows also require the prior-quarter LLM extract when prior-quarter comparison affects scoring. If it is missing, the daily run must build/fetch the prior-quarter evidence packet and run or queue that extraction before final scoring.
- SEC evidence checks must cover the run quarter and the required prior quarter for rows that need prior-quarter LLM review.
- Fresh earnings evidence means either a press release exhibit, usually `8-K Exhibit 99.1`, or a primary earnings `8-K`.
- Quarterly filing text alone is not enough for official Top 10 + Plus 5 LLM review because the critical LLM fields depend on fresh earnings narrative.
- Missing `8-K Item 2.02` is acceptable for base scoring only. Use the quarterly filing date as the signal date fallback, but quarantine the row from LLM/final high-conviction selection until fresh earnings evidence exists.
- When an earnings `8-K` exists but exhibit metadata is missing, the parser must fetch/check the SEC archive index directly before declaring the exhibit unavailable.
- Daily orchestration must keep running SEC fetch/coverage passes until the fetch queue is empty or the configured max-pass stop is hit. A single fetch pass is not sufficient because submissions can reveal archive-index work, and archive indexes can reveal exhibit-document work.
- Final rows plus explicit quarantine rows must reconcile to the broad universe count before publish.

## Filing Type Priority

1. Press release exhibit: usually `8-K Exhibit 99.1`.
2. Primary earnings `8-K`, usually `8-K Item 2.02`.
3. Quarterly filing: `10-Q` or `10-K`.

Main LLM extraction packets must include only fresh earnings evidence: press-release exhibit and/or primary earnings `8-K`. Do not include `10-Q` / `10-K` text in the main LLM extraction packet. An LLM-required row without press release or primary earnings `8-K` must be quarantined from official LLM review and Top 10 + Plus 5 selection.

## Current Implementation Touchpoints

- SEC coverage/parser: `tradingagents/research/fundamental/src/sec_pipeline/cache_coverage_manifest.py`
- SEC document loader: `tradingagents/research/fundamental/src/daily_run/coverage.py`
- Companyfacts extraction: `tradingagents/research/fundamental/src/ingest/xbrl.py`
- Pre-LLM scoring: `tradingagents/research/fundamental/src/features/pre_llm_scores.py`
- Score-input quarantine: `tradingagents/research/fundamental/src/daily_run/scoring_inputs.py`
- LLM eligibility and packets: `tradingagents/research/fundamental/src/daily_run/eligibility.py`
- Final scoring: `tradingagents/research/fundamental/src/daily_run/finalize.py`

## Operator Checklist

Before LLM/final publish, verify:

- `missing_periodic_10q_10k = 0` for the clean universe.
- SEC discovery chain has completed for earnings evidence: submissions -> earnings 8-K -> archive index -> press-release exhibit -> document file.
- Fetch queue is empty after repeated fetch/coverage passes, not just after a single fetch pass.
- `score_input_quarantine_count` is explicit and acceptable.
- `entry_price_quarantine` is empty for the publish universe, or excluded names are explicitly quarantined.
- `llm_packets` count equals LLM-required score-ready names with fresh earnings evidence: Tier 1-4 plus HP production/research extension plus repricing-momentum extension.
- Prior-quarter LLM recovery packets are included when needed. A run is not final until those extracts validate, unless SEC evidence proves no prior earnings filing exists.
- Gate 7 `tier_classification.csv` may already include QoQ-derived RM fields; Gate 9 still validates that prior context is complete before publish.
- Prior quarter exists for final selection. For a `2026Q2` run, process `2026Q1` before Top 10 + Plus 5 + shadow refill.
- `final_score_rows + explicit_quarantine_count = broad_universe_count`.
