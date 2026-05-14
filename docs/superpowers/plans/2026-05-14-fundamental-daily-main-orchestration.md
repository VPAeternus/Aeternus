# Fundamental Daily Main Orchestration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `fundamental-run-today` perform the full daily process from the master 2021Q4 SEC-evidence start list through Top 10 + Plus 5 + shadow refill, including automatic evidence/price checks and LLM evidence recovery inside the daily run.

**Architecture:** Do not create a new pipeline. Keep `tradingagents/research/fundamental/src/daily_run/orchestrator.py` as the main daily orchestrator. Add small helper modules under `tradingagents/research/fundamental/src/daily_run/` for identity resolution, price cache writeback, and daily status output. Keep LLM evidence recovery inside the existing orchestrator gates so there is one daily control path.

**Tech Stack:** Python 3.x, Typer, pytest, existing `daily_run`, `sec_pipeline`, `ingest`, `features`, `panel`, and `selection` modules, local SEC cache, local Yahoo price cache.

---

## Operator Contract

The saved daily steps live in:

- `tradingagents/research/fundamental/docs/daily_run_gate_sequence.md`

Plain daily flow:

1. Start from the master start list: 2021Q4 SEC-evidence tickers.
2. Add today's dealflow tickers.
3. For new dealflow names, resolve ticker to company ID, company name, and CIK.
4. If the local SEC ticker map misses, check trusted panel data, SEC facts, then SEC directly.
5. Mark source clearly: master start, existing master, today's dealflow add, or rejected.
6. Remove only names that truly cannot be tied to SEC filings or tradable price data.
7. Check SEC cache for earnings 8-K, press-release exhibit, 10-Q/10-K, and company facts.
8. If SEC evidence is missing, fetch it now and save it to cache.
9. Check Yahoo price cache.
10. If price data is missing, fetch it now and save it to cache.
11. Calculate pre-LLM score.
12. Assign Tier 0-4, HP, and RM flags.
13. Decide which rows need LLM.
14. Build LLM packets.
15. If packets cannot be built, recover/fetch evidence inside the daily run before stopping.
16. Run or queue LLM extraction.
17. Validate LLM output.
18. Calculate post-LLM score.
19. Calculate final score.
20. Select Top 10 Core.
21. Select Plus 5 Exception.
22. Run shadow refill review.
23. Emit final CSVs, Top15 files, shadow files, and clear rejection/status files.

Key rule: LLM evidence recovery happens inside the daily run before final scoring. No separate recovery pipeline.

---

## Current Pipeline Gaps

1. **Wrong default master source.**
   - Current CLI default can point to `out/final_dealflow_tickers_sec_eligible.json`.
   - Needed default is `tradingagents/research/fundamental/data/master_fundamental_universe_start_2021Q4.json`.

2. **New dealflow names are not resolved automatically.**
   - `build_combined_universe()` supports `unresolved_new_scouts`, but the orchestrator does not build that mapping.
   - New tickers can enter with missing CIK and hard-stop Gate 2.

3. **Identity fallback is not reusable.**
   - We already saw `CFLT`, `EXAS`, and `TGNA` missed by local `sec_company_tickers.json`.
   - Correct rule is SEC map first, then trusted panel, SEC facts, then SEC direct lookup before marking unresolved.

4. **The SEC-map review-list mode is not the official main path.**
   - `--build-review-list-from-sec` starts from all SEC map names.
   - New official path starts from the 2021Q4 SEC-evidence master start list and appends today's dealflow.

5. **Main price path does not cache new Yahoo rows.**
   - `attach_entry_prices()` calls a price provider.
   - The review-list helper can store fetched rows, but the normal daily price path does not clearly write live Yahoo results back to shared cache.

6. **LLM evidence recovery is not inside Gate 8.**
   - Gate 7 quarantines LLM-required rows with missing evidence.
   - Gate 8 hard-stops when packets have empty evidence.
   - Needed behavior: attempt cache recovery/fetch/materialization inside the same daily run, rebuild packets, then stop only if recovery fails.

7. **Raw document loading is too narrow.**
   - Current `load_raw_documents_from_coverage()` mainly reads `live_sec/documents`.
   - Historical/cache evidence also lives in `sec_docs_text`, `sec_docs_html`, shared LLM extraction roots, and older raw 8-K folders.

8. **Status files are split and incomplete.**
   - The final run needs one clear row-level status surface showing kept, rejected, price-missing, SEC-missing, LLM-ready, LLM-complete, and LLM-recovery-failed.

