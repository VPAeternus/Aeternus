# Fundamental Canonical History Replay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a consolidated fundamental pipeline that can generate historical and current-quarter complete candidate CSVs, ending in Top10 + Plus5 + shadow refill candidates, without importing legacy Growth combined CSVs as the source of truth.

**Architecture:** Reuse the current `tradingagents/research/fundamental/src/daily_run/` and `src/panel/` framework as the only output-producing path. Historical quarters must be replayed or rebuilt from canonical source artifacts and framework modules; any legacy CSV may be used only for one-time audit comparison, never as publishable input.

**Tech Stack:** Python, pandas, Typer, pytest, existing `daily_run`, `sec_pipeline`, `features`, `selection`, and `panel` modules.

**Communication Rule:** Explain each step in simple English first. Avoid internal terms unless they are defined in plain language before use.

---

## Step-by-Step Audit Log

### Step 1: Count Master-List Tickers

Status: existing code partially covers this.

Existing code:

- `tradingagents/research/fundamental/src/daily_run/universe.py`
  - `_load_master_rows(...)` loads canonical JSON or compatibility CSV master-list rows.
  - `build_combined_universe(...)` computes `master_count = len(master_rows)`.
  - `validate_universe_gate(...)` computes `row_count = len(rows)` for the combined universe after ticker dedupe and scout append.
- `tradingagents/research/fundamental/src/daily_run/orchestrator.py`
  - Gate 2 calls `build_combined_universe(...)` and writes `universe_gate_summary.json`.
- `tests/test_fundamental_daily_universe_gate.py`
  - asserts `result.summary["master_count"] == 3`.

Gap:

- Existing `master_count` is valid master-list row count after blank-ticker filtering, not explicitly unique ticker count.
- Combined `row_count` is deduped universe count after master + scout merge, not pure master-list unique count.
- Plan must add explicit `master_total_valid_rows`, `master_unique_ticker_count`, and `master_duplicate_ticker_count` before historical replay.

Acceptance criteria:

- A broad run records raw valid master rows, unique master tickers, duplicate master tickers, scout count, new scout count, and final combined universe count.
- Historical/current complete panel generation uses the unique master ticker set as the starting universe for each quarter.
- Duplicate master tickers are reported in validation JSON, not silently hidden.

Where the main stock list is stored:

- The main stock list is not hardcoded in `universe.py`.
- Each run receives a main-list file from the run command.
- If no file is provided, the run looks for `final_dealflow_tickers_sec_eligible.json` inside that run's output folder.
- For the latest confirmed `2026Q2` run, the main-list input is `eval_results/fundamental/2026-05-12_2026Q2_hp_rm_final_v3/final_dealflow_tickers_sec_eligible.json`.
- That run then saved the cleaned list it actually used as `eval_results/fundamental/2026-05-12_2026Q2_hp_rm_final_v3/master_fundamental_universe_2026Q2.csv`.
- Both latest files contain `1,313` tickers.

Why both files exist:

- `final_dealflow_tickers_sec_eligible.json` is the input handoff: the list of stocks approved for company-data collection.
- `master_fundamental_universe_2026Q2.csv` is the run-ready copy: same stocks after the run adds quarter, source labels, scout labels, and count checks.
- Keeping both lets us prove what came in and what was actually used.
- This is useful for audit, but the naming is confusing.
- Target cleanup: rename these concepts in future docs/output to "input stock list" and "review stock list" unless compatibility requires old filenames.

Rename and source-tracking fix:

- `master_fundamental_universe_<quarter>.csv` should be renamed for operators to `review_stock_list_<quarter>.csv`.
- Keep the old filename only as a compatibility copy if existing code still expects it.
- `master_universe_source` is too vague and currently misleading.
- Latest `2026Q2` check showed all `1,313` rows labeled as `final_dealflow_tickers_sec_eligible.json`, even though the input summary says:
  - base main-list count: `1,276`
  - base main-list file: `eval_results/fundamental/2026-05-11_2026Q2_master_sec_fetch/final_dealflow_tickers_sec_eligible.json`
  - same-day scout/dealflow count: `97`
  - new scout additions: `47`
  - resolved new additions: `46`
- Required fix: each stock row must carry clear source fields:
  - `stock_source_type`: `main_list`, `existing_main_list_with_dealflow_signal`, or `new_dealflow_add`
  - `stock_source_file`: input file path/name
  - `dealflow_seen_today`: `0/1`
  - `dealflow_scouts`: scout names for that ticker
- The final review stock list count is not today's dealflow count. It is main list plus valid new dealflow additions, with duplicates removed.

Where new scout company IDs come from:

- If a scout ticker is not already in the main list, `universe.py` can only use company ID/name data that was already resolved and passed into it.
- The resolver lives outside `universe.py`.
- `tradingagents/research/fundamental/src/pipeline/dealflow_adapter.py` converts scout tickers into company-ready rows.
- It calls `tradingagents/research/fundamental/src/ingest/cik.py`, which looks up ticker-to-company-ID data from the SEC company ticker map.
- If a new scout ticker still has no company ID, `universe.py` marks it `not_resolved`, and final mode stops instead of scoring it.

SEC ticker map rule:

