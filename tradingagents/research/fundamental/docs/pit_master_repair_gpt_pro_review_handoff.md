# PIT Master Repair GPT Pro Review Handoff

Purpose: give the reviewer the exact branch, schema proof, mapping proof, and first smoke outputs requested for the PIT master repair review.

## Target

- Branch: `pit-master-repair-row-contract`
- Worktree: `/Users/aeternusholdings/.config/superpowers/worktrees/Aeternus/pit-master-repair-row-contract`
- Base implementation commit before this handoff/follow-up patch: `c8638a4b`
- Review latest branch head with: `git rev-parse HEAD`

## Price Cache Schema

Code paths:

- Price ingest: `tradingagents/research/fundamental/src/ingest/prices.py`
- Entry-open attachment: `tradingagents/research/fundamental/src/daily_run/scoring_inputs.py`
- Trading-session helper: `tradingagents/research/fundamental/src/ingest/trading_calendar.py`

Rules now exposed in output rows:

- Raw Yahoo OHLCV only: `Open`, `High`, `Low`, `Close`, `Volume`.
- `Adj Close` is rejected from raw cache ingest.
- `entry_open` and `entry_open_raw` are raw open.
- `entry_open_price_basis = raw_open`.
- `entry_open_adjusted_for_return_calc` is the split-adjusted entry price when available, otherwise raw open.
- `return_price_basis = split_adjusted`.
- `price_adjustment_mode = split_adjusted_for_returns`.
- `adjustment_factor = entry_open_adjusted_for_return_calc / entry_open_raw`.
- Return labels use adjusted return basis, not mixed raw-open / adjusted-close basis.

Execution timing label:

- Current smoke rows show `score_timing_mode = post_open_research_score`.
- Current smoke rows show `execution_timing_mode = next_session_executable`.
- Meaning: because `entry_open` is available to scoring, same-open execution must not be assumed for no-forward-bias backtest execution. Full executable mode should use next executable price after score time.

## Ticker / CIK Mapping Source

Code paths:

- Identity resolver: `tradingagents/research/fundamental/src/daily_run/identity.py`
- Daily universe builder: `tradingagents/research/fundamental/src/daily_run/universe.py`
- Row contract validator: `tradingagents/research/fundamental/src/daily_run/row_contract.py`
- Score-input output fields: `tradingagents/research/fundamental/src/daily_run/scoring_inputs.py`

Resolution order for new names:

1. Master row.
2. Local SEC ticker map.
3. Refreshed SEC ticker map.
4. Trusted complete panel.
5. Local SEC facts.
6. SEC direct lookup/search.

Per-row output fields now emitted in smoke final-score CSVs:

- `cik`
- `cik10`
- `security_id`
- `ticker_as_of_decision_date`
- `ticker_mapping_source`
- `ticker_mapping_source_date`
- `ticker_mapping_effective_date`
- `ticker_mapping_pit_valid_flag`
- `ticker_mapping_missing_reason`
- `price_ticker_used`
- `facts_cik_used`
- `ticker_cik_mapping_confidence`

Smoke sample:

- `ticker_mapping_source = master_fundamental_universe_start_2021Q4.json`
- `ticker_mapping_source_date = 2021-12-31`
- `ticker_mapping_effective_date = 2021-12-31`
- `ticker_mapping_pit_valid_flag = 1`

## Smoke Output 1: 2022Q1

Command:

`/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m cli.main fundamental-run-smoke --date 2022-03-31 --quarter 2022Q1 --master-universe tradingagents/research/fundamental/data/master_fundamental_universe_start_2021Q4.json --prior-final-scores /Users/aeternusholdings/Documents/Aeternus/tradingagents/research/fundamental/runs/2021-12-31/2021Q4/walkforward_clean_v1/qoq_context_only_2021Q4.csv --allow-missing-handoff --output-root tradingagents/research/fundamental/runs/2022-03-31/2022Q1/pit_repair_smoke_v3 --format json`

Output root:

- `/Users/aeternusholdings/.config/superpowers/worktrees/Aeternus/pit-master-repair-row-contract/tradingagents/research/fundamental/runs/2022-03-31/2022Q1/pit_repair_smoke_v3`

Key files:

- Final smoke scores: `fundamental_final_scores_2022-03-31.csv`
- Final smoke summary: `fundamental_final_scores_2022-03-31_summary.json`
- Readiness JSON: `publish_readiness_summary.json`
- SEC coverage: `sec_coverage_manifest_2022Q1.csv`
- LLM job file: `lake/artifacts/2022Q1_llm_packets.jsonl`
- Gate files: `gates/gate_01.json` through `gates/gate_10.json`

Result:

- Final: `false`
- Mode: `scout-smoke`
- Rows in final smoke scores: `201`
- Columns in final smoke scores: `281`
- Missing required review columns: `0`
- Gates 1-7: `pass`
- Gate 8: `skipped`
- Gate 9: `pass`
- Gate 10: `skipped`
- Stop reason: `publish_skipped`

## Smoke Output 2: 2026Q1

Command:

`/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m cli.main fundamental-run-smoke --date 2026-03-31 --quarter 2026Q1 --master-universe tradingagents/research/fundamental/data/master_fundamental_universe_start_2021Q4.json --prior-final-scores /Users/aeternusholdings/Documents/Aeternus/tradingagents/research/fundamental/runs/2025-12-31/2025Q4/walkforward_clean_v1/fundamental_final_scores_2025-12-31.csv --allow-missing-handoff --output-root tradingagents/research/fundamental/runs/2026-03-31/2026Q1/pit_repair_smoke_v3 --format json`

Output root:

- `/Users/aeternusholdings/.config/superpowers/worktrees/Aeternus/pit-master-repair-row-contract/tradingagents/research/fundamental/runs/2026-03-31/2026Q1/pit_repair_smoke_v3`

Key files:

- Final smoke scores: `fundamental_final_scores_2026-03-31.csv`
- Final smoke summary: `fundamental_final_scores_2026-03-31_summary.json`
- Readiness JSON: `publish_readiness_summary.json`
- SEC coverage: `sec_coverage_manifest_2026Q1.csv`
- Prior LLM recovery manifest: `prior_llm_recovery/sec_coverage_manifest_2025Q4.csv`
- LLM job file: `lake/artifacts/2026Q1_llm_packets.jsonl`
- Gate files: `gates/gate_01.json` through `gates/gate_10.json`

Result:

- Final: `false`
- Mode: `scout-smoke`
- Rows in final smoke scores: `191`
- Columns in final smoke scores: `281`
- Missing required review columns: `0`
- Gates 1-7: `pass`
- Gate 8: `skipped`
- Gate 9: `pass`
- Gate 10: `skipped`
- Stop reason: `publish_skipped`

## Smoke Scope

Smoke mode is intentionally not a full publish:

- No LLM extraction.
- No Top 10 / Plus 5 / shadow publish.
- It proves universe, SEC evidence cache, price cache, PIT financial scoring input, row identity fields, raw/adjusted price fields, LLM packet construction, and pre-final score wiring.

Full acceptance still requires full quarter rebuilds after reviewer approval.