9. **LLM recovery must start before packet build, not only after packet failure.**
   - `build_llm_eligibility()` currently quarantines LLM-required rows when coverage is not `CACHED_READY`.
   - Those rows never reach packet build, so a Gate 8-only recovery pass would miss them.
   - Proper fix: recover from the full set of LLM-required rows, including `llm_evidence_missing` and `missing_earnings_8k_or_press_release` quarantine rows from Gate 7.

10. **The plan must define SEC direct lookup precisely.**
   - “Search SEC directly” is too vague.
   - Proper fix: refresh official SEC ticker files first, then use SEC submissions/companyfacts endpoints when CIK is known, and use official SEC company search only for unresolved dealflow names.

11. **Companyfacts roots are split.**
   - Current pre-LLM scoring reads `live_sec/companyfacts/CIK##########.json`.
   - Older local facts also exist as `cache/sec/facts_<TICKER>.json`.
   - Proper fix: daily run should either materialize facts into `live_sec/companyfacts` or allow a safe fallback read before marking pre-LLM data missing.

12. **Missing metadata is not always a fetch problem.**
   - Coverage can end with `fetch_queue_count=0` but still miss earnings exhibit metadata.
   - Proper fix: LLM recovery must search cached text/html and archive indexes, then classify remaining gaps as “no earnings 8-K/press release found” or “metadata/parser routing gap,” not keep rerunning fetch.

13. **Rejected new dealflow tickers need separate accounting.**
   - A rejected new dealflow ticker should not silently reduce the broad master denominator.
   - Proper fix: keep rejected dealflow names in rejection/status artifacts, but only include SEC/tradable resolved names in the combined scoring universe.

14. **Master-list tickers with missing price must reconcile.**
   - Master tickers should not disappear from final math.
   - Proper fix: price-missing master rows go to explicit quarantine and count toward final reconciliation.

15. **LLM queue mode cannot be called final.**
   - `subagent` mode can write a job and stop.
   - Proper fix: queued LLM means run status is pending, not final. Final publish requires validated post-LLM rows.

16. **Yahoo fetching needs batching, partial cache writes, and failure reasons.**
   - A broad run can hit network/time limits.
   - Proper fix: fetch missing price rows in batches, write successful batches to cache as they complete, and mark failures clearly.

17. **Resolved new dealflow names need persistence.**
   - If a new dealflow ticker is resolved and scored today, tomorrow should not rediscover it from scratch.
   - Proper fix: keep the immutable 2021Q4 start file and add an append-only resolved-additions ledger. Daily runs read start file plus approved/resolved additions ledger.

18. **The CLI default must be tested through Typer, not only direct Python config.**
   - `fundamental-run-today` builds the default master path inside the CLI command.
   - Proper fix: add `tests/test_cli_fundamental_run_today.py` coverage with monkeypatched run service/config capture.

19. **Network behavior must be bounded.**
   - Automatic SEC/Yahoo work cannot hang a daily run indefinitely.
   - Proper fix: add max SEC recovery attempts, max price batches, per-request timeout, and pending status when limits are reached.

20. **The implementation must preserve existing compatibility artifacts.**
   - SEC helpers expect `final_dealflow_tickers_sec_eligible.json` as an internal coverage input.
   - Proper fix: keep internal compatibility copies, but do not treat them as the conceptual master source.

21. **Daily publish may pass a coverage file without enabling selector coverage gating.**
   - Standalone Top15 CLI sets `coverage_gating=True` when a coverage manifest is provided.
   - Daily `publish_top15_and_shadow()` passes `coverage_manifest` but must also set coverage gating in selector config.
   - Proper fix: add a daily publish test where a high-score uncovered ticker is blocked from Top10/Plus5.

22. **Missing daily dealflow handoff can be silent.**
   - Current CLI sets handoff to `None` if the default handoff file is missing.
   - Official daily runs should not silently run with zero dealflow append unless explicitly allowed.
   - Proper fix: broad final mode hard-stops when expected daily handoff is missing, unless `--allow-missing-handoff` is explicitly set.

23. **Ticker aliases must be canonical across SEC and Yahoo.**
   - SEC/Yahoo/share-class tickers can differ by dot/dash or old symbols.
   - Proper fix: keep `ticker` as canonical internal symbol, add `sec_ticker` and `yahoo_ticker` when they differ, and test `BRK.B`/`BRK-B` style normalization.

24. **Date and quarter mismatch can create wrong filing windows.**
   - User can pass `--date` and `--quarter` that do not belong together.
   - Proper fix: warn or hard-stop broad final mode when date-derived quarter disagrees with provided quarter unless explicitly overridden.

25. **Default master source cannot be only the immutable start file forever.**
   - If the daily run only reads the 2021Q4 start file, resolved new tickers will be rediscovered every day.
   - Proper fix: default daily universe input is `master_fundamental_universe_start_2021Q4.json` plus `master_fundamental_universe_additions.jsonl` when it exists.

