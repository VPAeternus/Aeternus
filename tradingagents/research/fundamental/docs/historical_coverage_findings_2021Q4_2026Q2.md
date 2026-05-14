# Historical Coverage Findings: 2021Q4 to 2026Q2

Last updated: 2026-05-14T08:02:06-04:00

Purpose: permanent plain-English reference for historical fundamental coverage questions.

## Bottom Line

The complete panel for `2021Q4` through `2026Q2` has `23,602` ticker-quarter rows and includes `2026Q2`.

It is enough to review and replay the current scored panel. It is not enough to honestly say every score can be cleanly recalculated from raw source inputs without more LLM work, because some rows marked LLM-required are still missing completed LLM extraction.

Important: not every ticker gets LLM review. LLM review applies only to rows the framework marks as LLM-required.

## Main Files

- Complete panel: `outputs/fundamental_backtest/full_complete_panel_2021Q4_2026Q2/fundamental_complete_prellm_to_top15_2021Q4_2026Q2.csv`
- Historical LLM backfill prep command: `fundamental-llm-backfill --start-quarter 2021Q4 --end-quarter 2026Q2`
- Evidence summary: `eval_results/fundamental/sec_evidence_inventory_2021Q4_2026Q2/sec_evidence_inventory_summary.json`
- Evidence ticker-quarter inventory: `eval_results/fundamental/sec_evidence_inventory_2021Q4_2026Q2/sec_evidence_ticker_quarter_inventory.csv`
- Quarter coverage summary: `eval_results/fundamental/sec_evidence_inventory_2021Q4_2026Q2/sec_evidence_quarter_coverage_summary.csv`
- Score field coverage check: `eval_results/fundamental/sec_evidence_inventory_2021Q4_2026Q2/panel_score_field_coverage_by_quarter.json`
- Unique ticker list: `eval_results/fundamental/sec_evidence_inventory_2021Q4_2026Q2/unique_tickers_2021Q4_2026Q2.csv`
- Plain ticker list: `eval_results/fundamental/sec_evidence_inventory_2021Q4_2026Q2/unique_tickers_2021Q4_2026Q2.txt`
- Inventory script: `tradingagents/research/fundamental/src/sec_pipeline/evidence_inventory.py`

## Row Counts

- Total complete-panel rows: `23,602`
- Historical rows from `2021Q4` through `2026Q1`: `22,303`
- Current `2026Q2` rows: `1,299`
- Unique tickers across the full period: `1,319`
- Tickers with all `19` quarters present in the complete panel: `1,023`

## All-Root Evidence Coverage

This count checks all known evidence roots, not only the current `live_sec` cache.

- Tickers with some evidence anywhere: `6,852`
- Tickers with quarter-level evidence: `1,413`
- Ticker-quarter evidence rows: `23,806`
- Tickers with all `19` quarters represented by at least one quarter-level evidence source: `1,035`

Important meaning: this is broad evidence coverage across raw SEC files, company facts, LLM outputs, old score CSVs, complete panel rows, and price cache. It is not the same as fully scoring-ready.

## Coverage By Quarter

| Quarter | Tickers with evidence |
|---|---:|
| 2021Q4 | 1,251 |
| 2022Q1 | 1,204 |
| 2022Q2 | 1,212 |
| 2022Q3 | 1,221 |
| 2022Q4 | 1,224 |
| 2023Q1 | 1,223 |
| 2023Q2 | 1,223 |
| 2023Q3 | 1,249 |
| 2023Q4 | 1,254 |
| 2024Q1 | 1,264 |
| 2024Q2 | 1,262 |
| 2024Q3 | 1,391 |
| 2024Q4 | 1,249 |
| 2025Q1 | 1,249 |
| 2025Q2 | 1,248 |
| 2025Q3 | 1,266 |
| 2025Q4 | 1,261 |
| 2026Q1 | 1,255 |
| 2026Q2 | 1,300 |

## Score Recalculation Readiness

Current panel score fields:

- `23,602 / 23,602` rows have `entry_score_0_100`
- `23,602 / 23,602` rows have entry price
- `23,588 / 23,602` rows have pre-LLM score
- `7,617` rows are marked LLM-required
- `6,515` rows are both LLM-required and LLM-complete
- `1,102` rows are LLM-required but not LLM-complete
- `4` rows are LLM-complete but not marked LLM-required by the derived flag