- The SEC ticker map is a useful first lookup, not a complete list of every SEC filer.
- It mainly maps public tickers to company IDs and company names.
- It can miss companies with no public ticker, funds handled in separate SEC files, very new listings, delisted/old tickers, private filers, or names that do not match cleanly.
- If the SEC ticker map misses a scout ticker, the pipeline should not assume the company does not exist.
- Correct behavior: search SEC by ticker before removing the ticker from the final SEC-based stock review.

Current 1,276-list audit:

- `final_dealflow_tickers_sec_eligible.json` is a small curated review list, not the full SEC ticker map.
- The base `1,276` came from `1,279` unique historical fundamental panel tickers.
- The three tickers missing from the `1,276` base list are `CFLT`, `EXAS`, and `TGNA`.
- Local resolver labeled those three as `no_sec_ticker_match`, but SEC filings exist for them.
- This proves the old filter was too aggressive.
- Required fix: do not remove a ticker solely because the local SEC ticker map misses it. Search SEC filings by ticker first, then decide.

Correct new-ticker flow:

1. Ticker comes from dealflow.
2. Check main list.
3. If not in main list, try SEC ticker map.
4. If SEC ticker map misses it, search SEC by ticker.
5. If SEC filings exist, keep it and attach company ID.
6. If no SEC filings exist, mark the reason clearly:
   - no SEC filer found
   - foreign filer/no US SEC filing
   - fund/other special case
   - ticker/name unresolved

Proposed SEC-to-review-list filter:

- Start with the SEC ticker map, currently `10,348` tickers.
- Keep a ticker only when required company filing data exists for the quarter being reviewed.
- Required company filing data means the pipeline can find enough SEC evidence to calculate the revenue and other core fundamental fields needed before scoring.
- Every ticker must have the required earnings `8-K` and press-release exhibit for the quarter being reviewed.
- If the ticker does not have the required earnings `8-K` and press-release exhibit, remove it before spending scoring resources on it.
- Keep a ticker only when raw Yahoo price and volume data exists.
- Use raw Yahoo prices, not adjusted prices.
- Keep a ticker only when the raw close is at least `$2`.
- Keep a ticker only when average daily volume over the last 60 trading days is at least `500,000` shares.
- Save rejected tickers with a clear reason, so the operator can see whether the miss was company-data, price-data, price, volume, or unresolved SEC identity.

Confirmed rule:

- Earnings `8-K` and press-release exhibit are mandatory for every stock entering the review list, not only for later LLM/final-candidate review.

Recommended implementation home for the SEC-to-review-list filter:

- Status: implemented.
- New file: `tradingagents/research/fundamental/src/daily_run/review_list_filter.py`.
- This file should own the plain question: "which SEC tickers are worth reviewing this quarter?"
- It should start from the SEC ticker map, apply the SEC evidence rule, apply the raw Yahoo price/volume rule, and write kept/rejected lists.
- Keep `universe.py` focused on loading and validating the final review stock list.
- Keep `sec_pipeline/cache_coverage_manifest.py` focused on checking SEC documents.
- Keep `ingest/prices.py` focused on fetching raw Yahoo prices.
- `daily_run/orchestrator.py` now calls the new review-list filter before scoring starts when `build_review_list_from_sec=True`.
- Gate 2 now includes the filter counts under `review_list_filter`, so the operator can see how many SEC-map names were kept and rejected before scoring.
- CLI switch added: `fundamental-run-today --build-review-list-from-sec`.
- Review-list price checks now use cached price files by default.
- Default cache root: `/Users/aeternusholdings/.cache/autoresearch_fundamentals`.
- Live Yahoo review-list downloads are disabled unless `--allow-live-review-price-fetch` is passed.
- The same cache-only price source is used for later daily-run entry price checks when the SEC review-list path is active and live fetch is not allowed.
- Review-list output files:
  - `review_stock_list_<quarter>.csv`
  - `review_stock_list_rejections_<quarter>.csv`
  - `review_stock_list_summary_<quarter>.json`
- Rejection reasons include missing earnings `8-K`, missing press-release exhibit, missing periodic filing, missing core fundamental data, missing raw Yahoo data, raw close below `$2`, and `ADV60` below `500,000`.

2026-05-13 cache-only count result:

- SEC map names: `10,348`
- Strict SEC-ready names after earnings `8-K`, press-release exhibit, periodic filing, and no SEC missing inputs: `1,148`
- Company-data-ready names: `1,132`
- Cached-price names among company-data-ready names: `1,115`
- Final names after raw close `>= 2` and `ADV60 >= 500,000`: `791`
- Count summary saved at `eval_results/fundamental/2026-05-13_2026Q2_sec_review_filter_cache_only/cache_only_count_summary.json`.

Module ownership note:

- `universe.py` owns the "who are we reviewing?" step only.
- It should load the main list, clean ticker names, add same-day scout names if needed, remove duplicate tickers, save the reviewed list, and report counts/problems.
- It should not own company data collection, scoring, AI review, final ranking, Top15 selection, shadow refill, or historical rebuilds.

Gate 2 definition:

- Gate 2 means: confirm the correct stock list before any scoring starts.
- It proves the run is using the full main list plus scout additions, not only the small daily scout list.
- It saves the final stock list and a count summary.
- It stops the run if the list is missing, broken, too small, scout-only, or missing required company identifiers.