---

## Non-Negotiables

- Do not create another pipeline.
- Do not make `fundamental-llm-backfill` the daily path.
- Do not start from the full SEC ticker map for the official daily run.
- Do not drop tickers only because local `sec_company_tickers.json` misses them.
- Do not publish Top 10 + Plus 5 + shadow refill if Gate 8 has unresolved required LLM rows.
- Do not call queued LLM work final until validated `post_llm_scores.csv` is present.
- Do not let rejected new dealflow tickers change the broad master denominator silently.
- Do not mutate the immutable 2021Q4 master start file during daily runs.
- Do not remove compatibility files if SEC helper code still needs them internally.
- Do not publish selector output unless coverage gating is active when a coverage manifest is provided.
- Do not silently ignore a missing daily dealflow handoff in official broad-final mode.
- Do not mix SEC/Yahoo ticker aliases without recording the mapping.
- Do not rediscover already-resolved additions every day; persist them in an append-only ledger.

---

## Review Loop Findings

Loop 1 found broad gaps:

- default master path was wrong.
- new dealflow identity fallback was missing.
- main price path did not clearly cache live Yahoo rows.
- LLM evidence recovery was outside the daily run.
- raw document loading was too narrow.

Loop 2 found hidden Gate 7/Gate 8 risk:

- LLM recovery cannot only run after packet build.
- Some LLM-required rows are quarantined at Gate 7 before packets exist.
- Plan fix: recovery must start from all LLM-required rows, including Gate 7 LLM quarantine rows and Gate 8 empty-packet rows.

Loop 3 found data-source/accounting risk:

- “SEC direct lookup” was too vague.
- companyfacts are split between `live_sec/companyfacts/CIK##########.json` and older `facts_<TICKER>.json`.
- rejected new dealflow tickers need separate status accounting.
- master-list tickers with missing price must remain in explicit quarantine and reconcile to the broad universe.
- queued LLM cannot be final.

Loop 4 found operational/persistence risk:

- resolved new dealflow names need a current-quarter master snapshot/proposed update so tomorrow does not rediscover them.
- CLI default path needs a Typer-level test.
- SEC/Yahoo network work needs bounded attempts and pending status.
- compatibility files can remain as internal adapter files while the official master source changes.

Loop 5 found publish gating risk:

- daily publish passes a coverage manifest but must explicitly enable selector coverage gating.
- add a daily publish regression so uncovered high-score names cannot enter Top10/Plus5.

Loop 6 found daily-input and symbol risk:

- missing daily handoff can silently become zero new dealflow names.
- ticker aliases need explicit canonical, SEC, and Yahoo symbols.
- date/quarter mismatch needs a guardrail.

Loop 7 found persistence risk:

- a “proposed update” artifact is not enough for daily automation.
- use immutable start file plus append-only resolved-additions ledger.
- default daily master is start file plus additions ledger, not the start file alone forever.

Current confidence statement:

- I am confident this plan now covers every known loophole found by code/doc review.
- Factual final confidence still requires the implementation tests in Task 11 to pass.
- No task is allowed to claim final daily-run readiness without those tests.

---

## Target File Changes

Modify:

- `tradingagents/research/fundamental/src/cli/commands.py`
  - Default `fundamental-run-today` to the 2021Q4 master start JSON plus additions ledger when `--master-universe` is not supplied.
  - Keep `--build-review-list-from-sec` as diagnostic/experimental, not the main route.

- `tradingagents/research/fundamental/src/daily_run/models.py`
  - Add config fields for master-start path, identity fallback roots, price cache writeback, LLM recovery attempt limits, network/fetch limits, missing-handoff policy, and date/quarter override policy.

- `tradingagents/research/fundamental/src/daily_run/orchestrator.py`
  - Wire identity resolution into Gate 2.
  - Wire price cache writeback into Gate 6.
  - Wire LLM evidence recovery into Gate 7/Gate 8 before hard-stop.

- `tradingagents/research/fundamental/src/daily_run/finalize.py`
  - Ensure daily publish enables selector coverage gating whenever a coverage manifest is supplied.

- `tradingagents/research/fundamental/src/daily_run/universe.py`
  - Preserve clear source labels and write dealflow add/rejection summaries.
  - Preserve canonical ticker plus SEC/Yahoo ticker aliases where needed.
  - Load immutable start file plus append-only additions ledger.

- `tradingagents/research/fundamental/src/daily_run/coverage.py`
  - Expose reusable document loading/materialization helpers for LLM recovery.