Meaning: current files can reproduce current panel outputs, but full clean recalculation of every LLM-required row needs either recovered historical LLM extracts or rerun LLM extraction for the required-but-not-complete ticker-quarters.

Do not describe `1,102` as "missing LLM for all tickers." Correct wording is: `1,102` ticker-quarter rows are marked LLM-required but are not LLM-complete by the current panel flags.

## Historical LLM Backfill Prep And Trigger

Use `fundamental-llm-backfill` to scan a complete panel across an editable quarter range, prepare missing-row artifacts, build runnable evidence packets where source text exists, and optionally trigger existing LLM runner modes. It targets only rows that are both:

- marked LLM-required, and
- not marked LLM-complete.

Safe prepare-only command:

`fundamental-llm-backfill --panel-csv outputs/fundamental_backtest/full_complete_panel_2021Q4_2026Q2/fundamental_complete_prellm_to_top15_2021Q4_2026Q2.csv --start-quarter 2021Q4 --end-quarter 2026Q2`

Trigger options:

- `--llm-mode prepare`: write artifacts only. This is the default.
- `--llm-mode subagent`: write `llm_subagent_job.json` against runnable evidence packets.
- `--llm-mode in-session`: run the existing in-session LLM helper against runnable evidence packets.
- `--llm-mode external`: run the existing external LLM script against runnable evidence packets.
- `--llm-mode post-file --post-llm <csv>`: validate an existing post-LLM CSV against generated packet sample IDs. It does not merge results back into the panel yet.

Default output root:

`eval_results/fundamental/llm_backfill_2021Q4_2026Q2`

Artifacts:

- `historical_llm_backfill_missing_required_rows.csv`
- `historical_llm_backfill_missing_tickers.txt`
- `historical_llm_backfill_summary.json`
- `historical_llm_backfill_missing_manifest.jsonl`
- `historical_llm_backfill_evidence_packets.jsonl`
- `historical_llm_backfill_evidence_missing.csv`

Important: `historical_llm_backfill_missing_manifest.jsonl` is only a missing-row manifest with `sample_id`, ticker, quarter, and original panel row. The runnable packet file is `historical_llm_backfill_evidence_packets.jsonl`; it is built only when earnings/8-K text is found under `--sec-text-root`.

Evidence lookup first uses panel link fields such as `earnings_8k_accession`, `earnings_8k_primary_document`, `earnings_exhibit_document`, and `text_path`. If those fields are blank or do not locate files, it conservatively scans `TICKER_*` files under `--sec-text-root` and only accepts filenames with matching quarter tokens such as `q1x2024`, `q1-2024`, `q12024`, or `2024q1`. Generic `10-Q` and `10-K` text is not used for LLM packets.

Runnable evidence packets sanitize candidate rows before LLM input. They keep identity and pre-LLM scoring context, but remove forward returns, winner/loser labels, outcome fields, selection/top15/shadow fields, diagnostics, price fields, and QoQ fields. The full unsanitized panel row remains only in the audit manifest.

## 2026Q2 Specific Readiness

`2026Q2` is included in the `23,602` total.

- `1,299 / 1,299` rows have pre-LLM score
- `1,299 / 1,299` rows have entry price
- `1,299 / 1,299` rows have entry score
- `256` rows are LLM-required
- `205` rows are both LLM-required and LLM-complete
- `51` rows are LLM-required but still pending
- `4` rows are LLM-complete but not marked LLM-required by the derived flag
- `209` rows have `llm_status = complete` in total

## Source Count Notes

The prior narrow live-cache check found only `142` tickers fully ready across all `19` quarters. That was too narrow for historical coverage because it did not include all roots listed by the user.

The all-root inventory is broader and should be used when the question is:

"What historical evidence do we already have across `2021Q4` to `2026Q2`?"

The strict readiness check should be used when the question is:

"Can we recalculate every score cleanly from raw source inputs right now?"

For that second question, answer is currently: no, because `1,102` LLM-required ticker-quarters are not LLM-complete.