- `tradingagents/research/fundamental/docs/daily_run_gate_sequence.md`
  - Keep the plain daily operator steps and main-route rule current.

Create:

- `tradingagents/research/fundamental/src/daily_run/master_source.py`
  - Load immutable 2021Q4 start file plus append-only resolved-additions ledger.
  - Write daily combined master snapshots.

- `tradingagents/research/fundamental/src/daily_run/identity.py`
  - Resolve ticker, CIK, and company name using SEC map, complete panel, SEC facts, and SEC direct lookup.
  - Keep SEC direct lookup isolated behind injectable functions so tests do not hit the network.

- `tradingagents/research/fundamental/src/daily_run/price_cache.py`
  - Cache-first Yahoo price loading and writeback for the main daily price path.
  - Batch fetch missing rows and save successful batches immediately.

- `tradingagents/research/fundamental/src/daily_run/orchestrator.py`
  - Recover/fetch/materialize evidence for LLM-required rows inside the daily run.
  - Input includes both Gate 7 LLM quarantine rows and Gate 8 empty-packet rows.

- `tradingagents/research/fundamental/src/daily_run/status.py`
  - Build one plain row-level status file from existing gate outputs.

Tests:

- `tests/test_fundamental_daily_master_source.py`
- `tests/test_fundamental_daily_identity_resolution.py`
- `tests/test_fundamental_daily_price_cache.py`
- `tests/test_fundamental_daily_status.py`
- Extend `tests/test_cli_fundamental_run_today.py`
- Extend `tests/test_fundamental_daily_orchestrator_contract.py`
- Extend `tests/test_fundamental_daily_universe_gate.py`

---

## Task 1: Make The Master Start Plus Additions Ledger The Official Default

**Files:**

- Modify: `tradingagents/research/fundamental/src/cli/commands.py`
- Modify: `tradingagents/research/fundamental/src/daily_run/models.py`
- Create: `tradingagents/research/fundamental/src/daily_run/master_source.py`
- Test: `tests/test_cli_fundamental_run_today.py`
- Test: `tests/test_fundamental_daily_master_source.py`
- Test: `tests/test_fundamental_daily_universe_contract.py`

- [ ] **Step 1: Write failing test**

Add a test proving `fundamental-run-today` uses:

`tradingagents/research/fundamental/data/master_fundamental_universe_start_2021Q4.json`

plus `tradingagents/research/fundamental/data/master_fundamental_universe_additions.jsonl` when it exists, unless `--master-universe` is supplied.

Use Typer `CliRunner` and monkeypatch `run_daily_fundamental` or capture `DailyRunConfig`, because the default path is chosen inside the CLI command.

- [ ] **Step 2: Run test**

Run:

`python3 -m pytest tests/test_cli_fundamental_run_today.py tests/test_fundamental_daily_master_source.py tests/test_fundamental_daily_universe_contract.py -q`

Expected: fail because the default currently points near the output folder.

- [ ] **Step 3: Implement minimal default path**

Add constants for:

- master start file.
- additions ledger.

Implement a loader that combines start rows plus ledger rows, deduped by canonical ticker with the latest valid ledger identity taking precedence only for additions.

- [ ] **Step 4: Run test**

Expected: pass.

---

## Task 2: Add Daily Input Guardrails

**Files:**

- Modify: `tradingagents/research/fundamental/src/cli/commands.py`
- Modify: `tradingagents/research/fundamental/src/daily_run/models.py`
- Modify: `tradingagents/research/fundamental/src/daily_run/orchestrator.py`
- Test: `tests/test_cli_fundamental_run_today.py`
- Test: `tests/test_fundamental_daily_orchestrator_contract.py`

- [ ] **Step 1: Write failing tests**

Cases:

- broad-final mode with missing default handoff hard-stops unless explicitly allowed.
- diagnostic mode may run without handoff but reports `handoff_missing`.
- date-derived quarter mismatch hard-stops broad-final mode unless explicitly overridden.

- [ ] **Step 2: Run tests**

Run:

`python3 -m pytest tests/test_cli_fundamental_run_today.py tests/test_fundamental_daily_orchestrator_contract.py -q`

Expected: fail because missing handoff currently becomes `None`.

- [ ] **Step 3: Implement guardrails**

Add config/CLI options:

- `--allow-missing-handoff`
- `--allow-date-quarter-mismatch`

Default:

- broad-final: strict.
- diagnostic-only: allowed but reported.
- scout-smoke: allowed if user supplied a handoff or explicitly allows missing.

- [ ] **Step 4: Run tests**

Expected: pass.

---

## Task 3: Add Reusable Ticker Identity Resolution

**Files:**

- Create: `tradingagents/research/fundamental/src/daily_run/identity.py`
- Modify: `tradingagents/research/fundamental/src/daily_run/orchestrator.py`
- Test: `tests/test_fundamental_daily_identity_resolution.py`

- [ ] **Step 1: Write failing tests**

Cases:

- SEC map hit resolves CIK/name.
- SEC map miss falls back to complete panel.
- SEC map miss falls back to SEC facts.
- share-class alias keeps canonical ticker plus SEC/Yahoo ticker mapping.
- refreshed SEC ticker map resolves a stale local miss.
- SEC direct search is called only after local/cache fallbacks fail.
- unresolved ticker returns clear reason, not silent blank.

- [ ] **Step 2: Run tests**

Run:

`python3 -m pytest tests/test_fundamental_daily_identity_resolution.py -q`

Expected: fail because `identity.py` does not exist.

- [ ] **Step 3: Implement resolver**

Resolution order:

1. Existing master row.
2. Local SEC ticker map.
3. Refreshed official SEC ticker map.
4. Existing complete panel.
5. Local SEC facts.
6. SEC direct lookup/search through an injectable function.
7. Clear unresolved reason.

SEC direct lookup rules:

- Do not scrape random websites.
- Prefer official SEC data.
- Official SEC identity sources:
  - `https://www.sec.gov/files/company_tickers.json`
  - `https://www.sec.gov/files/company_tickers_exchange.json`
  - `https://www.sec.gov/files/company_tickers_mf.json` for fund/special-case classification.
  - SEC EDGAR company search/CIK lookup only when ticker files and trusted local sources fail.
- If a CIK is found, verify by fetching or checking SEC submissions/companyfacts.
- If no CIK can be found, keep the ticker out of the scoring universe and write the rejection reason.
- Tests must mock network calls.

Return plain statuses:

- `resolved_from_master`
- `resolved_from_sec_ticker_map`
- `resolved_from_refreshed_sec_ticker_map`
- `resolved_from_complete_panel`
- `resolved_from_sec_facts`
- `resolved_from_sec_direct`
- `no_sec_filer_found`
- `foreign_or_no_us_sec_filing`
- `fund_or_special_case`
- `ticker_or_name_unresolved`

Returned rows must include:

- `ticker`: canonical internal ticker.
- `sec_ticker`: symbol used for SEC lookup.
- `yahoo_ticker`: symbol used for Yahoo prices.
- `symbol_alias_reason`: blank or plain reason for the alias.

- [ ] **Step 4: Run tests**

Expected: pass.

---

## Task 4: Resolve New Dealflow Names Inside Gate 2

**Files:**

- Modify: `tradingagents/research/fundamental/src/daily_run/universe.py`
- Modify: `tradingagents/research/fundamental/src/daily_run/orchestrator.py`
- Test: `tests/test_fundamental_daily_universe_gate.py`

- [ ] **Step 1: Write failing orchestrator test**

Build a master list with one ticker and a handoff with one new ticker. Mock the resolver to return CIK/name for the new ticker. The combined universe should include both rows and pass Gate 2.

Add a second case where a new handoff ticker is unresolved. It must be written to rejection artifacts and must not enter the scoring universe.

- [ ] **Step 2: Run test**

Run:

`python3 -m pytest tests/test_fundamental_daily_universe_gate.py -q`

Expected: fail because the orchestrator does not call resolver.

- [ ] **Step 3: Implement Gate 2 resolver call**

Before `build_combined_universe()`, collect handoff tickers not already in the master list. Resolve them and pass resolved rows through `unresolved_new_scouts`.

Rules:

- Existing master tickers keep master identity.
- New resolved dealflow tickers enter the combined universe.
- New unresolved/rejected dealflow tickers do not enter the combined scoring universe.
- Rejected new dealflow tickers are still written to status/rejection artifacts.
- Broad master denominator is master rows plus resolved new dealflow rows, not rejected dealflow rows.
- The immutable 2021Q4 start file is not edited.
- The run writes a current-quarter combined master snapshot.
- New resolved dealflow names are appended to the additions ledger only after identity and SEC filer verification pass.

- [ ] **Step 4: Write artifacts**

Write:

- `dealflow_identity_resolution.csv`
- `dealflow_identity_rejections.csv`
- `universe_source_summary.json`
- `master_fundamental_universe_<quarter>.json`
- `master_fundamental_universe_additions_pending_<quarter>.json`
- updated append-only `master_fundamental_universe_additions.jsonl` when additions are approved/resolved

- [ ] **Step 5: Run tests**

Expected: pass.

---

## Task 5: Make Price Check Cache-First And Write Back New Yahoo Rows

**Files:**

- Create: `tradingagents/research/fundamental/src/daily_run/price_cache.py`
- Modify: `tradingagents/research/fundamental/src/daily_run/scoring_inputs.py`
- Modify: `tradingagents/research/fundamental/src/daily_run/orchestrator.py`
- Test: `tests/test_fundamental_daily_price_cache.py`

- [ ] **Step 1: Write failing tests**

Cases:

- cached rows are used without Yahoo call.
- missing rows are fetched from Yahoo.
- fetched rows are saved to shared cache and run cache.
- partial batch success is saved even if a later batch fails.
- output clearly separates price-missing from SEC-missing.

- [ ] **Step 2: Run tests**

Run:

`python3 -m pytest tests/test_fundamental_daily_price_cache.py -q`

Expected: fail because main price path lacks cache writeback helper.

- [ ] **Step 3: Implement helper**

Add one helper used by Gate 6:

- load cached prices first.
- fetch missing ticker/date range only.
- fetch in batches using `review_price_batch_size` or a new daily price batch size.
- save each successful fetched batch to shared market cache and run folder.
- return combined rows.
- return failures with clear reasons.
- stop at configured max batch attempts and mark remaining rows pending/failed.

Important reconciliation rule:

- Master-list rows with missing price stay in explicit price quarantine.
- They count in `explicit_invalid_quarantine_count`.
- They must not silently disappear from final row-count reconciliation.

- [ ] **Step 4: Run tests**

Expected: pass.

---

## Task 6: Add LLM Evidence Recovery Inside Daily Run

**Files:**

- Modify: `tradingagents/research/fundamental/src/daily_run/orchestrator.py`
- Modify: `tradingagents/research/fundamental/src/daily_run/coverage.py`
- Test: `tests/test_fundamental_daily_orchestrator_contract.py`

- [ ] **Step 1: Write failing tests**

Cases:

- required row quarantined at Gate 7 with `llm_evidence_missing` is recovered before packet build.
- required row quarantined at Gate 7 with `missing_earnings_8k_or_press_release` is recovered before packet build.
- required row missing packet recovers from `sec_docs_text`.
- required row missing packet recovers from `sec_docs_html` by converting to text.
- required row missing packet triggers SEC fetch when cache is empty.
- `fetch_queue_count=0` with missing metadata becomes a clear metadata/parser/no-evidence reason, not an infinite fetch loop.
- unrecoverable row gets clear reason.

- [ ] **Step 2: Run tests**

Run:

`python3 -m pytest tests/test_fundamental_daily_orchestrator_contract.py -q`

Expected: fail until Gate 7 recovery and Gate 8 empty-packet recovery are wired.

- [ ] **Step 3: Implement recovery logic**

Input:

- LLM-required rows.
- coverage rows.
- Gate 7 LLM quarantine rows.
- current Gate 8 packet quarantine rows.
- SEC roots.
- fetch runner.

Output:

- recovered document rows.
- updated coverage rows where possible.
- recovery status CSV rows.
- summary counts.

Statuses:

- `packet_ready_from_cache`
- `packet_ready_after_html_text_conversion`
- `packet_ready_after_sec_fetch`
- `no_earnings_8k_or_press_release_found`
- `metadata_or_parser_routing_gap`
- `unresolved_ticker_or_cik`
- `foreign_or_no_us_sec_filing`
- `fund_or_special_case`

Recovery order:

1. Search `live_sec/documents`.
2. Search `sec_docs_text`.
3. Search `sec_docs_html` and convert usable HTML to text/document rows.
4. Search older raw 8-K folders.
5. Search archive indexes for exhibit candidates.
6. Run SEC fetch only when a real fetch queue exists.
7. Re-run coverage and reload raw documents.
8. Classify remaining rows with a plain reason.

Bounded-work rule:

- obey max SEC recovery attempts.
- obey SEC rate limits and request timeouts.
- if work remains after configured limits, mark the run pending evidence recovery, not final.

- [ ] **Step 4: Run tests**

Expected: pass.

---

## Task 7: Wire LLM Recovery Into Gate 7 And Gate 8

**Files:**

- Modify: `tradingagents/research/fundamental/src/daily_run/orchestrator.py`
- Modify: `tradingagents/research/fundamental/src/daily_run/eligibility.py`
- Test: `tests/test_fundamental_daily_orchestrator_contract.py`

- [ ] **Step 1: Write failing test**

Create a daily run where one HP/RM/Tier row needs LLM, initial packet build fails, recovery finds the document, packet rebuild succeeds, and Gate 8 proceeds.

Add another case where the row is stopped at Gate 7 because coverage is not `CACHED_READY`; recovery must still run and make it eligible before packet build.

- [ ] **Step 2: Run test**

Run:

`python3 -m pytest tests/test_fundamental_daily_orchestrator_contract.py -q`

Expected: fail because Gate 8 hard-stops before recovery.

- [ ] **Step 3: Implement recovery loop**

Gate 8 flow:

1. Build the full LLM-required set from tiered rows.
2. Split it into evidence-ready rows and evidence-missing rows.
3. If evidence-missing rows exist, call LLM evidence recovery before packet build.
4. Re-run/reload coverage and raw documents.
5. Build packets from recovered evidence-ready rows.
6. If packet count matches required evidence-ready count and no required rows remain unresolved, continue.
7. If required rows remain unresolved, hard-stop with clear recovery status.
8. If recovered, continue to LLM run/queue.

Queue-mode rule:

- If `llm_mode=subagent` writes a job, the daily run stops as pending LLM.
- It must not publish final Top 10 + Plus 5 + shadow refill until the validated post-file rerun completes.

- [ ] **Step 4: Save artifacts**

Write:

- `llm_evidence_recovery_status.csv`
- `llm_evidence_recovery_summary.json`
- updated `llm_empty_evidence_quarantine.csv`
- updated `llm_quarantine.csv`

- [ ] **Step 5: Run tests**

Expected: pass.

---

## Task 8: Handle Companyfacts Split Roots

**Files:**

- Modify: `tradingagents/research/fundamental/src/daily_run/scoring_inputs.py`
- Modify: `tradingagents/research/fundamental/src/daily_run/orchestrator.py`
- Test: `tests/test_fundamental_daily_orchestrator_contract.py`

- [ ] **Step 1: Write failing test**

Create a ticker with no `live_sec/companyfacts/CIK##########.json` but with a trusted fallback `cache/sec/facts_<TICKER>.json`. Pre-LLM scoring should use the fallback or materialize it into the live cache.

- [ ] **Step 2: Run test**

Run:

`python3 -m pytest tests/test_fundamental_daily_orchestrator_contract.py -q`

Expected: fail if scoring only reads `live_sec/companyfacts`.

- [ ] **Step 3: Implement safe fallback**

Allowed behavior:

- Prefer `live_sec/companyfacts/CIK##########.json`.
- If missing, use `facts_<TICKER>.json` only when ticker and CIK/company identity agree with the resolved universe row.
- Optionally copy/materialize fallback facts into the live cache path.
- If neither exists and SEC fetch cannot obtain it, mark pre-LLM data missing.

- [ ] **Step 4: Run tests**

Expected: pass.

---

## Task 9: Improve Final Status Files

**Files:**

- Modify: `tradingagents/research/fundamental/src/daily_run/orchestrator.py`
- Modify: `tradingagents/research/fundamental/src/daily_run/universe.py`
- Create: `tradingagents/research/fundamental/src/daily_run/status.py`
- Modify: `tradingagents/research/fundamental/docs/daily_run_gate_sequence.md`
- Test: `tests/test_fundamental_daily_status.py`

- [ ] **Step 1: Write failing test**

Assert the run writes a single status file with one row per ticker and columns:

- `ticker`
- `quarter`
- `source_status`
- `identity_status`
- `sec_status`
- `price_status`
- `pre_llm_status`
- `llm_required_status`
- `llm_packet_status`
- `llm_completion_status`
- `final_score_status`
- `rejection_reason`

It must include rejected new dealflow tickers even when they did not enter the scoring universe.

- [ ] **Step 2: Run test**

Expected: fail because the unified status file does not exist.

- [ ] **Step 3: Implement status writer**

Build it from existing gate outputs. Do not recompute scores.

- [ ] **Step 4: Run tests**

Expected: pass.

---

## Task 10: Enforce Coverage Gating During Daily Publish

**Files:**

- Modify: `tradingagents/research/fundamental/src/daily_run/finalize.py`
- Test: `tests/test_fundamental_daily_orchestrator_contract.py`

- [ ] **Step 1: Write failing test**

Build final scores where the highest-scoring ticker has SEC coverage status `NEEDS_FETCH` and another valid ticker has `CACHED_READY`. Daily publish must select the valid ticker, not the uncovered high-score ticker.

- [ ] **Step 2: Run test**

Run:

`python3 -m pytest tests/test_fundamental_daily_orchestrator_contract.py -q`

Expected: fail if daily publish passes the coverage file but does not enable selector coverage gating.

- [ ] **Step 3: Implement fix**

In `publish_top15_and_shadow()`, set `coverage_gating=True` in the Top15 and shadow selector configs whenever `coverage_manifest` exists.

- [ ] **Step 4: Run tests**

Expected: pass.

---

## Task 11: End-To-End Verification

**Files:**

- Modify only if verification finds defects.

- [ ] **Step 1: Run focused tests**

Run:

`python3 -m pytest tests/test_cli_fundamental_run_today.py tests/test_fundamental_daily_master_source.py tests/test_fundamental_daily_identity_resolution.py tests/test_fundamental_daily_price_cache.py tests/test_fundamental_daily_status.py tests/test_fundamental_daily_universe_gate.py tests/test_fundamental_daily_orchestrator_contract.py -q`

Expected: pass.

- [ ] **Step 2: Run daily fundamental suite**

Run:

`python3 -m pytest tests/test_fundamental_daily_*.py tests/test_fundamental_review_list_filter.py -q`

Expected: pass.

- [ ] **Step 3: Run compile check**

Run:

`python3 -m py_compile tradingagents/research/fundamental/src/daily_run/identity.py tradingagents/research/fundamental/src/daily_run/price_cache.py tradingagents/research/fundamental/src/daily_run/orchestrator.py tradingagents/research/fundamental/src/cli/commands.py`

Expected: pass.

- [ ] **Step 4: Run diagnostic daily smoke**

Run:

`python3 -m cli.main fundamental-run-today --mode diagnostic-only --date 2026-05-14 --quarter 2026Q2 --skip-llm --output-root eval_results/fundamental/2026-05-14_daily_orchestration_smoke`

Expected:

- starts from master start list.
- appends today's dealflow.
- writes identity, SEC, price, LLM, and final status artifacts.
- writes internal compatibility copy `final_dealflow_tickers_sec_eligible.json` only for SEC helper compatibility.
- does not publish final rankings because diagnostic mode skips publish.

- [ ] **Step 5: Run final-mode pending-LLM smoke**

Run with `--llm-mode subagent`.

Expected:

- writes LLM job.
- does not publish Top 10 + Plus 5 + shadow refill.
- run report says pending LLM, not final.

- [ ] **Step 6: Run final-mode post-file smoke**

Run with a validated test post-LLM CSV.

Expected:

- validates post-LLM rows.
- builds final scores.
- publishes Top 10 + Plus 5 + shadow refill only after validation.

- [ ] **Step 7: Run bounded-network failure smoke**

Use mocked SEC/Yahoo providers that fail after one successful batch.

Expected:

- successful batch is cached.
- failed batch has a clear reason.
- run status is pending/stopped, not final.

---

## Definition Of Done

- `fundamental-run-today` is still the only daily main path.
- Default master source is the 2021Q4 SEC-evidence start list.
- New dealflow tickers are resolved automatically before Gate 2 hard-stop.
- Price data is cache-first and fetched rows are saved.
- LLM-required rows get evidence recovery inside the daily run before Gate 8 hard-stop.
- Top 10 + Plus 5 + shadow refill are published only from broad final scores.
- Every rejected or blocked ticker has a plain reason in a status file.

## Implementation Completion Note - 2026-05-14

- Done: new dealflow tickers are resolved before Gate 2 and unresolved new names are rejected before scoring.
- Done: the current-quarter master JSON is the full combined daily list, not only additions, and later SEC steps use that combined JSON.
- Done: daily price lookup is cache-first, live fetches only missing tickers, and fetched rows are saved to run/shared caches.
- Done: companyfacts fallback copies shared `facts_TICKER.json` into the live daily companyfacts folder before coverage/scoring.
- Done: LLM evidence recovery is inside the daily run; it uses SEC raw document caches, materializes recovered docs to the live folder, and only calls SEC fetch when a queue exists or a fetch service is provided.
- Done: Gate 8 now retries packet build after empty-evidence packet recovery before hard-stopping.
- Done: Gate 7 now hard-stops broad-final runs if LLM-required rows still have missing evidence after recovery.
- Done: the daily run writes `daily_ticker_status.csv` with plain status/reason columns.
- Done: Top10 + Plus5 + shadow publish receives coverage gating when a coverage manifest exists.
- Done: default identity resolution now checks trusted panel fallback and supports SEC direct lookup before rejecting a new dealflow ticker.
- Done: daily price cache logic now treats stale/partial cached rows as incomplete for the required entry-date window and fetches the missing range when live fetch is allowed.
- Done: resolved dealflow additions are written to the persistent additions ledger only after the ticker appears in final scored rows.
- Verification: `python3 -m pytest tests/test_fundamental_daily_*.py tests/test_fundamental_review_list_filter.py tests/test_cli_fundamental_run_today.py tests/test_fundamental_architecture_contract.py tests/test_fundamental_no_growth_output_ownership.py -q` -> 114 passed.
- Verification: `python3 -m py_compile` on touched daily-run modules -> passed.
